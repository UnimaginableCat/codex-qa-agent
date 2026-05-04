"""Support code for the generation CLI adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.common.statuses import StepStatus
from tools.generation.authoring_contract import AuthoringPlanCompiler
from tools.generation.cli_core import (
    GenerationCliInputError,
    _highest_priority_status,
)
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic, GenerationSourceInput, SourceInputFormat
from tools.generation.inventory import _validate_entity_inventory_file, _validate_operation_inventory_file
from tools.generation.orchestration.context import initialize_generation_run_context
from tools.generation.persistence import managed_generation_artifacts_root_for_path
from tools.generation.persistence.artifacts import (
    AUTHORING_PLAN_FILENAME,
    CONTEXT_FILENAME,
    ENTITY_INVENTORY_FILENAME,
    OPERATION_INVENTORY_FILENAME,
    load_generation_run_context_from_bundle_dir,
)


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



def _evaluate_authoring_bundle(
    bundle_dir: Path,
) -> tuple[StepStatus, dict[str, Any], list[GenerationDiagnostic]]:
    entity_inventory_path = bundle_dir / ENTITY_INVENTORY_FILENAME
    operation_inventory_path = bundle_dir / OPERATION_INVENTORY_FILENAME
    authoring_plan_path = bundle_dir / AUTHORING_PLAN_FILENAME

    entity_payload, entity_diagnostics = _validate_entity_inventory_file(entity_inventory_path)
    entity_status = _inventory_validation_status(entity_diagnostics)

    operation_payload, operation_diagnostics = _validate_operation_inventory_file(operation_inventory_path)
    operation_status = _inventory_validation_status(operation_diagnostics)

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


def _inventory_validation_status(diagnostics: list[GenerationDiagnostic]) -> StepStatus:
    if any(diagnostic.severity == DiagnosticSeverity.ERROR for diagnostic in diagnostics):
        return StepStatus.BLOCKED
    return StepStatus.PASS

