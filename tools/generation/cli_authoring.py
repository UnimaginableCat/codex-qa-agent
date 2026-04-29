"""Support code for the generation CLI adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.application import GenerationInputMode
from tools.generation.authoring import AgentPlanAuthoringService
from tools.generation.authoring_contract import AuthoringPlanCompiler, AuthoringPlanTemplateService
from tools.generation.cli_authoring_bundle import (
    _evaluate_authoring_bundle,
    _resolve_scaffold_run_context,
    _scaffold_source_input,
)
from tools.generation.cli_authoring_sync import _sync_authoring_plan_from_inventories, _write_synced_authoring_plan
from tools.generation.cli_core import (
    MANAGED_AGENT_PLAN_ROOT,
    GenerationCliInputError,
    _managed_bundle_dir_for_authoring_path,
    _resolve_bundle_dir,
)
from tools.generation.cli_diagnostics import (
    _compile_authoring_plan_adapter_diagnostics,
    _init_agent_plan_adapter_diagnostics,
    _init_authoring_plan_adapter_diagnostics,
    _init_entity_inventory_adapter_diagnostics,
    _init_operation_inventory_adapter_diagnostics,
    _sync_authoring_plan_adapter_diagnostics,
    _validate_agent_plan_adapter_diagnostics,
    _validate_authoring_bundle_adapter_diagnostics,
    _validate_authoring_plan_adapter_diagnostics,
    _validate_entity_inventory_adapter_diagnostics,
    _validate_operation_inventory_adapter_diagnostics,
)
from tools.generation.cli_inventory import _validate_entity_inventory_file, _validate_operation_inventory_file
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic, GenerationSourceInput, SourceInputFormat
from tools.generation.orchestration.context import initialize_generation_run_context
from tools.generation.persistence import FileGenerationArtifactStore, managed_generation_artifacts_root_for_path
from tools.generation.persistence.artifacts import (
    AUTHORING_PLAN_FILENAME,
    CONTEXT_FILENAME,
    ENTITY_INVENTORY_FILENAME,
    OPERATION_INVENTORY_FILENAME,
)


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
    requested_output_path = _requested_scaffold_output_path(args)
    _ensure_run_id_scaffold_target_exists(args, requested_output_path)
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
            "message": (
                "Authoring-plan bundle scaffolded. Fill and validate one stage at a time: "
                "entity inventory, then operation inventory, then authoring plan."
            ),
            "bundle_dir": run_context.artifact_dir,
            "output_path": output_path,
            "entity_inventory_path": entity_inventory_path,
            "operation_inventory_path": operation_inventory_path,
            "requested_output_path": requested_output_path,
            "template_version": template.metadata.get("template_version", ""),
            "input_mode": GenerationInputMode.AUTHORING_PLAN.value,
            "diagnostics": [],
            "stage_policy": {
                "mode": "strict_sequential_authoring",
                "rule": "Do not fill or substantially rewrite multiple staged files in the same authoring pass.",
                "stages": [
                    {
                        "name": "entity_inventory",
                        "path": entity_inventory_path,
                        "required_gate": "validate-entity-inventory",
                    },
                    {
                        "name": "operation_inventory",
                        "path": operation_inventory_path,
                        "required_gate": "validate-operation-inventory",
                        "requires_passed_stage": "entity_inventory",
                    },
                    {
                        "name": "sync_authoring_plan",
                        "path": output_path,
                        "required_gate": "sync-authoring-plan",
                        "requires_passed_stage": "operation_inventory",
                    },
                    {
                        "name": "authoring_plan",
                        "path": output_path,
                        "required_gate": "validate-authoring-plan",
                        "requires_passed_stage": "sync_authoring_plan",
                    },
                    {
                        "name": "bundle",
                        "path": run_context.artifact_dir,
                        "required_gate": "validate-authoring-bundle",
                        "requires_passed_stage": "authoring_plan",
                    },
                ],
            },
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
    requested_output_path = _requested_scaffold_output_path(args)
    _ensure_run_id_scaffold_target_exists(args, requested_output_path)
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
    requested_output_path = _requested_scaffold_output_path(args)
    _ensure_run_id_scaffold_target_exists(args, requested_output_path)
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



def run_sync_authoring_plan(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _sync_authoring_plan_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    bundle_dir = _resolve_bundle_dir(Path(args.path))
    entity_inventory_path = bundle_dir / ENTITY_INVENTORY_FILENAME
    operation_inventory_path = bundle_dir / OPERATION_INVENTORY_FILENAME
    authoring_plan_path = bundle_dir / AUTHORING_PLAN_FILENAME

    entity_payload, entity_diagnostics = _validate_entity_inventory_file(entity_inventory_path)
    operation_payload, operation_diagnostics = _validate_operation_inventory_file(operation_inventory_path)
    if entity_diagnostics or operation_diagnostics or entity_payload is None or operation_payload is None:
        return to_json_safe(
            {
                "status": StepStatus.BLOCKED.value,
                "message": "Authoring-plan sync is blocked until staged inventories validate.",
                "bundle_dir": str(bundle_dir),
                "diagnostics": [
                    diagnostic.to_dict()
                    for diagnostic in [*entity_diagnostics, *operation_diagnostics]
                ],
                "stage_results": {
                    "entity_inventory": {
                        "status": (StepStatus.PASS if not entity_diagnostics else StepStatus.BLOCKED).value,
                        "file_path": str(entity_inventory_path),
                        "diagnostics": [diagnostic.to_dict() for diagnostic in entity_diagnostics],
                    },
                    "operation_inventory": {
                        "status": (StepStatus.PASS if not operation_diagnostics else StepStatus.BLOCKED).value,
                        "file_path": str(operation_inventory_path),
                        "diagnostics": [diagnostic.to_dict() for diagnostic in operation_diagnostics],
                    },
                },
            }
        )

    load_result = AuthoringPlanCompiler().load(authoring_plan_path)
    load_diagnostics = list(load_result.diagnostics)
    if load_diagnostics and authoring_plan_path.exists():
        return to_json_safe(
            {
                "status": StepStatus.BLOCKED.value,
                "message": "Authoring-plan sync is blocked because the existing authoring-plan cannot be loaded.",
                "bundle_dir": str(bundle_dir),
                "file_path": str(authoring_plan_path),
                "diagnostics": [diagnostic.to_dict() for diagnostic in load_diagnostics],
            }
        )
    template_service = AuthoringPlanTemplateService()
    existing_plan = load_result.authoring_plan or template_service.build_template(
        source_id=str(entity_payload.get("source_id") or operation_payload.get("source_id") or ""),
        project=str(entity_payload.get("project") or operation_payload.get("project") or ""),
        title=str(entity_payload.get("surface") or operation_payload.get("surface") or "Authoring plan"),
        goal=str(operation_payload.get("purpose") or entity_payload.get("purpose") or "Author coverage from staged inventories."),
    )
    synced_plan = _sync_authoring_plan_from_inventories(
        existing_plan=existing_plan,
        entity_inventory=entity_payload,
        operation_inventory=operation_payload,
    )
    _write_synced_authoring_plan(bundle_dir, synced_plan)
    validation_result = AuthoringPlanCompiler().validate_file(authoring_plan_path)
    followup_message = (
        "Authoring-plan synced from staged inventories, but follow-up validation is still blocked. "
        "Author or fix cases next, then run --validate-authoring-plan."
        if validation_result.status != StepStatus.PASS
        else "Authoring-plan synced from staged inventories and follow-up validation passed."
    )
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "message": followup_message,
            "bundle_dir": str(bundle_dir),
            "output_path": str(authoring_plan_path),
            "case_count": len(synced_plan.cases),
            "validation_status_after_sync": validation_result.status.value,
            "next_status": validation_result.status.value,
            "validation_diagnostics_after_sync": [
                diagnostic.to_dict() for diagnostic in validation_result.diagnostics
            ],
            "authoring_plan": synced_plan.to_dict(),
        }
    )


def _requested_scaffold_output_path(args: argparse.Namespace) -> Path:
    requested_output_path = Path(args.output)
    run_id = str(args.run_id or "").strip()
    if not run_id:
        return requested_output_path
    if requested_output_path.name == run_id:
        return requested_output_path
    return requested_output_path / run_id


def _ensure_run_id_scaffold_target_exists(args: argparse.Namespace, requested_output_path: Path) -> None:
    run_id = str(args.run_id or "").strip()
    if not run_id:
        return
    context_path = requested_output_path / CONTEXT_FILENAME
    if context_path.exists():
        return
    raise GenerationCliInputError(
        [
            GenerationDiagnostic(
                code="adapter_scaffold_run_id_bundle_missing",
                message="--run-id scaffold target must reference an existing managed generation bundle.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(requested_output_path),
                details={"run_id": run_id},
            )
        ]
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

