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
from tools.generation.authoring_contract import AuthoringPlanCompiler, AuthoringPlanTemplateService
from tools.generation.persistence.artifacts import (
    AUTHORING_PLAN_FILENAME,
    CONTEXT_FILENAME,
    ENTITY_INVENTORY_FILENAME,
    OPERATION_INVENTORY_FILENAME,
    load_generation_run_context_from_bundle_dir,
)
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
from tools.generation.review import (
    DraftEditTargetType,
    PatchTemplateCatalogService,
    ScenarioDraftBatchPromotionService,
    ScenarioDraftPromotionService,
    ScenarioDraftReviewService,
    ScenarioDirectoryRevalidationRequest,
    ScenarioDirectoryRevalidationService,
    ScenarioPromotionBatchRequest,
    ScenarioPromotionRequest,
    ScenarioPreflightStatus,
    ScenarioRevalidationRequest,
    ScenarioRevalidationService,
)
from tools.generation.orchestration.context import initialize_generation_run_context
from tools.generation.persistence import (
    FileGenerationArtifactStore,
    managed_generation_artifacts_root_for_path,
)

LEGACY_AGENT_PLAN_ROOT = ("artifacts", "agent", "input")
MANAGED_AGENT_PLAN_ROOT = ("artifacts", "agent", "generation")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.generation.cli",
        description="Compile authoring DSL into a NormalizedTestPlan and optionally render markdown draft scenarios.",
    )
    workflow = parser.add_mutually_exclusive_group()
    workflow.add_argument(
        "--init-authoring-plan",
        action="store_true",
        help="Write a scaffolded authoring-plan YAML file into a managed generation bundle.",
    )
    workflow.add_argument(
        "--init-entity-inventory",
        action="store_true",
        help="Write a scaffolded entity-inventory YAML file into a managed generation bundle.",
    )
    workflow.add_argument(
        "--init-operation-inventory",
        action="store_true",
        help="Write a scaffolded operation-inventory YAML file into a managed generation bundle.",
    )
    workflow.add_argument(
        "--init-agent-plan",
        action="store_true",
        help="Write a low-level AgentTestPlanInput template JSON file. Prefer authoring-plan YAML for the normal DSL flow.",
    )
    workflow.add_argument(
        "--validate-agent-plan",
        action="store_true",
        help="Validate a compiled AgentTestPlanInput file without generation.",
    )
    workflow.add_argument(
        "--validate-authoring-plan",
        action="store_true",
        help="Validate a compact authoring-plan file without compile or generation.",
    )
    workflow.add_argument(
        "--validate-authoring-bundle",
        action="store_true",
        help="Validate entity inventory, operation inventory, and authoring plan together for one managed bundle.",
    )
    workflow.add_argument(
        "--validate-entity-inventory",
        action="store_true",
        help="Validate an entity-inventory YAML file without compile or generation.",
    )
    workflow.add_argument(
        "--validate-operation-inventory",
        action="store_true",
        help="Validate an operation-inventory YAML file without compile or generation.",
    )
    workflow.add_argument(
        "--compile-authoring-plan",
        action="store_true",
        help="Compile a compact authoring-plan file into a managed AgentTestPlanInput bundle.",
    )
    workflow.add_argument("--review-drafts", action="store_true", help="Review generated drafts for a run id.")
    workflow.add_argument("--promote-draft", action="store_true", help="Promote one selected draft into scenarios/.")
    workflow.add_argument("--promote-all-drafts", action="store_true", help="Promote all drafts from one run into scenarios/.")
    workflow.add_argument("--list-patch-templates", action="store_true", help="List deterministic draft edit templates.")
    workflow.add_argument("--show-patch-template", action="store_true", help="Show one draft edit template by target type.")
    workflow.add_argument("--validate-scenario", action="store_true", help="Validate one scenario file without execution.")
    workflow.add_argument("--validate-scenario-dir", action="store_true", help="Validate all scenario markdown files in one directory.")

    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--agent-plan-file",
        help="Path to a compiled AgentTestPlanInput JSON file. Prefer --authoring-plan-file for the normal DSL flow.",
    )
    source.add_argument(
        "--authoring-plan-file",
        help="Path to a compact authoring-plan YAML file. This is the preferred DSL input.",
    )
    source.add_argument("--prose", help="Inline prose source for fallback/bootstrap test-plan generation.")
    source.add_argument("--source-file", help="Path to a prose source file.")
    parser.add_argument("--entity-inventory-file", help="Path to an entity-inventory YAML file.")
    parser.add_argument("--operation-inventory-file", help="Path to an operation-inventory YAML file.")
    parser.add_argument(
        "--input-mode",
        choices=[mode.value for mode in GenerationInputMode],
        help="Generation input mode. Defaults to authoring_plan, agent_plan, or prose based on the selected source flag.",
    )
    parser.add_argument("--source-id", help="Stable source id for this generation run.")
    parser.add_argument("--project", help="Project identifier stored in generation contracts.")
    parser.add_argument("--surface", default="", help="Optional surface/controller name used for staged authoring inventories.")
    parser.add_argument("--name", default="", help="Optional human-readable source name.")
    parser.add_argument("--goal", default="", help="Optional goal used when scaffolding a low-level agent plan template.")
    parser.add_argument(
        "--output",
        help="Managed generation root hint for --init-authoring-plan, --init-agent-plan, or --compile-authoring-plan. The CLI writes bundles under artifacts/agent/generation.",
    )
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
    parser.add_argument("--path", help="Scenario markdown file or directory path for validation commands.")
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
        "--purge-target-dir",
        action="store_true",
        help="Delete the resolved promotion target directory before promotion. Use for rerender/re-promote cycles.",
    )
    parser.add_argument(
        "--target-dir",
        default="scenarios/generated",
        help="Promotion target directory under scenarios/. The default generated/ root uses a run-scoped subdirectory.",
    )

    parser.add_argument(
        "--render-drafts",
        action="store_true",
        help="Render non-executed markdown scenario drafts from the generated plan and parser-validate them.",
    )
    return parser


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


def run_init_authoring_plan(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _init_authoring_plan_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    template_service = AuthoringPlanTemplateService()
    template = template_service.build_template(
        source_id=args.source_id or "",
        project=args.project or "",
        title=args.name or "",
        goal=args.goal or "",
    )
    requested_output_path = Path(args.output)
    run_context = _resolve_scaffold_run_context(
        requested_output_path=requested_output_path,
        source_input=_scaffold_source_input(
            source_id=template.source_id,
            project=template.project,
            name=template.title,
            content=template.to_dict(),
            source_path=AUTHORING_PLAN_FILENAME,
            input_mode=GenerationInputMode.AUTHORING_PLAN.value,
        ),
    )
    artifact_store = FileGenerationArtifactStore()
    artifact_store.write_context(run_context)
    output_path = artifact_store.write_authoring_plan(run_context, template)
    entity_inventory_path = artifact_store.write_yaml_document(run_context, ENTITY_INVENTORY_FILENAME, template_service.build_entity_inventory_template(
        source_id=template.source_id,
        project=template.project,
        surface=args.surface or template.scope.surface,
    ))
    operation_inventory_path = artifact_store.write_yaml_document(run_context, OPERATION_INVENTORY_FILENAME, template_service.build_operation_inventory_template(
        source_id=template.source_id,
        project=template.project,
        surface=args.surface or template.scope.surface,
    ))
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "message": "Authoring-plan bundle scaffolded.",
            "bundle_dir": run_context.artifact_dir,
            "output_path": output_path,
            "entity_inventory_path": entity_inventory_path,
            "operation_inventory_path": operation_inventory_path,
            "requested_output_path": requested_output_path,
            "template_version": template.metadata.get("template_version", ""),
            "input_mode": GenerationInputMode.AUTHORING_PLAN.value,
            "diagnostics": [],
            "authoring_plan": template.to_dict(),
            "entity_inventory": template_service.build_entity_inventory_template(
                source_id=template.source_id,
                project=template.project,
                surface=args.surface or template.scope.surface,
            ),
            "operation_inventory": template_service.build_operation_inventory_template(
                source_id=template.source_id,
                project=template.project,
                surface=args.surface or template.scope.surface,
            ),
        }
    )


def run_init_agent_plan(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _init_agent_plan_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    authoring_service = AgentPlanAuthoringService()
    requested_output_path = Path(args.output)
    artifacts_root_dir = managed_generation_artifacts_root_for_path(requested_output_path)
    if artifacts_root_dir is None:
        raise GenerationCliInputError(
            [
                GenerationDiagnostic(
                    code="adapter_init_agent_plan_requires_managed_root",
                    message="Agent plan scaffold must be written under artifacts/agent/generation.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(requested_output_path),
                )
            ]
        )
    workspace_root = artifacts_root_dir.parent.parent.parent
    template = authoring_service.build_template(
        source_id=args.source_id or "",
        project=args.project or "",
        title=args.name or "",
        goal=args.goal or "",
    )
    source_input = GenerationSourceInput(
        source_id=template.source_id,
        project=template.project,
        input_format=SourceInputFormat.STRUCTURED,
        name=template.title,
        content=json.dumps(template.to_dict(), ensure_ascii=False),
    )
    run_context = initialize_generation_run_context(source_input, workspace_root=workspace_root)
    artifact_store = FileGenerationArtifactStore()
    artifact_store.write_context(run_context)
    output_path = artifact_store.write_agent_plan(run_context, template)
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "message": "Agent-authored plan bundle scaffolded.",
            "bundle_dir": run_context.artifact_dir,
            "output_path": output_path,
            "requested_output_path": requested_output_path,
            "template_version": template.metadata.get("template_version", ""),
            "input_mode": GenerationInputMode.AGENT_PLAN.value,
            "diagnostics": [],
            "template": template.to_dict(),
        }
    )


def run_init_entity_inventory(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _init_entity_inventory_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    template_service = AuthoringPlanTemplateService()
    inventory = template_service.build_entity_inventory_template(
        source_id=args.source_id or "",
        project=args.project or "",
        surface=args.surface or "",
    )
    requested_output_path = Path(args.output)
    run_context = _resolve_scaffold_run_context(
        requested_output_path=requested_output_path,
        source_input=_scaffold_source_input(
            source_id=str(inventory["source_id"]),
            project=str(inventory["project"]),
            name=str(inventory["surface"]),
            content=inventory,
            source_path=ENTITY_INVENTORY_FILENAME,
            input_mode="entity_inventory",
        ),
    )
    artifact_store = FileGenerationArtifactStore()
    artifact_store.write_context(run_context)
    output_path = artifact_store.write_yaml_document(run_context, ENTITY_INVENTORY_FILENAME, inventory)
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "message": "Entity inventory scaffolded.",
            "bundle_dir": run_context.artifact_dir,
            "output_path": output_path,
            "requested_output_path": requested_output_path,
            "diagnostics": [],
            "entity_inventory": inventory,
        }
    )


def run_init_operation_inventory(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _init_operation_inventory_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    template_service = AuthoringPlanTemplateService()
    inventory = template_service.build_operation_inventory_template(
        source_id=args.source_id or "",
        project=args.project or "",
        surface=args.surface or "",
    )
    requested_output_path = Path(args.output)
    run_context = _resolve_scaffold_run_context(
        requested_output_path=requested_output_path,
        source_input=_scaffold_source_input(
            source_id=str(inventory["source_id"]),
            project=str(inventory["project"]),
            name=str(inventory["surface"]),
            content=inventory,
            source_path=OPERATION_INVENTORY_FILENAME,
            input_mode="operation_inventory",
        ),
    )
    artifact_store = FileGenerationArtifactStore()
    artifact_store.write_context(run_context)
    output_path = artifact_store.write_yaml_document(run_context, OPERATION_INVENTORY_FILENAME, inventory)
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "message": "Operation inventory scaffolded.",
            "bundle_dir": run_context.artifact_dir,
            "output_path": output_path,
            "requested_output_path": requested_output_path,
            "diagnostics": [],
            "operation_inventory": inventory,
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


def run_validate_entity_inventory(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _validate_entity_inventory_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    file_path = Path(args.entity_inventory_file)
    payload, validation_diagnostics = _validate_entity_inventory_file(file_path)
    status = StepStatus.PASS if not validation_diagnostics else StepStatus.BLOCKED
    return to_json_safe(
        {
            "status": status.value,
            "message": (
                "Entity inventory is structurally valid."
                if status == StepStatus.PASS
                else "Entity inventory is blocked by missing or inconsistent staged contract details."
            ),
            "file_path": file_path,
            "diagnostics": [diagnostic.to_dict() for diagnostic in validation_diagnostics],
            "entity_inventory": payload,
        }
    )


def run_validate_operation_inventory(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _validate_operation_inventory_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    file_path = Path(args.operation_inventory_file)
    payload, validation_diagnostics = _validate_operation_inventory_file(file_path)
    status = StepStatus.PASS if not validation_diagnostics else StepStatus.BLOCKED
    return to_json_safe(
        {
            "status": status.value,
            "message": (
                "Operation inventory is structurally valid."
                if status == StepStatus.PASS
                else "Operation inventory is blocked by missing or inconsistent staged contract details."
            ),
            "file_path": file_path,
            "diagnostics": [diagnostic.to_dict() for diagnostic in validation_diagnostics],
            "operation_inventory": payload,
        }
    )


def run_validate_authoring_bundle(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _validate_authoring_bundle_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    bundle_dir = _resolve_bundle_dir(Path(args.path))
    overall_status, stage_results, _ = _evaluate_authoring_bundle(bundle_dir)
    authoring_plan_path = bundle_dir / AUTHORING_PLAN_FILENAME
    return to_json_safe(
        {
            "status": overall_status.value,
            "message": (
                "Authoring bundle is structurally valid across entity inventory, operation inventory, and authoring plan. "
                "No runnable scenario drafts were rendered or promoted by this authoring validation step."
                if overall_status == StepStatus.PASS
                else "Authoring bundle is blocked by staged authoring validation diagnostics."
            ),
            "bundle_dir": str(bundle_dir),
            "stage_order": ["entity_inventory", "operation_inventory", "authoring_plan"],
            "stage_results": stage_results,
            "handoff": {
                "scope": "authoring_only",
                "scenario_drafts_rendered": False,
                "promoted_scenarios": False,
                "next_commands": [
                    {
                        "label": "compile_authoring_plan",
                        "command": (
                            f"python -m tools.generation.cli --compile-authoring-plan "
                            f"--authoring-plan-file {authoring_plan_path} --output {MANAGED_AGENT_PLAN_ROOT}"
                        ),
                    },
                    {
                        "label": "render_drafts",
                        "command": (
                            f"python -m tools.generation.cli --authoring-plan-file {authoring_plan_path} "
                            f"--workspace-root . --render-drafts"
                        ),
                    },
                ],
            },
        }
    )


def run_validate_authoring_plan(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _validate_authoring_plan_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    result = AuthoringPlanCompiler().validate_file(Path(args.authoring_plan_file))
    return to_json_safe(
        {
            "status": result.status.value,
            "message": result.message,
            "file_path": result.file_path,
            "input_mode": GenerationInputMode.AUTHORING_PLAN.value,
            "case_count": result.case_count,
            "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
            "authoring_plan": None if result.authoring_plan is None else result.authoring_plan.to_dict(),
            "agent_plan": None if result.compiled_plan is None else result.compiled_plan.to_dict(),
        }
    )


def run_compile_authoring_plan(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _compile_authoring_plan_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    authoring_plan_path = Path(args.authoring_plan_file)
    bundle_dir = _managed_bundle_dir_for_authoring_path(authoring_plan_path)
    if bundle_dir is not None:
        bundle_status, stage_results, bundle_diagnostics = _evaluate_authoring_bundle(bundle_dir)
        if bundle_status != StepStatus.PASS:
            return to_json_safe(
                {
                    "status": bundle_status.value,
                    "message": "Managed authoring bundle is blocked by staged validation diagnostics.",
                    "file_path": str(authoring_plan_path),
                    "input_mode": GenerationInputMode.AUTHORING_PLAN.value,
                    "diagnostics": [diagnostic.to_dict() for diagnostic in bundle_diagnostics],
                    "stage_results": stage_results,
                }
            )
    result = AuthoringPlanCompiler().compile_file(authoring_plan_path)
    payload: dict[str, Any] = {
        "status": result.status.value,
        "message": result.message,
        "file_path": result.file_path,
        "input_mode": GenerationInputMode.AUTHORING_PLAN.value,
        "case_count": result.case_count,
        "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
        "authoring_plan": None if result.authoring_plan is None else result.authoring_plan.to_dict(),
        "agent_plan": None if result.compiled_plan is None else result.compiled_plan.to_dict(),
    }
    if result.status != StepStatus.PASS or result.compiled_plan is None or result.authoring_plan is None:
        return to_json_safe(payload)

    requested_output_path = Path(args.output)
    artifacts_root_dir = managed_generation_artifacts_root_for_path(requested_output_path)
    if artifacts_root_dir is None:
        raise GenerationCliInputError(
            [
                GenerationDiagnostic(
                    code="adapter_compile_authoring_plan_requires_managed_root",
                    message="Compiled authoring-plan bundle must be written under artifacts/agent/generation.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(requested_output_path),
                )
            ]
        )
    workspace_root = artifacts_root_dir.parent.parent.parent
    artifact_store = FileGenerationArtifactStore()
    source_input = GenerationSourceInput(
        source_id=result.authoring_plan.source_id,
        project=result.authoring_plan.project,
        input_format=SourceInputFormat.STRUCTURED,
        name=result.authoring_plan.title,
        content=json.dumps(result.authoring_plan.to_dict(), ensure_ascii=False),
        source_path=Path(args.authoring_plan_file),
        metadata={"input_mode": GenerationInputMode.AUTHORING_PLAN.value},
    )
    run_context = initialize_generation_run_context(source_input, workspace_root=workspace_root)
    artifact_store.write_context(run_context)
    artifact_store.write_source_input(run_context, source_input)
    artifact_store.write_diagnostics(run_context, result.diagnostics)
    output_path = artifact_store.write_agent_plan(run_context, result.compiled_plan)
    payload.update(
        {
            "bundle_dir": run_context.artifact_dir,
            "output_path": output_path,
            "requested_output_path": requested_output_path,
        }
    )
    return to_json_safe(payload)


def _scaffold_source_input(
    *,
    source_id: str,
    project: str,
    name: str,
    content: dict[str, Any],
    source_path: str,
    input_mode: str,
) -> GenerationSourceInput:
    return GenerationSourceInput(
        source_id=source_id,
        project=project,
        input_format=SourceInputFormat.STRUCTURED,
        name=name,
        content=json.dumps(content, ensure_ascii=False),
        source_path=Path(source_path),
        metadata={"input_mode": input_mode},
    )


def _resolve_scaffold_run_context(
    *,
    requested_output_path: Path,
    source_input: GenerationSourceInput,
):
    existing_context = _load_existing_bundle_context(requested_output_path)
    if existing_context is not None:
        return existing_context
    artifacts_root_dir = managed_generation_artifacts_root_for_path(requested_output_path)
    if artifacts_root_dir is None:
        raise GenerationCliInputError(
            [
                GenerationDiagnostic(
                    code="adapter_scaffold_requires_managed_root",
                    message="Staged authoring scaffold must target artifacts/agent/generation or one existing bundle inside it.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(requested_output_path),
                )
            ]
        )
    workspace_root = artifacts_root_dir.parent.parent.parent
    return initialize_generation_run_context(source_input, workspace_root=workspace_root)


def _load_existing_bundle_context(path: Path):
    if not path.exists():
        return None
    if path.is_dir():
        return load_generation_run_context_from_bundle_dir(path.resolve())
    if path.is_file():
        if path.name == CONTEXT_FILENAME:
            return load_generation_run_context_from_bundle_dir(path.parent.resolve())
        if path.name in {AUTHORING_PLAN_FILENAME, ENTITY_INVENTORY_FILENAME, OPERATION_INVENTORY_FILENAME}:
            return load_generation_run_context_from_bundle_dir(path.parent.resolve())
    return None


def _managed_bundle_dir_for_authoring_path(path: Path) -> Path | None:
    resolved = path.resolve()
    if managed_generation_artifacts_root_for_path(resolved) is None:
        return None
    if resolved.is_dir():
        return resolved
    if resolved.is_file() and resolved.name == AUTHORING_PLAN_FILENAME:
        return resolved.parent
    return None


def _resolve_bundle_dir(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_dir():
        return resolved
    if resolved.is_file() and resolved.name in {
        CONTEXT_FILENAME,
        AUTHORING_PLAN_FILENAME,
        ENTITY_INVENTORY_FILENAME,
        OPERATION_INVENTORY_FILENAME,
    }:
        return resolved.parent
    return resolved


def _highest_priority_status(statuses: list[StepStatus]) -> StepStatus:
    if StepStatus.ERROR in statuses:
        return StepStatus.ERROR
    if StepStatus.BLOCKED in statuses:
        return StepStatus.BLOCKED
    if StepStatus.FAIL in statuses:
        return StepStatus.FAIL
    return StepStatus.PASS


def _evaluate_authoring_bundle(
    bundle_dir: Path,
) -> tuple[StepStatus, dict[str, Any], list[GenerationDiagnostic]]:
    entity_inventory_path = bundle_dir / ENTITY_INVENTORY_FILENAME
    operation_inventory_path = bundle_dir / OPERATION_INVENTORY_FILENAME
    authoring_plan_path = bundle_dir / AUTHORING_PLAN_FILENAME

    entity_payload, entity_diagnostics = _validate_entity_inventory_file(entity_inventory_path)
    entity_status = StepStatus.PASS if not entity_diagnostics else StepStatus.BLOCKED

    operation_payload, operation_diagnostics = _validate_operation_inventory_file(operation_inventory_path)
    operation_status = StepStatus.PASS if not operation_diagnostics else StepStatus.BLOCKED

    authoring_result = AuthoringPlanCompiler().validate_file(authoring_plan_path)
    authoring_status = authoring_result.status

    stage_results = {
        "entity_inventory": {
            "status": entity_status.value,
            "file_path": str(entity_inventory_path),
            "diagnostics": [diagnostic.to_dict() for diagnostic in entity_diagnostics],
            "payload": entity_payload,
        },
        "operation_inventory": {
            "status": operation_status.value,
            "file_path": str(operation_inventory_path),
            "diagnostics": [diagnostic.to_dict() for diagnostic in operation_diagnostics],
            "payload": operation_payload,
        },
        "authoring_plan": {
            "status": authoring_status.value,
            "file_path": None if authoring_result.file_path is None else str(authoring_result.file_path),
            "case_count": authoring_result.case_count,
            "compiled_case_count": (
                0
                if authoring_result.compiled_plan is None
                else len(authoring_result.compiled_plan.planned_test_cases)
            ),
            "diagnostics": [diagnostic.to_dict() for diagnostic in authoring_result.diagnostics],
            "payload": None if authoring_result.authoring_plan is None else authoring_result.authoring_plan.to_dict(),
        },
    }
    overall_status = _highest_priority_status([entity_status, operation_status, authoring_status])
    diagnostics = [*entity_diagnostics, *operation_diagnostics, *authoring_result.diagnostics]
    return overall_status, stage_results, diagnostics


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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.init_authoring_plan:
            payload = run_init_authoring_plan(args)
        elif args.init_entity_inventory:
            payload = run_init_entity_inventory(args)
        elif args.init_operation_inventory:
            payload = run_init_operation_inventory(args)
        elif args.init_agent_plan:
            payload = run_init_agent_plan(args)
        elif args.validate_agent_plan:
            payload = run_validate_agent_plan(args)
        elif args.validate_entity_inventory:
            payload = run_validate_entity_inventory(args)
        elif args.validate_operation_inventory:
            payload = run_validate_operation_inventory(args)
        elif args.validate_authoring_bundle:
            payload = run_validate_authoring_bundle(args)
        elif args.validate_authoring_plan:
            payload = run_validate_authoring_plan(args)
        elif args.compile_authoring_plan:
            payload = run_compile_authoring_plan(args)
        elif args.review_drafts:
            payload = run_review(args)
        elif args.promote_draft or args.promote_all_drafts:
            payload = run_promotion(args)
        elif args.list_patch_templates:
            payload = run_list_patch_templates(args)
        elif args.show_patch_template:
            payload = run_show_patch_template(args)
        elif args.validate_scenario:
            payload = run_validate_scenario(args)
        elif args.validate_scenario_dir:
            payload = run_validate_scenario_dir(args)
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
        if args.init_authoring_plan or args.init_entity_inventory or args.init_operation_inventory or args.init_agent_plan or args.validate_agent_plan or args.validate_entity_inventory or args.validate_operation_inventory or args.validate_authoring_bundle or args.validate_authoring_plan or args.compile_authoring_plan
        else "review"
        if args.review_drafts
        else "promotion"
        if args.promote_draft or args.promote_all_drafts
        else "template"
        if args.list_patch_templates or args.show_patch_template
        else "revalidation_dir"
        if args.validate_scenario_dir
        else "revalidation"
        if args.validate_scenario
        else "generation"
    )
    _print_payload(payload, output_format=args.output_format, workflow=workflow)
    return 0 if payload["status"] == StepStatus.PASS.value else 1


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
    if args.promote_all_drafts:
        result = ScenarioDraftBatchPromotionService().promote(
            ScenarioPromotionBatchRequest(
                run_id=str(args.run_id),
                workspace_root=Path(args.workspace_root),
                target_dir=Path(args.target_dir),
                allow_invalid=args.allow_invalid,
                purge_target_dir=args.purge_target_dir,
            )
        )
        return to_json_safe(
            {
                "status": result.status.value,
                "run_id": result.run_id,
                "requested_count": result.requested_count,
                "promoted_count": result.promoted_count,
                "error_count": result.error_count,
                "target_dir": result.target_dir,
                "promotion_result_path": result.promotion_result_path,
                "results": [item.to_dict() for item in result.results],
                "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
            }
        )
    result = ScenarioDraftPromotionService().promote(
        ScenarioPromotionRequest(
            run_id=str(args.run_id),
            draft_id=str(args.draft_id),
            workspace_root=Path(args.workspace_root),
            target_dir=Path(args.target_dir),
            allow_invalid=args.allow_invalid,
            purge_target_dir=args.purge_target_dir,
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
    validation_notes = _validation_notes_for_result(result.validation_mode, compile_validation, preflight_validation)
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
            "validation_notes": validation_notes,
            "based_on_generated_draft": result.based_on_generated_draft,
            "generation_run_id": result.generation_run_id,
            "draft_id": result.draft_id,
        }
    )


def run_validate_scenario_dir(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _revalidation_dir_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    result = ScenarioDirectoryRevalidationService().validate(
        ScenarioDirectoryRevalidationRequest(
            directory_path=Path(args.path),
            validation_mode=args.mode,
            workspace_root=Path(args.workspace_root),
        )
    )
    validation_notes = _validation_notes_for_directory(result.validation_mode, result.results)
    return to_json_safe(
        {
            "status": result.status.value,
            "directory_path": result.directory_path,
            "validation_mode": result.validation_mode,
            "scenario_count": result.scenario_count,
            "failure_count": result.failure_count,
            "readiness_counts": result.readiness_counts,
            "failure_items": result.failure_items,
            "validation_notes": validation_notes,
            "results": [item.to_dict() for item in result.results],
        }
    )


class GenerationCliInputError(ValueError):
    def __init__(self, diagnostics: list[GenerationDiagnostic]) -> None:
        super().__init__("Invalid generation CLI input.")
        self.diagnostics = diagnostics


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


def _load_yaml_inventory_file(path: Path, *, inventory_kind: str) -> tuple[dict[str, Any] | None, list[GenerationDiagnostic]]:
    if not path.exists():
        return None, [
            GenerationDiagnostic(
                code=f"adapter_{inventory_kind}_file_missing",
                message=f"{inventory_kind.replace('_', ' ').title()} file does not exist.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
            )
        ]
    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [
            GenerationDiagnostic(
                code=f"adapter_{inventory_kind}_invalid_yaml",
                message=f"{inventory_kind.replace('_', ' ').title()} file must contain valid YAML.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
                details={"error": str(exc)},
            )
        ]
    if not isinstance(payload, dict):
        return None, [
            GenerationDiagnostic(
                code=f"adapter_{inventory_kind}_not_object",
                message=f"{inventory_kind.replace('_', ' ').title()} file must contain a YAML object.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
            )
        ]
    return payload, []


def _validate_entity_inventory_file(path: Path) -> tuple[dict[str, Any] | None, list[GenerationDiagnostic]]:
    payload, diagnostics = _load_yaml_inventory_file(path, inventory_kind="entity_inventory")
    if payload is None:
        return None, diagnostics
    required_fields = ("version", "source_id", "project", "surface", "entities")
    missing_fields = [field_name for field_name in required_fields if field_name not in payload]
    if missing_fields:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_entity_inventory_missing_fields",
                message="Entity inventory is missing required top-level fields.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
                details={"missing_fields": missing_fields},
            )
        )
        return payload, diagnostics
    if not isinstance(payload.get("entities"), list):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_entity_inventory_entities_not_list",
                message="Entity inventory field 'entities' must be a YAML array.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
            )
        )
        return payload, diagnostics
    seen_names: set[str] = set()
    for index, item in enumerate(payload.get("entities", []), start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_entity_inventory_item_invalid",
                    message="Each entity inventory item must be a YAML object.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity_index": index},
                )
            )
            continue
        entity_name = str(item.get("name") or "").strip()
        if not entity_name:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_entity_inventory_name_missing",
                    message="Each entity inventory item must include name.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity_index": index},
                )
            )
            continue
        if entity_name in seen_names:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_entity_inventory_duplicate_name",
                    message="Entity inventory names must be unique.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity": entity_name},
                )
            )
        seen_names.add(entity_name)
        if not str(item.get("id_field") or "").strip():
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_entity_inventory_id_field_missing",
                    message="Each entity inventory item must include id_field.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity": entity_name},
                )
            )
    return payload, diagnostics


def _validate_operation_inventory_file(path: Path) -> tuple[dict[str, Any] | None, list[GenerationDiagnostic]]:
    payload, diagnostics = _load_yaml_inventory_file(path, inventory_kind="operation_inventory")
    if payload is None:
        return None, diagnostics
    allowed_same_state_behaviors = {"reject", "idempotent_success"}
    required_fields = ("version", "source_id", "project", "surface", "entity_operations", "routes")
    missing_fields = [field_name for field_name in required_fields if field_name not in payload]
    if missing_fields:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_operation_inventory_missing_fields",
                message="Operation inventory is missing required top-level fields.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
                details={"missing_fields": missing_fields},
            )
        )
        return payload, diagnostics
    for field_name in ("entity_operations", "routes", "db_verifications"):
        if field_name in payload and not isinstance(payload.get(field_name), list):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_field_not_list",
                    message="Operation inventory list fields must be YAML arrays.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"field": field_name},
                )
            )
    entity_inventory_payload, entity_inventory_diagnostics = _validate_entity_inventory_file(path.parent / ENTITY_INVENTORY_FILENAME)
    entity_items = [] if entity_inventory_payload is None else entity_inventory_payload.get("entities", [])
    known_entities = {
        str(item.get("name")).strip()
        for item in entity_items
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    if path.parent / ENTITY_INVENTORY_FILENAME != path and (path.parent / ENTITY_INVENTORY_FILENAME).exists():
        diagnostics.extend(entity_inventory_diagnostics)
    for index, item in enumerate(payload.get("entity_operations", []), start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_operation_invalid",
                    message="Each entity operation inventory item must be a YAML object.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"operation_index": index},
                )
            )
            continue
        entity_name = str(item.get("entity") or "").strip()
        operation_name = str(item.get("operation") or "").strip()
        if not entity_name or not operation_name:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_operation_missing_fields",
                    message="Each entity operation must include entity and operation.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"operation_index": index},
                )
            )
        elif known_entities and entity_name not in known_entities:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_unknown_entity",
                    message="Entity operation references an entity not declared in entity-inventory.yaml.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity": entity_name, "operation": operation_name},
                )
            )
    for index, item in enumerate(payload.get("routes", []), start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_route_invalid",
                    message="Each route inventory item must be a YAML object.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
            continue
        method = str(item.get("method") or "").strip()
        route_path = str(item.get("path") or "").strip()
        if not method or not route_path:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_route_missing_fields",
                    message="Each route inventory item must include method and path.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
        if item.get("success_status") is not None and not isinstance(item.get("success_status"), int):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_success_status_invalid",
                    message="Route success_status must be an integer.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
        failure_statuses = item.get("failure_statuses", [])
        if failure_statuses is not None and not isinstance(failure_statuses, list):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_failure_statuses_invalid",
                    message="Route failure_statuses must be a YAML array when present.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
        target_state = item.get("target_state")
        if target_state is not None and not isinstance(target_state, str):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_target_state_invalid",
                    message="Route target_state must be a string when present.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
        same_state_behavior = item.get("same_state_behavior")
        normalized_same_state_behavior = (
            str(same_state_behavior).strip().lower()
            if isinstance(same_state_behavior, str)
            else ""
        )
        if same_state_behavior is not None and normalized_same_state_behavior not in allowed_same_state_behaviors:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_behavior_invalid",
                    message="Route same_state_behavior must be `reject` or `idempotent_success` when present.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_behavior": same_state_behavior},
                )
            )
        same_state_status = item.get("same_state_status")
        if same_state_status is not None and not isinstance(same_state_status, int):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_status_invalid",
                    message="Route same_state_status must be an integer when present.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
        if same_state_behavior is not None and same_state_status is None:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_contract_incomplete",
                    message="Route same_state_behavior requires same_state_status.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_behavior": same_state_behavior},
                )
            )
        if same_state_behavior is not None and not str(target_state or "").strip():
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_contract_incomplete",
                    message="Route same_state_behavior requires target_state so same-state lifecycle cases have an explicit source of truth.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_behavior": same_state_behavior},
                )
            )
        if isinstance(same_state_status, int) and normalized_same_state_behavior == "idempotent_success" and not (200 <= same_state_status < 300):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_contract_inconsistent",
                    message="same_state_behavior=idempotent_success requires a 2xx same_state_status.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_status": same_state_status},
                )
            )
        if isinstance(same_state_status, int) and normalized_same_state_behavior == "reject" and 200 <= same_state_status < 300:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_contract_inconsistent",
                    message="same_state_behavior=reject must not use a 2xx same_state_status.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_status": same_state_status},
                )
            )
        if (
            isinstance(same_state_status, int)
            and normalized_same_state_behavior == "reject"
            and isinstance(failure_statuses, list)
            and failure_statuses
            and same_state_status not in failure_statuses
        ):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_contract_inconsistent",
                    message="Rejecting same-state behavior must list same_state_status in failure_statuses.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_status": same_state_status},
                )
            )
    for index, item in enumerate(payload.get("db_verifications", []), start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_db_verification_invalid",
                    message="Each db_verifications item must be a YAML object.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"db_verification_index": index},
                )
            )
            continue
        entity_name = str(item.get("entity") or "").strip()
        operation_name = str(item.get("operation") or "").strip()
        if not entity_name or not operation_name:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_db_verification_missing_fields",
                    message="Each db_verifications item must include entity and operation.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"db_verification_index": index},
                )
            )
        elif known_entities and entity_name not in known_entities:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_unknown_entity",
                    message="DB verification references an entity not declared in entity-inventory.yaml.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity": entity_name, "operation": operation_name},
                )
            )
    return payload, diagnostics


def _adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.authoring_plan_file and not args.agent_plan_file and not args.prose and not args.source_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_source",
                message="Generation requires exactly one of --authoring-plan-file, --agent-plan-file, --prose, or --source-file.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.input_mode == GenerationInputMode.AUTHORING_PLAN.value and not args.authoring_plan_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_authoring_plan_mode_requires_file",
                message="input_mode=authoring_plan requires --authoring-plan-file.",
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
    if args.input_mode == GenerationInputMode.PROSE.value and args.authoring_plan_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_prose_mode_rejects_authoring_plan_file",
                message="input_mode=prose requires --prose or --source-file, not --authoring-plan-file.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.authoring_plan_file and not Path(args.authoring_plan_file).exists():
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_authoring_plan_file_missing",
                message="Authoring-plan file does not exist.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.authoring_plan_file,
            )
        )
    if args.authoring_plan_file and _path_under_root(Path(args.authoring_plan_file), LEGACY_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_authoring_plan_file_legacy_root_unsupported",
                message="Legacy artifacts/agent/input is no longer supported. Use artifacts/agent/generation for generated bundles.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.authoring_plan_file,
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
    if args.agent_plan_file and _path_under_root(Path(args.agent_plan_file), LEGACY_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_agent_plan_file_legacy_root_unsupported",
                message="Legacy artifacts/agent/input is no longer supported. Use one generation bundle root under artifacts/agent/generation.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.agent_plan_file,
            )
        )
    if not args.agent_plan_file and not args.authoring_plan_file and not args.source_id:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_source_id",
                message="Prose generation requires --source-id.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    if not args.agent_plan_file and not args.authoring_plan_file and not args.project:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_project",
                message="Prose generation requires --project.",
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
    elif not _path_under_root(Path(args.output), MANAGED_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_agent_plan_requires_managed_root",
                message="Agent plan scaffold must be written under artifacts/agent/generation.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.output,
            )
        )
    return diagnostics


def _init_authoring_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.output:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_authoring_plan_requires_output",
                message="--init-authoring-plan requires --output.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    elif not _path_under_root(Path(args.output), MANAGED_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_authoring_plan_requires_managed_root",
                message="Authoring plan scaffold must be written under artifacts/agent/generation.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.output,
            )
        )
    return diagnostics


def _init_entity_inventory_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if not args.output:
        return [
            GenerationDiagnostic(
                code="adapter_init_entity_inventory_requires_output",
                message="--init-entity-inventory requires --output.",
                severity=DiagnosticSeverity.ERROR,
            )
        ]
    if not _path_under_root(Path(args.output), MANAGED_AGENT_PLAN_ROOT):
        return [
            GenerationDiagnostic(
                code="adapter_init_entity_inventory_requires_managed_root",
                message="Entity inventory scaffold must target artifacts/agent/generation or one existing bundle inside it.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.output,
            )
        ]
    return []


def _init_operation_inventory_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if not args.output:
        return [
            GenerationDiagnostic(
                code="adapter_init_operation_inventory_requires_output",
                message="--init-operation-inventory requires --output.",
                severity=DiagnosticSeverity.ERROR,
            )
        ]
    if not _path_under_root(Path(args.output), MANAGED_AGENT_PLAN_ROOT):
        return [
            GenerationDiagnostic(
                code="adapter_init_operation_inventory_requires_managed_root",
                message="Operation inventory scaffold must target artifacts/agent/generation or one existing bundle inside it.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.output,
            )
        ]
    return []


def _validate_agent_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.agent_plan_file:
        if _path_under_root(Path(args.agent_plan_file), LEGACY_AGENT_PLAN_ROOT):
            return [
                GenerationDiagnostic(
                    code="adapter_validate_agent_plan_legacy_root_unsupported",
                    message="Legacy artifacts/agent/input is no longer supported. Use one generation bundle root under artifacts/agent/generation.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=args.agent_plan_file,
                )
            ]
        return []
    return [
        GenerationDiagnostic(
            code="adapter_validate_agent_plan_requires_file",
            message="--validate-agent-plan requires --agent-plan-file.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]


def _validate_authoring_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.authoring_plan_file:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_validate_authoring_plan_requires_file",
            message="--validate-authoring-plan requires --authoring-plan-file.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]


def _validate_entity_inventory_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.entity_inventory_file:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_validate_entity_inventory_requires_file",
            message="--validate-entity-inventory requires --entity-inventory-file.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]


def _validate_operation_inventory_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.operation_inventory_file:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_validate_operation_inventory_requires_file",
            message="--validate-operation-inventory requires --operation-inventory-file.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]


def _validate_authoring_bundle_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if not args.path:
        return [
            GenerationDiagnostic(
                code="adapter_validate_authoring_bundle_requires_path",
                message="--validate-authoring-bundle requires --path pointing to a managed bundle dir or one staged file inside it.",
                severity=DiagnosticSeverity.ERROR,
            )
        ]
    bundle_dir = _resolve_bundle_dir(Path(args.path))
    if not _path_under_root(bundle_dir, MANAGED_AGENT_PLAN_ROOT):
        return [
            GenerationDiagnostic(
                code="adapter_validate_authoring_bundle_requires_managed_root",
                message="--validate-authoring-bundle requires a path under artifacts/agent/generation.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.path,
            )
        ]
    return []


def _compile_authoring_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics = _validate_authoring_plan_adapter_diagnostics(args)
    if not args.output:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_compile_authoring_plan_requires_output",
                message="--compile-authoring-plan requires --output.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    elif not _path_under_root(Path(args.output), MANAGED_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_compile_authoring_plan_requires_managed_root",
                message="Compiled authoring-plan bundle must be written under artifacts/agent/generation.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.output,
            )
        )
    return diagnostics


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
    if args.promote_draft and not args.draft_id:
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


def _revalidation_dir_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if not args.path:
        return [
            GenerationDiagnostic(
                code="adapter_revalidation_dir_requires_path",
                message="--validate-scenario-dir requires --path.",
                severity=DiagnosticSeverity.ERROR,
            )
        ]
    path = Path(args.path)
    if not path.exists():
        return [
            GenerationDiagnostic(
                code="adapter_revalidation_dir_path_missing",
                message="--validate-scenario-dir path does not exist.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.path,
            )
        ]
    if path.exists() and not path.is_dir():
        return [
            GenerationDiagnostic(
                code="adapter_revalidation_dir_requires_directory",
                message="--validate-scenario-dir requires a directory path.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.path,
            )
        ]
    return []


def _error_payload(diagnostics: list[GenerationDiagnostic]) -> dict[str, Any]:
    return to_json_safe(
        {
            "status": StepStatus.BLOCKED.value,
            "message": "Generation adapter request is blocked by input or staged-validation diagnostics.",
            "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
            "artifact_paths": {},
        }
    )


def _print_payload(payload: dict[str, Any], *, output_format: str = "json", workflow: str = "generation") -> None:
    if output_format == "text" and workflow == "authoring":
        print(_render_authoring_text(payload))
        return
    if output_format == "text" and workflow == "generation":
        print(_render_generation_text(payload))
        return
    if output_format == "text" and workflow == "review":
        print(_render_review_text(payload))
        return
    if output_format == "text" and workflow == "promotion":
        print(_render_promotion_text(payload))
        return
    if output_format == "text" and workflow == "template":
        print(_render_template_text(payload))
        return
    if output_format == "text" and workflow == "revalidation":
        print(_render_revalidation_text(payload))
        return
    if output_format == "text" and workflow == "revalidation_dir":
        print(_render_revalidation_dir_text(payload))
        return
    print(json.dumps(payload, ensure_ascii=False))


def _render_generation_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Message: {payload.get('message', '')}",
        f"Run ID: {payload.get('run_id', '')}",
        f"Source ID: {payload.get('source_id', '')}",
        f"Project: {payload.get('project', '')}",
        f"Bundle: {payload.get('bundle_dir', '')}",
        f"Agent plan: {payload.get('agent_plan_path') or 'not_applicable'}",
        f"Input mode: {payload.get('input_mode', '')}",
        f"Cases: {payload.get('test_case_count', 0)}",
        f"Scenario rendering: {payload.get('scenario_rendering', 'not_requested')}",
    ]
    artifact_paths = payload.get("artifact_paths") or {}
    if artifact_paths:
        lines.append("Artifacts:")
        if artifact_paths.get("bundle"):
            lines.append(f"  - bundle: {artifact_paths['bundle']}")
        if artifact_paths.get("agent_plan"):
            lines.append(f"  - agent_plan: {artifact_paths['agent_plan']}")
        if artifact_paths.get("normalized_plan"):
            lines.append(f"  - normalized_plan: {artifact_paths['normalized_plan']}")
        if artifact_paths.get("summary"):
            lines.append(f"  - summary: {artifact_paths['summary']}")
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("Diagnostics:")
        for diagnostic in diagnostics[:12]:
            lines.append(
                f"  - {diagnostic.get('severity', '').lower()}: {diagnostic.get('code', '')}: {diagnostic.get('message', '')}"
            )
    return "\n".join(lines).rstrip()


def _render_authoring_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Message: {payload.get('message', '')}",
    ]
    if payload.get("output_path"):
        lines.extend(
            [
                f"Bundle: {payload.get('bundle_dir', '')}",
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
    stage_results = payload.get("stage_results") or {}
    if stage_results:
        lines.append("Stages:")
        for stage_name in payload.get("stage_order") or stage_results.keys():
            stage_payload = stage_results.get(stage_name) or {}
            stage_line = f"  - {stage_name}: {stage_payload.get('status', '')}"
            if stage_name == "authoring_plan":
                stage_line += (
                    f" ({stage_payload.get('compiled_case_count', 0)}/"
                    f"{stage_payload.get('case_count', 0)} cases compile)"
                )
            lines.append(stage_line)
    handoff = payload.get("handoff") or {}
    if handoff:
        lines.extend(
            [
                "Handoff:",
                f"  - scope: {handoff.get('scope', '')}",
                f"  - scenario_drafts_rendered: {handoff.get('scenario_drafts_rendered', False)}",
                f"  - promoted_scenarios: {handoff.get('promoted_scenarios', False)}",
            ]
        )
        next_commands = handoff.get("next_commands") or []
        if next_commands:
            lines.append("Next commands:")
            for command in next_commands:
                lines.append(f"  - {command.get('label', '')}: {command.get('command', '')}")
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("Diagnostics:")
        for diagnostic in diagnostics:
            lines.append(f"  - {diagnostic.get('code', '')}: {diagnostic.get('message', '')}")
            details = diagnostic.get("details") or {}
            if details.get("rule"):
                lines.append(f"    Rule: {details.get('rule', '')}")
            if details.get("hint"):
                lines.append(f"    Hint: {details.get('hint', '')}")
            examples = details.get("supported_examples") or []
            if examples:
                lines.append("    Examples:")
                for example in examples[:6]:
                    lines.append(f"      - {example}")
            suggested_case = details.get("suggested_case") or {}
            if suggested_case.get("title"):
                lines.append(
                    f"    Suggest: {suggested_case.get('title', '')} [{suggested_case.get('http_method', '')} {suggested_case.get('endpoint_path', '')}]"
                )
            if suggested_case.get("objective"):
                lines.append(f"    Objective: {suggested_case.get('objective', '')}")
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
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("Review diagnostics:")
        for diagnostic in diagnostics:
            lines.append(f"  - {diagnostic.get('code', '')}: {diagnostic.get('message', '')}")
            suggested_case = (diagnostic.get("details") or {}).get("suggested_case") or {}
            if suggested_case.get("title"):
                lines.append(
                    f"    Suggest: {suggested_case.get('title', '')} [{suggested_case.get('http_method', '')} {suggested_case.get('endpoint_path', '')}]"
                )
            if suggested_case.get("objective"):
                lines.append(f"    Objective: {suggested_case.get('objective', '')}")
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


def _render_promotion_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Run ID: {payload.get('run_id', '')}",
    ]
    if "draft_id" in payload:
        lines.extend(
            [
                f"Draft ID: {payload.get('draft_id', '')}",
                f"Source: {payload.get('source_path') or ''}",
                f"Target: {payload.get('target_path') or ''}",
            ]
        )
    else:
        lines.extend(
            [
                f"Requested: {payload.get('requested_count', 0)}",
                f"Promoted: {payload.get('promoted_count', 0)}",
                f"Errors: {payload.get('error_count', 0)}",
                f"Target dir: {payload.get('target_dir') or ''}",
            ]
        )
        results = payload.get("results") or []
        if results:
            lines.append("Results:")
            for item in results:
                lines.append(
                    f"  - {item.get('draft_id', '')}: {item.get('status', '')} -> {item.get('target_path') or ''}"
                )
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("Diagnostics:")
        for diagnostic in diagnostics:
            lines.append(f"  - {diagnostic.get('code', '')}: {diagnostic.get('message', '')}")
    if payload.get("promotion_result_path"):
        lines.append(f"Promotion result: {payload.get('promotion_result_path')}")
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
    validation_notes = payload.get("validation_notes") or []
    if validation_notes:
        lines.append("Validation notes:")
        for note in validation_notes:
            lines.append(f"  - {note}")
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


def _render_revalidation_dir_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Directory: {payload['directory_path']}",
        f"Validation mode: {payload.get('validation_mode', 'parser')}",
        f"Scenarios: {payload.get('scenario_count', 0)}",
        f"Failures: {payload.get('failure_count', 0)}",
    ]
    readiness_counts = payload.get("readiness_counts") or {}
    if readiness_counts:
        lines.append("Readiness counts:")
        for key, value in sorted(readiness_counts.items()):
            lines.append(f"  - {key}: {value}")
    failure_items = payload.get("failure_items") or []
    if failure_items:
        lines.append("Failures:")
        for item in failure_items:
            lines.append(
                f"  - {item.get('file_path', '')}: parse={item.get('parse_status', '')} readiness={item.get('readiness_category', '')}"
            )
            gap_codes = item.get("gap_codes") or []
            if gap_codes:
                lines.append(f"    Gaps: {', '.join(str(code) for code in gap_codes)}")
    validation_notes = payload.get("validation_notes") or []
    if validation_notes:
        lines.append("Validation notes:")
        for note in validation_notes:
            lines.append(f"  - {note}")
    return "\n".join(lines).rstrip()


def _validation_notes_for_result(
    validation_mode: str,
    compile_validation: Any,
    preflight_validation: Any,
) -> list[str]:
    if validation_mode == "compile" and compile_validation is not None:
        warnings = getattr(compile_validation, "warnings", [])
        if warnings:
            return [
                "Compile mode is structural only: env-backed external inputs are declared but not resolved here.",
                "Run --mode preflight to verify that the selected environment file resolves all required external variables.",
            ]
    if validation_mode == "preflight" and preflight_validation is not None:
        if getattr(preflight_validation, "preflight_status", None) == ScenarioPreflightStatus.SUCCESS:
            return [
                "Preflight mode includes environment resolution and dependency checks in addition to compile validation."
            ]
    return []


def _validation_notes_for_directory(validation_mode: str, results: list[Any]) -> list[str]:
    if validation_mode != "compile":
        return []
    for item in results:
        compile_validation = getattr(item, "compile_validation", None)
        warnings = [] if compile_validation is None else getattr(compile_validation, "warnings", [])
        if warnings:
            return [
                "Compile directory validation is structural only: env-backed external inputs remain unresolved by design.",
                "Use --mode preflight for environment-aware validation of the promoted scenario directory.",
            ]
    return []


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _path_under_root(path: Path, root_parts: tuple[str, ...]) -> bool:
    parts = tuple(part.lower() for part in path.parts)
    width = len(root_parts)
    return any(parts[index:index + width] == root_parts for index in range(len(parts) - width + 1))


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
