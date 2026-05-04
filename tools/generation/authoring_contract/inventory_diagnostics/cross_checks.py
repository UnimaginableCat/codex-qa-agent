"""Cross-check authoring-plan contracts against staged inventories."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic
from tools.generation.persistence.artifacts import managed_generation_artifacts_root_for_path

from ..case_diagnostics.lifecycle import (
    _expected_precondition_state,
    _is_same_state_inventory_case,
    _same_state_inventory_contract_diagnostics,
)
from ..diagnostics import authoring_diagnostic
from ..models import AuthoringPlan, _maybe_int
from .indexes import (
    _db_verification_inventory_specs,
    _entity_inventory_specs,
    _entity_operation_inventory_specs,
    _infer_route_entity,
    _infer_setup_state_from_inventory,
    _is_declared_failure_status,
    _normalized_inventory_states,
    _normalized_scoped_by_fields,
    _normalized_string_list,
    _route_inventory_key,
    _route_inventory_specs,
    _scope_matches_entity_identity,
    _single_or_sorted_state,
)
from .loading import _load_entity_inventory_payload, _load_operation_inventory_payload


def _stage_inventory_contract_diagnostics(
    *,
    file_path: Path,
    authoring_plan: AuthoringPlan,
) -> list[GenerationDiagnostic]:
    if managed_generation_artifacts_root_for_path(file_path) is None:
        return []
    entity_inventory = _load_entity_inventory_payload(file_path)
    operation_inventory = _load_operation_inventory_payload(file_path)
    if entity_inventory is None or operation_inventory is None:
        return []
    return _cross_check_authoring_plan_against_stage_inventories(
        authoring_plan=authoring_plan,
        file_path=file_path,
        entity_inventory=entity_inventory,
        operation_inventory=operation_inventory,
    )


def _cross_check_authoring_plan_against_stage_inventories(
    *,
    authoring_plan: AuthoringPlan,
    file_path: Path,
    entity_inventory: dict[str, Any],
    operation_inventory: dict[str, Any],
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    source_ref = str(file_path)
    entity_specs = _entity_inventory_specs(entity_inventory)
    entity_operation_specs = _entity_operation_inventory_specs(operation_inventory)
    route_specs = _route_inventory_specs(operation_inventory)
    db_verification_specs = _db_verification_inventory_specs(operation_inventory)

    for entity_name, entity_spec in authoring_plan.entities.items():
        inventory_entity_spec = entity_specs.get(entity_name)
        if inventory_entity_spec is None:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_stage_inventory_entity_mismatch",
                    "Authoring-plan entity is not declared in entity-inventory.yaml.",
                    source_ref=source_ref,
                    details={"entity": entity_name},
                )
            )
            continue
        inventory_id_field = str(inventory_entity_spec.get("id_field") or "").strip()
        inventory_key_fields = _normalized_string_list(inventory_entity_spec.get("key_fields"))
        authored_id_field = entity_spec.id_field.strip()
        if inventory_id_field and authored_id_field and inventory_id_field != authored_id_field:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_stage_inventory_entity_mismatch",
                    "Authoring-plan entity id_field must match entity-inventory.yaml.",
                    source_ref=source_ref,
                    details={
                        "entity": entity_name,
                        "authored_id_field": authored_id_field,
                        "inventory_id_field": inventory_id_field,
                    },
                )
            )
        for operation_name, operation in entity_spec.operations.items():
            operation_key = (entity_name, operation_name)
            if operation.route is not None:
                if operation_key not in entity_operation_specs:
                    diagnostics.append(
                        authoring_diagnostic(
                            "authoring_stage_inventory_operation_mismatch",
                            "Route-backed entity operation is not declared in operation-inventory.yaml.",
                            source_ref=source_ref,
                            details={"entity": entity_name, "operation": operation_name},
                        )
                    )
            if operation.sql.strip():
                db_verification_spec = db_verification_specs.get(operation_key)
                if db_verification_spec is None:
                    diagnostics.append(
                        authoring_diagnostic(
                            "authoring_stage_inventory_operation_mismatch",
                            "DB verification operation is not declared in operation-inventory.yaml.",
                            source_ref=source_ref,
                            details={"entity": entity_name, "operation": operation_name},
                        )
                    )
                else:
                    scoped_by = _normalized_scoped_by_fields(db_verification_spec.get("scoped_by"))
                    if scoped_by and not _scope_matches_entity_identity(
                        scoped_by=scoped_by,
                        id_field=inventory_id_field,
                        key_fields=inventory_key_fields,
                    ):
                        diagnostics.append(
                            authoring_diagnostic(
                                "authoring_stage_inventory_operation_mismatch",
                                "DB verification scope must use fields declared as the entity id_field or key_fields in staged inventories.",
                                source_ref=source_ref,
                                details={
                                    "entity": entity_name,
                                    "operation": operation_name,
                                    "scoped_by": scoped_by,
                                    "inventory_id_field": inventory_id_field,
                                    "inventory_key_fields": inventory_key_fields,
                                },
                            )
                        )

    for case in authoring_plan.cases:
        case_ref = case.id.strip() or source_ref
        for setup_step in case.setup:
            step_key = (setup_step.use_entity.strip(), setup_step.operation.strip())
            if step_key not in entity_operation_specs:
                diagnostics.append(
                    authoring_diagnostic(
                        "authoring_stage_inventory_operation_mismatch",
                        "Workflow setup operation is not declared in operation-inventory.yaml.",
                        source_ref=case_ref,
                        details={"entity": step_key[0], "operation": step_key[1]},
                    )
                )
        if case.oracle is not None and case.oracle.persisted_state is not None:
            persisted_key = (
                case.oracle.persisted_state.entity.strip(),
                case.oracle.persisted_state.operation.strip(),
            )
            if persisted_key not in db_verification_specs:
                diagnostics.append(
                    authoring_diagnostic(
                        "authoring_stage_inventory_operation_mismatch",
                        "Persisted-state operation is not declared in operation-inventory.yaml.",
                        source_ref=case_ref,
                        details={"entity": persisted_key[0], "operation": persisted_key[1]},
                    )
                )
        if case.execute is None or case.execute.route is None:
            continue
        authored_route_path = case.execute.route.path.strip()
        route_key = _route_inventory_key(case.execute.route.method, authored_route_path)
        route_spec = route_specs.get(route_key)
        if route_spec is None:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_stage_inventory_route_mismatch",
                    "Authoring case route is not declared in operation-inventory.yaml.",
                    source_ref=case_ref,
                    details={"method": route_key[0], "path": authored_route_path, "route_shape": route_key[1]},
                )
            )
            continue
        expected_status = None if case.oracle is None else case.oracle.status_code
        failure_statuses: set[int] = set()
        if isinstance(expected_status, int):
            success_status = _maybe_int(route_spec.get("success_status"))
            raw_failure_statuses = {_maybe_int(item) for item in route_spec.get("failure_statuses", [])}
            raw_failure_statuses.discard(None)
            failure_statuses = {item for item in raw_failure_statuses if item is not None}
            if 200 <= expected_status < 300:
                if success_status is not None and expected_status != success_status:
                    diagnostics.append(
                        authoring_diagnostic(
                            "authoring_stage_inventory_status_mismatch",
                            "Success HTTP status in authoring-plan.yaml does not match operation-inventory.yaml.",
                            source_ref=case_ref,
                            details={
                                "method": route_key[0],
                                "path": authored_route_path,
                                "route_shape": route_key[1],
                                "authored_status": expected_status,
                                "inventory_success_status": success_status,
                            },
                        )
                    )
            elif failure_statuses and expected_status not in failure_statuses:
                diagnostics.append(
                    authoring_diagnostic(
                        "authoring_stage_inventory_status_mismatch",
                        "Failure HTTP status in authoring-plan.yaml is not listed in operation-inventory.yaml.",
                        source_ref=case_ref,
                        details={
                            "method": route_key[0],
                            "path": authored_route_path,
                            "route_shape": route_key[1],
                            "authored_status": expected_status,
                            "inventory_failure_statuses": sorted(failure_statuses),
                        },
                    )
                )
        if case.kind.strip().lower() != "workflow" or not case.setup:
            continue
        route_entity = _infer_route_entity(authored_route_path, entity_specs)
        actual_state = _infer_setup_state_from_inventory(
            case.setup,
            entity_operation_specs,
            route_entity=route_entity,
        )
        diagnostics.extend(
            _same_state_inventory_contract_diagnostics(
                case=case,
                case_ref=case_ref,
                route_spec=route_spec,
                route_key=route_key,
                actual_state=actual_state,
            )
        )
        if _is_same_state_inventory_case(route_spec=route_spec, route_key=route_key, actual_state=actual_state):
            continue
        if _is_declared_failure_status(expected_status, failure_statuses):
            continue
        expected_states = _normalized_inventory_states(route_spec.get("precondition_state"))
        precondition_declared = bool(expected_states)
        if not expected_states:
            expected_state = _expected_precondition_state(case)
            expected_states = {expected_state} if expected_state is not None else set()
        if not expected_states or actual_state is None or actual_state in expected_states:
            continue
        diagnostic_code = (
            "authoring_stage_inventory_state_mismatch"
            if precondition_declared
            else "authoring_stage_inventory_state_mismatch_inferred"
        )
        diagnostics.append(
            authoring_diagnostic(
                diagnostic_code,
                "Workflow setup state derived from operation-inventory.yaml does not satisfy the case precondition.",
                severity=DiagnosticSeverity.ERROR if precondition_declared else DiagnosticSeverity.WARNING,
                source_ref=case_ref,
                details={
                    "expected_state": _single_or_sorted_state(expected_states),
                    "actual_state": actual_state,
                    "precondition_declared": precondition_declared,
                    "route_entity": route_entity,
                    "route_path": authored_route_path,
                    "route_shape": route_key[1],
                    "setup_operations": [
                        {"entity": step.use_entity, "operation": step.operation}
                        for step in case.setup
                    ],
                },
            )
        )
    return diagnostics
