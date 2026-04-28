"""Support code for the generation CLI adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.application import GenerateTestPlanOptions, GenerateTestPlanRequest, GenerationInputMode
from tools.generation.application.use_cases import GenerateTestPlanUseCase
from tools.generation.authoring import AgentPlanAuthoringService
from tools.generation.authoring_contract import AuthoringPlanCompiler
from tools.generation.cli_authoring_bundle import _evaluate_authoring_bundle
from tools.generation.cli_core import (
    GenerationCliInputError,
    _dedupe_preserve_order,
    _managed_bundle_dir_for_authoring_path,
)
from tools.generation.cli_diagnostics import _adapter_diagnostics
from tools.generation.domain.gaps import format_case_gap_note, project_case_gap
from tools.generation.domain.models import (
    AgentTestPlanInput,
    GenerationSourceInput,
    PlannedCaseGap,
    SourceInputFormat,
)


def build_request(args: argparse.Namespace) -> GenerateTestPlanRequest:
    diagnostics = _adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)

    input_mode = _resolve_input_mode(args)
    authoring_plan_result = _compile_authoring_plan_file(Path(args.authoring_plan_file)) if args.authoring_plan_file else None
    agent_plan = _load_agent_plan_file(Path(args.agent_plan_file)) if args.agent_plan_file else None
    if authoring_plan_result is not None:
        authoring_plan = authoring_plan_result.authoring_plan
        agent_plan = authoring_plan_result.compiled_plan
        source_input = GenerationSourceInput(
            source_id="" if authoring_plan is None else authoring_plan.source_id,
            project="" if authoring_plan is None else authoring_plan.project,
            input_format=SourceInputFormat.STRUCTURED,
            name="" if authoring_plan is None else authoring_plan.title,
            content="" if authoring_plan is None else json.dumps(authoring_plan.to_dict(), ensure_ascii=False),
            source_path=Path(args.authoring_plan_file),
            metadata={"input_mode": GenerationInputMode.AUTHORING_PLAN.value},
        )
    elif agent_plan is not None:
        source_input = GenerationSourceInput(
            source_id=agent_plan.source_id,
            project=agent_plan.project,
            input_format=SourceInputFormat.STRUCTURED,
            name=agent_plan.title,
            content=json.dumps(agent_plan.to_dict(), ensure_ascii=False),
            source_path=Path(args.agent_plan_file),
            metadata={"input_mode": GenerationInputMode.AGENT_PLAN.value},
        )
    else:
        source_input = GenerationSourceInput(
            source_id=args.source_id,
            project=args.project,
            name=args.name,
            input_format=SourceInputFormat.PROSE,
            content=args.prose or "",
            source_path=Path(args.source_file) if args.source_file else None,
            metadata={"input_mode": GenerationInputMode.PROSE.value},
        )
    return GenerateTestPlanRequest(
        source_input=source_input,
        input_mode=input_mode,
        agent_plan=agent_plan,
        workspace_root=Path(args.workspace_root),
        options=GenerateTestPlanOptions(
            persist_artifacts=not args.no_persist,
            render_scenario_drafts=args.render_drafts,
        ),
    )



def run_generation(args: argparse.Namespace) -> dict[str, Any]:
    request = build_request(args)
    result = GenerateTestPlanUseCase().execute(request)
    return summarize_result(result)



def summarize_result(result: Any) -> dict[str, Any]:
    scenario_render_result = result.scenario_render_result
    unresolved_intents = _scenario_unresolved_intents(scenario_render_result)
    return to_json_safe(
        {
            "status": result.final_status.value,
            "message": result.message,
            "run_id": result.run_context.run_id,
            "source_id": result.run_context.source_id,
            "project": result.run_context.project,
            "bundle_dir": result.run_context.artifact_dir,
            "agent_plan_path": result.artifact_paths.get("agent_plan"),
            "input_mode": result.details.get("input_mode", "prose"),
            "test_case_count": len(result.normalized_plan.test_cases),
            "scenario_rendering": result.details.get("scenario_rendering", "not_requested"),
            "scenario_draft_count": (
                len(scenario_render_result.draft_set.drafts) if scenario_render_result else 0
            ),
            "scenario_deferred_count": (
                len(scenario_render_result.draft_set.deferred_items) if scenario_render_result else 0
            ),
            "scenario_parse_valid_count": (
                sum(1 for item in scenario_render_result.validation_results if item.parse_valid)
                if scenario_render_result
                else 0
            ),
            "scenario_unresolved_intent_count": sum(item["gap_count"] for item in unresolved_intents),
            "scenario_unresolved_intents": unresolved_intents,
            "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
            "artifact_paths": result.artifact_paths,
        }
    )



def _scenario_unresolved_intents(scenario_render_result: Any) -> list[dict[str, Any]]:
    if scenario_render_result is None:
        return []
    summaries_by_case_id: dict[str, dict[str, Any]] = {}
    for draft in scenario_render_result.draft_set.drafts:
        raw_gaps = draft.metadata.get("case_gaps", [])
        if not isinstance(raw_gaps, list):
            continue
        gaps = [
            PlannedCaseGap.from_dict(item)
            for item in raw_gaps
            if isinstance(item, dict)
        ]
        if not gaps:
            continue
        summary = summaries_by_case_id.setdefault(
            draft.case_id,
            {
                "draft_id": draft.draft_id,
                "case_id": draft.case_id,
                "gap_count": 0,
                "gap_categories": [],
                "gap_codes": [],
                "gap_messages": [],
                "notes": [],
            },
        )
        for gap in gaps:
            code, message = project_case_gap(gap)
            summary["gap_categories"].append(gap.category.value)
            if code:
                summary["gap_codes"].append(code)
            if message:
                summary["gap_messages"].append(message)
            summary["notes"].append(format_case_gap_note(gap))
        summary["gap_count"] += len(gaps)
    for deferred_item in scenario_render_result.draft_set.deferred_items:
        summary = summaries_by_case_id.setdefault(
            deferred_item.case_id,
            {
                "draft_id": "",
                "case_id": deferred_item.case_id,
                "gap_count": 0,
                "gap_categories": [],
                "gap_codes": [],
                "gap_messages": [],
                "notes": [],
            },
        )
        for check in deferred_item.unsupported_checks:
            category = _gap_category_from_reason_code(check.reason_code)
            if category is None:
                continue
            summary["gap_count"] += 1
            summary["gap_categories"].append(category)
            summary["gap_codes"].append(check.reason_code)
            if check.message:
                summary["gap_messages"].append(check.message)
            summary["notes"].append(f"Typed gap [{category}]: {check.message}")
    summaries: list[dict[str, Any]] = []
    for summary in summaries_by_case_id.values():
        summaries.append(
            {
                **summary,
                "gap_categories": _dedupe_preserve_order(summary["gap_categories"]),
                "gap_codes": _dedupe_preserve_order(summary["gap_codes"]),
                "gap_messages": _dedupe_preserve_order(summary["gap_messages"]),
                "notes": _dedupe_preserve_order(summary["notes"]),
            }
        )
    return summaries



def _gap_category_from_reason_code(reason_code: str) -> str | None:
    mapping = {
        "endpoint_detail_unresolved": "endpoint_detail",
        "executable_detail_unresolved": "executable_detail",
        "auth_strategy_unresolved": "auth_strategy",
        "environment_unresolved": "environment",
        "assertion_detail_unresolved": "assertion_detail",
        "data_setup_unresolved": "data_setup",
    }
    return mapping.get(str(reason_code))



def _resolve_input_mode(args: argparse.Namespace) -> GenerationInputMode:
    if args.input_mode:
        return GenerationInputMode(args.input_mode)
    if args.authoring_plan_file:
        return GenerationInputMode.AUTHORING_PLAN
    if args.agent_plan_file:
        return GenerationInputMode.AGENT_PLAN
    return GenerationInputMode.PROSE



def _load_agent_plan_file(path: Path) -> AgentTestPlanInput:
    load_result = AgentPlanAuthoringService().load(path)
    if load_result.agent_plan is None:
        raise GenerationCliInputError(
            load_result.diagnostics
        )
    return load_result.agent_plan



def _compile_authoring_plan_file(path: Path):
    bundle_dir = _managed_bundle_dir_for_authoring_path(path)
    if bundle_dir is not None:
        bundle_status, _, bundle_diagnostics = _evaluate_authoring_bundle(bundle_dir)
        if bundle_status != StepStatus.PASS:
            raise GenerationCliInputError(bundle_diagnostics)
    compile_result = AuthoringPlanCompiler().compile_file(path)
    if compile_result.status != StepStatus.PASS or compile_result.compiled_plan is None:
        raise GenerationCliInputError(
            compile_result.diagnostics
        )
    return compile_result

