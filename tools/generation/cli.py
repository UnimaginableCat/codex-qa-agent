"""Agent-facing CLI adapter for test-plan generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.authoring import AgentPlanAuthoringService
from tools.generation.application import GenerateTestPlanOptions, GenerateTestPlanRequest, GenerationInputMode
from tools.generation.application.use_cases import GenerateTestPlanUseCase
from tools.generation.domain.gaps import format_case_gap_note, project_case_gap
from tools.generation.domain.models import (
    AgentTestPlanInput,
    DiagnosticSeverity,
    GenerationDiagnostic,
    GenerationSourceInput,
    PlannedCaseGap,
    SourceInputFormat,
)
from tools.generation.evidence.models import CodeFactsScope, TargetStack
from tools.generation.review import (
    DraftEditTargetType,
    PatchTemplateCatalogService,
    ScenarioDraftPromotionService,
    ScenarioDraftReviewService,
    ScenarioPromotionRequest,
    ScenarioRevalidationRequest,
    ScenarioRevalidationService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.generation.cli",
        description="Generate a NormalizedTestPlan, optionally enriched by explicit scoped code facts.",
    )
    workflow = parser.add_mutually_exclusive_group()
    workflow.add_argument("--init-agent-plan", action="store_true", help="Write an AgentTestPlanInput template JSON file.")
    workflow.add_argument("--validate-agent-plan", action="store_true", help="Validate an AgentTestPlanInput file without generation.")
    workflow.add_argument("--review-drafts", action="store_true", help="Review generated drafts for a run id.")
    workflow.add_argument("--promote-draft", action="store_true", help="Promote one selected draft into scenarios/.")
    workflow.add_argument("--list-patch-templates", action="store_true", help="List deterministic draft edit templates.")
    workflow.add_argument("--show-patch-template", action="store_true", help="Show one draft edit template by target type.")
    workflow.add_argument("--validate-scenario", action="store_true", help="Validate one scenario file without execution.")

    source = parser.add_mutually_exclusive_group()
    source.add_argument("--agent-plan-file", help="Path to a structured agent-authored plan JSON file.")
    source.add_argument("--prose", help="Inline prose source for test-plan generation.")
    source.add_argument("--source-file", help="Path to a prose source file.")
    parser.add_argument(
        "--input-mode",
        choices=[mode.value for mode in GenerationInputMode],
        help="Generation input mode. Defaults to agent_plan for --agent-plan-file, otherwise prose.",
    )
    parser.add_argument("--source-id", help="Stable source id for this generation run.")
    parser.add_argument("--project", help="Project identifier stored in generation contracts.")
    parser.add_argument("--name", default="", help="Optional human-readable source name.")
    parser.add_argument("--goal", default="", help="Optional goal used when scaffolding an agent plan template.")
    parser.add_argument("--output", help="Output path for --init-agent-plan.")
    parser.add_argument("--workspace-root", default=".", help="Workspace root for artifact persistence.")
    parser.add_argument(
        "--output-format",
        choices=["json", "text"],
        default="json",
        help="Output format for review-oriented commands. Defaults to json.",
    )
    parser.add_argument("--no-persist", action="store_true", help="Do not persist generation artifacts.")
    parser.add_argument("--run-id", help="Generation run id for review or promotion.")
    parser.add_argument("--draft-id", help="Draft id selected for promotion.")
    parser.add_argument("--path", help="Scenario markdown path for --validate-scenario.")
    parser.add_argument(
        "--mode",
        choices=["parser", "compile", "preflight"],
        default="parser",
        help="Validation mode for --validate-scenario. Defaults to parser.",
    )
    parser.add_argument(
        "--target-type",
        choices=[target_type.value for target_type in DraftEditTargetType],
        help="Edit target type for --show-patch-template.",
    )
    parser.add_argument("--allow-invalid", action="store_true", help="Allow promotion of parser-invalid drafts.")
    parser.add_argument(
        "--target-dir",
        default="scenarios/generated",
        help="Promotion target directory under scenarios/. The default generated/ root uses a run-scoped subdirectory.",
    )

    parser.add_argument("--project-path", help="Explicit target project path for code facts extraction.")
    parser.add_argument(
        "--evidence-scope-id",
        default="api",
        help="Explicit scope id for code facts extraction.",
    )
    parser.add_argument(
        "--evidence-scope-path",
        action="append",
        default=[],
        help="Explicit scoped file or directory path for code facts extraction. Repeat for multiple paths.",
    )
    parser.add_argument(
        "--evidence-pattern",
        action="append",
        default=[],
        help="File glob used inside scoped directories. Defaults to *.py and *.java.",
    )
    parser.add_argument(
        "--evidence-max-files",
        type=int,
        default=20,
        help="Maximum files to inspect inside explicit evidence scope.",
    )
    parser.add_argument(
        "--stack-hint",
        choices=[stack.value for stack in TargetStack],
        help="Optional explicit stack hint for code facts extraction.",
    )
    parser.add_argument(
        "--collect-code-facts",
        action="store_true",
        help="Collect typed code facts from the explicit evidence scope.",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Apply collected evidence to the NormalizedTestPlan.",
    )
    parser.add_argument(
        "--render-drafts",
        action="store_true",
        help="Render non-executed markdown scenario drafts and parser-validate them.",
    )
    return parser


def build_request(args: argparse.Namespace) -> GenerateTestPlanRequest:
    diagnostics = _adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)

    input_mode = _resolve_input_mode(args)
    agent_plan = _load_agent_plan_file(Path(args.agent_plan_file)) if args.agent_plan_file else None
    if agent_plan is not None:
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
    evidence_scope = None
    if args.collect_code_facts:
        evidence_scope = CodeFactsScope(
            scope_id=args.evidence_scope_id,
            paths=[Path(item) for item in args.evidence_scope_path],
            file_patterns=args.evidence_pattern or ["*.py", "*.java"],
            max_files=args.evidence_max_files,
            stack_hint=None if not args.stack_hint else TargetStack(args.stack_hint),
        )

    return GenerateTestPlanRequest(
        source_input=source_input,
        input_mode=input_mode,
        agent_plan=agent_plan,
        workspace_root=Path(args.workspace_root),
        project_path=Path(args.project_path) if args.project_path else None,
        evidence_scope=evidence_scope,
        options=GenerateTestPlanOptions(
            persist_artifacts=not args.no_persist,
            collect_code_facts=args.collect_code_facts,
            enrichment_enabled=args.enrich,
            render_scenario_drafts=args.render_drafts,
        ),
    )


def run_generation(args: argparse.Namespace) -> dict[str, Any]:
    request = build_request(args)
    result = GenerateTestPlanUseCase().execute(request)
    return summarize_result(result)


def run_init_agent_plan(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _init_agent_plan_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    authoring_service = AgentPlanAuthoringService()
    requested_output_path = Path(args.output)
    try:
        output_path = authoring_service.resolve_template_output_path(requested_output_path)
    except FileExistsError:
        raise GenerationCliInputError(
            [
                GenerationDiagnostic(
                    code="adapter_init_agent_plan_output_exists",
                    message="Agent plan scaffold output already exists. Choose a new file path.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(requested_output_path),
                )
            ]
        ) from None
    template = authoring_service.write_template(
        output_path,
        source_id=args.source_id or "",
        project=args.project or "",
        title=args.name or "",
        goal=args.goal or "",
    )
    payload_diagnostics: list[dict[str, Any]] = []
    message = "Agent-authored plan template scaffolded."
    if output_path != requested_output_path:
        payload_diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_scaffold_output_redirected",
                message="Requested scaffold output already existed, so a managed isolated output directory was used.",
                severity=DiagnosticSeverity.WARNING,
                source_ref=str(output_path),
                details={
                    "requested_output_path": str(requested_output_path),
                    "resolved_output_path": str(output_path),
                },
            ).to_dict()
        )
        message = "Agent-authored plan template scaffolded in an isolated output directory."
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "message": message,
            "output_path": output_path,
            "requested_output_path": requested_output_path,
            "template_version": template.metadata.get("template_version", ""),
            "input_mode": GenerationInputMode.AGENT_PLAN.value,
            "diagnostics": payload_diagnostics,
            "template": template.to_dict(),
        }
    )


def run_validate_agent_plan(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _validate_agent_plan_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    result = AgentPlanAuthoringService().validate_file(Path(args.agent_plan_file))
    return to_json_safe(
        {
            "status": result.status.value,
            "message": result.message,
            "file_path": result.file_path,
            "input_mode": GenerationInputMode.AGENT_PLAN.value,
            "case_count": result.case_count,
            "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
            "agent_plan": None if result.agent_plan is None else result.agent_plan.to_dict(),
        }
    )


def summarize_result(result: Any) -> dict[str, Any]:
    evidence_bundle = result.evidence_bundle
    enrichment_result = result.enrichment_result
    scenario_render_result = result.scenario_render_result
    unresolved_intents = _scenario_unresolved_intents(scenario_render_result)
    return to_json_safe(
        {
            "status": result.final_status.value,
            "message": result.message,
            "run_id": result.run_context.run_id,
            "source_id": result.run_context.source_id,
            "project": result.run_context.project,
            "input_mode": result.details.get("input_mode", "prose"),
            "test_case_count": len(result.normalized_plan.test_cases),
            "code_facts": result.details.get("code_facts", "not_requested"),
            "evidence_fact_count": len(evidence_bundle.facts) if evidence_bundle else 0,
            "enrichment": result.details.get("enrichment", "not_requested"),
            "applied_evidence_count": (
                len(enrichment_result.applied_evidence) if enrichment_result else 0
            ),
            "unapplied_evidence_count": (
                len(enrichment_result.unapplied_evidence) if enrichment_result else 0
            ),
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
            "evidence_diagnostics": (
                [diagnostic.to_dict() for diagnostic in evidence_bundle.diagnostics]
                if evidence_bundle
                else []
            ),
            "unapplied_evidence": (
                [reason.to_dict() for reason in enrichment_result.unapplied_evidence]
                if enrichment_result
                else []
            ),
            "artifact_paths": result.artifact_paths,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.init_agent_plan:
            payload = run_init_agent_plan(args)
        elif args.validate_agent_plan:
            payload = run_validate_agent_plan(args)
        elif args.review_drafts:
            payload = run_review(args)
        elif args.promote_draft:
            payload = run_promotion(args)
        elif args.list_patch_templates:
            payload = run_list_patch_templates(args)
        elif args.show_patch_template:
            payload = run_show_patch_template(args)
        elif args.validate_scenario:
            payload = run_validate_scenario(args)
        else:
            payload = run_generation(args)
    except GenerationCliInputError as exc:
        payload = _error_payload(exc.diagnostics)
        _print_payload(payload, output_format=args.output_format, workflow="error")
        return 1
    except Exception as exc:  # noqa: BLE001
        payload = _error_payload(
            [
                GenerationDiagnostic(
                    code="generation_adapter_error",
                    message=f"Generation adapter failed: {exc}",
                    severity=DiagnosticSeverity.ERROR,
                )
            ]
        )
        _print_payload(payload, output_format=args.output_format, workflow="error")
        return 1

    workflow = (
        "authoring"
        if args.init_agent_plan or args.validate_agent_plan
        else "review"
        if args.review_drafts
        else "promotion"
        if args.promote_draft
        else "template"
        if args.list_patch_templates or args.show_patch_template
        else "revalidation"
        if args.validate_scenario
        else "generation"
    )
    _print_payload(payload, output_format=args.output_format, workflow=workflow)
    return 0 if payload["status"] == StepStatus.PASS.value else 1


def _scenario_unresolved_intents(scenario_render_result: Any) -> list[dict[str, Any]]:
    if scenario_render_result is None:
        return []
    summaries: list[dict[str, Any]] = []
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
        categories: list[str] = []
        codes: list[str] = []
        messages: list[str] = []
        notes: list[str] = []
        for gap in gaps:
            code, message = project_case_gap(gap)
            categories.append(gap.category.value)
            if code:
                codes.append(code)
            if message:
                messages.append(message)
            notes.append(format_case_gap_note(gap))
        summaries.append(
            {
                "draft_id": draft.draft_id,
                "case_id": draft.case_id,
                "gap_count": len(gaps),
                "gap_categories": _dedupe_preserve_order(categories),
                "gap_codes": _dedupe_preserve_order(codes),
                "gap_messages": _dedupe_preserve_order(messages),
                "notes": notes,
            }
        )
    return summaries


def run_review(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _review_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    review_set = ScenarioDraftReviewService().review(
        str(args.run_id),
        workspace_root=Path(args.workspace_root),
    )
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "run_id": review_set.run_id,
            "source_id": review_set.source_id,
            "artifact_dir": review_set.artifact_dir,
            "draft_count": len(review_set.items),
            "valid_draft_count": sum(1 for item in review_set.items if item.parse_status.value == "valid"),
            "invalid_draft_count": sum(1 for item in review_set.items if item.parse_status.value == "invalid"),
            "partial_draft_count": sum(
                1
                for item in review_set.items
                if item.readiness_category.value == "parser_valid_partial"
            ),
            "strongly_supported_draft_count": sum(
                1
                for item in review_set.items
                if item.readiness_category.value == "parser_valid_strongly_supported"
            ),
            "deferred_item_count": len(review_set.deferred_items),
            "drafts_with_edit_targets": sum(1 for item in review_set.items if item.edit_target_count > 0),
            "total_edit_targets": sum(item.edit_target_count for item in review_set.items),
            "average_completeness_ratio": _average_completeness_ratio(review_set),
            "close_to_runnable_count": _close_to_runnable_count(review_set),
            "review_set": review_set.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in review_set.diagnostics],
        }
    )


def run_promotion(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _promotion_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    result = ScenarioDraftPromotionService().promote(
        ScenarioPromotionRequest(
            run_id=str(args.run_id),
            draft_id=str(args.draft_id),
            workspace_root=Path(args.workspace_root),
            target_dir=Path(args.target_dir),
            allow_invalid=args.allow_invalid,
        )
    )
    return to_json_safe(
        {
            "status": result.status.value,
            "run_id": result.run_id,
            "draft_id": result.draft_id,
            "source_path": result.source_path,
            "target_path": result.target_path,
            "promotion_result_path": result.promotion_result_path,
            "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
        }
    )


def run_list_patch_templates(args: argparse.Namespace) -> dict[str, Any]:
    catalog = PatchTemplateCatalogService().list_templates()
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "catalog_version": catalog.catalog_version,
            "template_count": len(catalog.templates),
            "templates": [template.to_dict() for template in catalog.templates],
        }
    )


def run_show_patch_template(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _patch_template_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    target_type = DraftEditTargetType(str(args.target_type))
    template = PatchTemplateCatalogService().get_template(target_type)
    if template is None:
        raise GenerationCliInputError(
            [
                GenerationDiagnostic(
                    code="adapter_patch_template_missing",
                    message=f"No patch template exists for target type {target_type.value}.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=target_type.value,
                )
            ]
        )
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "template": template.to_dict(),
        }
    )


def run_validate_scenario(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _revalidation_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    result = ScenarioRevalidationService().validate(
        ScenarioRevalidationRequest(
            file_path=Path(args.path),
            validation_mode=args.mode,
            workspace_root=Path(args.workspace_root),
        )
    )
    compile_validation = result.compile_validation
    preflight_validation = result.preflight_validation
    readiness_category = (
        result.environment_readiness_category.value
        if result.environment_readiness_category is not None
        else result.execution_readiness_category.value
    )
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "file_path": result.file_path,
            "parse_status": result.parse_status.value,
            "validation_mode": result.validation_mode,
            "diagnostics": result.diagnostics,
            "checklist": result.checklist.to_dict(),
            "gap_summary": result.gap_summary.to_dict(),
            "edit_targets": result.edit_targets.to_dict(),
            "edit_target_count": len(result.edit_targets.targets),
            "promotion_advisory": result.promotion_advisory.value,
            "completeness_ratio": result.completeness_ratio,
            "compile_status": None if compile_validation is None else compile_validation.compile_status.value,
            "preflight_status": None if preflight_validation is None else preflight_validation.preflight_status.value,
            "execution_readiness_category": result.execution_readiness_category.value,
            "environment_readiness_category": (
                None
                if result.environment_readiness_category is None
                else result.environment_readiness_category.value
            ),
            "readiness_category": readiness_category,
            "compile_validation": None if compile_validation is None else compile_validation.to_dict(),
            "preflight_validation": None if preflight_validation is None else preflight_validation.to_dict(),
            "based_on_generated_draft": result.based_on_generated_draft,
            "generation_run_id": result.generation_run_id,
            "draft_id": result.draft_id,
        }
    )


class GenerationCliInputError(ValueError):
    def __init__(self, diagnostics: list[GenerationDiagnostic]) -> None:
        super().__init__("Invalid generation CLI input.")
        self.diagnostics = diagnostics


def _resolve_input_mode(args: argparse.Namespace) -> GenerationInputMode:
    if args.input_mode:
        return GenerationInputMode(args.input_mode)
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


def _adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.agent_plan_file and not args.prose and not args.source_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_source",
                message="Generation requires exactly one of --agent-plan-file, --prose, or --source-file.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.input_mode == GenerationInputMode.AGENT_PLAN.value and not args.agent_plan_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_agent_plan_mode_requires_file",
                message="input_mode=agent_plan requires --agent-plan-file.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.input_mode == GenerationInputMode.PROSE.value and args.agent_plan_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_prose_mode_rejects_agent_plan_file",
                message="input_mode=prose requires --prose or --source-file, not --agent-plan-file.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.agent_plan_file and not Path(args.agent_plan_file).exists():
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_agent_plan_file_missing",
                message="Agent-authored plan file does not exist.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.agent_plan_file,
            )
        )
    if not args.agent_plan_file and not args.source_id:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_source_id",
                message="Prose generation requires --source-id.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    if not args.agent_plan_file and not args.project:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_project",
                message="Prose generation requires --project.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.enrich and not args.collect_code_facts:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_enrichment_requires_code_facts",
                message="--enrich requires --collect-code-facts and an explicit evidence scope.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.collect_code_facts and not args.project_path:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_code_facts_require_project_path",
                message="Code facts collection requires explicit --project-path.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.collect_code_facts and not args.evidence_scope_path:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_code_facts_require_explicit_scope",
                message="Code facts collection requires at least one --evidence-scope-path.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.evidence_max_files < 1:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_invalid_evidence_max_files",
                message="--evidence-max-files must be at least 1.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.render_drafts and args.no_persist:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_render_drafts_requires_persistence",
                message="--render-drafts requires artifact persistence; remove --no-persist.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    return diagnostics


def _review_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.run_id:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_review_requires_run_id",
            message="--review-drafts requires --run-id.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]


def _init_agent_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.output:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_agent_plan_requires_output",
                message="--init-agent-plan requires --output.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    return diagnostics


def _validate_agent_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.agent_plan_file:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_validate_agent_plan_requires_file",
            message="--validate-agent-plan requires --agent-plan-file.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]


def _promotion_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.run_id:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_promotion_requires_run_id",
                message="--promote-draft requires --run-id.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    if not args.draft_id:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_promotion_requires_draft_id",
                message="--promote-draft requires --draft-id.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.run_id,
            )
        )
    return diagnostics


def _patch_template_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.target_type:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_patch_template_requires_target_type",
            message="--show-patch-template requires --target-type.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]


def _revalidation_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.path:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_revalidation_requires_path",
            message="--validate-scenario requires --path.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]


def _error_payload(diagnostics: list[GenerationDiagnostic]) -> dict[str, Any]:
    return to_json_safe(
        {
            "status": StepStatus.ERROR.value,
            "message": "Generation adapter input was invalid.",
            "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
            "artifact_paths": {},
        }
    )


def _print_payload(payload: dict[str, Any], *, output_format: str = "json", workflow: str = "generation") -> None:
    if output_format == "text" and workflow == "authoring":
        print(_render_authoring_text(payload))
        return
    if output_format == "text" and workflow == "review":
        print(_render_review_text(payload))
        return
    if output_format == "text" and workflow == "template":
        print(_render_template_text(payload))
        return
    if output_format == "text" and workflow == "revalidation":
        print(_render_revalidation_text(payload))
        return
    print(json.dumps(payload, ensure_ascii=False))


def _render_authoring_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Message: {payload.get('message', '')}",
    ]
    if payload.get("output_path"):
        lines.extend(
            [
                f"Output: {payload['output_path']}",
                f"Template version: {payload.get('template_version', '')}",
                f"Input mode: {payload.get('input_mode', '')}",
            ]
        )
    if payload.get("file_path"):
        lines.extend(
            [
                f"File: {payload['file_path']}",
                f"Input mode: {payload.get('input_mode', '')}",
                f"Case count: {payload.get('case_count', 0)}",
            ]
        )
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("Diagnostics:")
        for diagnostic in diagnostics:
            lines.append(f"  - {diagnostic.get('code', '')}: {diagnostic.get('message', '')}")
    template = payload.get("template") or {}
    if template:
        lines.append("Template preview:")
        for preview_line in json.dumps(template, ensure_ascii=False, indent=2).splitlines()[:12]:
            lines.append(f"  {preview_line}")
    return "\n".join(lines).rstrip()


def _render_review_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Run ID: {payload['run_id']}",
        f"Source ID: {payload['source_id']}",
        f"Drafts: {payload['draft_count']}",
        f"Partial drafts: {payload.get('partial_draft_count', 0)}",
        f"Strongly supported drafts: {payload.get('strongly_supported_draft_count', 0)}",
        f"Deferred items: {payload.get('deferred_item_count', 0)}",
        f"Drafts with edit targets: {payload.get('drafts_with_edit_targets', 0)}",
        f"Total edit targets: {payload.get('total_edit_targets', 0)}",
        f"Average completeness: {payload.get('average_completeness_ratio', 0.0)}",
        f"Close to runnable: {payload.get('close_to_runnable_count', 0)}",
        "",
    ]
    review_set = payload.get("review_set") or {}
    for item in review_set.get("items", []):
        lines.extend(
            [
                f"Draft: {item['draft_id']}",
                f"Title: {item.get('title', '')}",
                f"Status: {item['readiness_category']}",
                f"Parse: {item['parse_status']}",
                f"Route: {item.get('route_status', 'unknown')}",
                f"Promotion advisory: {item.get('promotion_advisory', '')}",
                "Checklist:",
            ]
        )
        checklist = item.get("checklist") or {}
        for line in checklist.get("diff_lines", []):
            lines.append(f"  {line}")
        lines.append("Remaining gaps:")
        gap_summary = item.get("gap_summary") or {}
        for code in gap_summary.get("gap_codes", []):
            lines.append(f"  - {code}")
        lines.append("Edit targets:")
        edit_targets = (item.get("edit_targets") or {}).get("targets", [])
        if edit_targets:
            for target in edit_targets:
                lines.append(
                    f"  - [{target['section_name']}] {target['target_type']}: {target['suggested_minimum_patch']}"
                )
                suggestion = target.get("patch_suggestion") or {}
                template_id = suggestion.get("template_id")
                if template_id:
                    lines.append(f"    Template: {template_id}")
                    preview = suggestion.get("template_preview") or []
                    if preview:
                        lines.append("    Preview:")
                        for preview_line in preview[:6]:
                            lines.append(f"      {preview_line}")
        else:
            lines.append("  - none")
        lines.append("")

    deferred_items = review_set.get("deferred_items") or []
    if deferred_items:
        lines.append("Deferred:")
        for item in deferred_items:
            lines.append(f"  {item['case_id']}: {item['reason_code']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_template_text(payload: dict[str, Any]) -> str:
    if "template" in payload:
        template = payload["template"]
        lines = [
            f"Status: {payload['status']}",
            f"Template: {template['template_id']}",
            f"Target type: {template['target_type']}",
            f"Section: {template['section_name']}",
            f"Title: {template['title']}",
            f"Description: {template['description']}",
            "Preview:",
        ]
        lines.extend(f"  {line}" for line in template.get("template_lines", []))
        usage_notes = template.get("usage_notes", [])
        if usage_notes:
            lines.append("Usage notes:")
            lines.extend(f"  - {line}" for line in usage_notes)
        return "\n".join(lines)

    lines = [
        f"Status: {payload['status']}",
        f"Catalog version: {payload.get('catalog_version', '')}",
        f"Templates: {payload.get('template_count', 0)}",
        "",
    ]
    for template in payload.get("templates", []):
        lines.append(
            f"- {template['template_id']} [{template['section_name']}] {template['target_type']}: {template['title']}"
        )
    return "\n".join(lines).rstrip()


def _render_revalidation_text(payload: dict[str, Any]) -> str:
    display_status = payload.get("readiness_category") or payload["status"]
    lines = [
        f"Status: {display_status}",
        f"File: {payload['file_path']}",
        f"Parse: {payload['parse_status']}",
        f"Validation mode: {payload.get('validation_mode', 'parser')}",
        f"Compile: {payload.get('compile_status') or 'not_requested'}",
        f"Preflight: {payload.get('preflight_status') or 'not_requested'}",
        f"Readiness: {payload.get('readiness_category', payload.get('execution_readiness_category', ''))}",
        f"Promotion advisory: {payload.get('promotion_advisory', '')}",
        f"Completeness: {payload.get('completeness_ratio', 0.0)}",
    ]
    if payload.get("based_on_generated_draft"):
        lines.extend(
            [
                "Origin: generated draft",
                f"Generation run: {payload.get('generation_run_id', '')}",
                f"Draft ID: {payload.get('draft_id', '')}",
            ]
        )
    lines.append("Checklist:")
    checklist = payload.get("checklist") or {}
    for line in checklist.get("diff_lines", []):
        lines.append(f"  {line}")
    lines.append("Remaining gaps:")
    gap_summary = payload.get("gap_summary") or {}
    gap_codes = gap_summary.get("gap_codes", [])
    if gap_codes:
        for code in gap_codes:
            lines.append(f"  - {code}")
    else:
        lines.append("  - none")
    compile_validation = payload.get("compile_validation") or {}
    compile_issues = compile_validation.get("issues") or []
    compile_warnings = compile_validation.get("warnings") or []
    if compile_issues or compile_warnings:
        lines.append("Compile issues:")
        for issue in compile_issues:
            lines.append(f"  - {issue.get('issue_type', '')}: {issue.get('message', '')}")
        for warning in compile_warnings:
            lines.append(f"  - warning/{warning.get('issue_type', '')}: {warning.get('message', '')}")
    preflight_validation = payload.get("preflight_validation") or {}
    preflight_issues = preflight_validation.get("issues") or []
    preflight_warnings = preflight_validation.get("warnings") or []
    if preflight_issues or preflight_warnings:
        lines.append("Preflight issues:")
        for issue in preflight_issues:
            lines.append(f"  - {issue.get('issue_type', '')}: {issue.get('message', '')}")
        for warning in preflight_warnings:
            lines.append(f"  - warning/{warning.get('issue_type', '')}: {warning.get('message', '')}")
    lines.append("Edit targets:")
    edit_targets = (payload.get("edit_targets") or {}).get("targets", [])
    if edit_targets:
        for target in edit_targets:
            lines.append(
                f"  - [{target['section_name']}] {target['target_type']}: {target['suggested_minimum_patch']}"
            )
            suggestion = target.get("patch_suggestion") or {}
            if suggestion.get("template_id"):
                lines.append(f"    Template: {suggestion['template_id']}")
    else:
        lines.append("  - none")
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("Parser diagnostics:")
        for diagnostic in diagnostics:
            lines.append(f"  - {diagnostic.get('severity', '')}: {diagnostic.get('message', '')}")
    return "\n".join(lines).rstrip()


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _average_completeness_ratio(review_set: Any) -> float:
    if not review_set.items:
        return 0.0
    total = sum(item.checklist.completeness_ratio for item in review_set.items)
    return round(total / len(review_set.items), 3)


def _close_to_runnable_count(review_set: Any) -> int:
    return sum(
        1
        for item in review_set.items
        if item.parse_status.value == "valid"
        and item.checklist.completeness_ratio >= 0.6
        and item.route_status.startswith("resolved")
    )


if __name__ == "__main__":
    raise SystemExit(main())
