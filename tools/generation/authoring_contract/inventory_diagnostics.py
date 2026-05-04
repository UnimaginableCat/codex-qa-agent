"""Stage-inventory validation for compact authoring plans."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.persistence.artifacts import (
    ENTITY_INVENTORY_FILENAME,
    OPERATION_INVENTORY_FILENAME,
    managed_generation_artifacts_root_for_path,
)

from .case_diagnostics import (
    _expected_precondition_state,
    _is_same_state_inventory_case,
    _normalized_inventory_state,
    _same_state_inventory_contract_diagnostics,
)
from .diagnostics import authoring_diagnostic
from .models import AuthoringPlan, AuthoringSetupStep, _maybe_int

_ROUTE_PLACEHOLDER_PATTERN = re.compile(r"{{\s*[^{}]+?\s*}}")


def _required_stage_inventory_diagnostics(file_path: Path) -> list[GenerationDiagnostic]:
    if managed_generation_artifacts_root_for_path(file_path) is None:
        return []
    inventory_specs = (
        (
            "entity_inventory",
            file_path.parent / ENTITY_INVENTORY_FILENAME,
            ("version", "source_id", "project", "surface", "entities"),
            {"entities"},
        ),
        (
            "operation_inventory",
            file_path.parent / OPERATION_INVENTORY_FILENAME,
            ("version", "source_id", "project", "surface", "entity_operations", "routes"),
            {"entity_operations", "routes", "db_verifications"},
        ),
    )
    diagnostics: list[GenerationDiagnostic] = []
    for inventory_kind, inventory_path, required_fields, list_fields in inventory_specs:
        diagnostics.extend(
            _inventory_file_diagnostics(
                inventory_kind=inventory_kind,
                inventory_path=inventory_path,
                required_fields=required_fields,
                list_fields=list_fields,
            )
        )
    return diagnostics


def _inventory_file_diagnostics(
    *,
    inventory_kind: str,
    inventory_path: Path,
    required_fields: tuple[str, ...],
    list_fields: set[str],
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not inventory_path.exists():
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_missing",
                "Managed authoring bundles require staged inventory files before authoring-plan validation or compile.",
                source_ref=str(inventory_path),
                details={"inventory_kind": inventory_kind, "path": str(inventory_path)},
            )
        )
        return diagnostics
    try:
        import yaml

        payload = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
    except Exception as exc:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_invalid",
                "Staged inventory file could not be parsed as YAML.",
                source_ref=str(inventory_path),
                details={"inventory_kind": inventory_kind, "path": str(inventory_path), "error": str(exc)},
            )
        )
        return diagnostics
    if not isinstance(payload, dict):
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_invalid",
                "Staged inventory file must contain a YAML object.",
                source_ref=str(inventory_path),
                details={"inventory_kind": inventory_kind, "path": str(inventory_path)},
            )
        )
        return diagnostics
    missing_fields = [field_name for field_name in required_fields if field_name not in payload]
    if missing_fields:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_invalid",
                "Staged inventory file is missing required top-level fields.",
                source_ref=str(inventory_path),
                details={
                    "inventory_kind": inventory_kind,
                    "path": str(inventory_path),
                    "missing_fields": missing_fields,
                },
            )
        )
    for field_name in list_fields:
        if field_name in payload and not isinstance(payload.get(field_name), list):
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_stage_inventory_invalid",
                    "Staged inventory list fields must be YAML arrays.",
                    source_ref=str(inventory_path),
                    details={
                        "inventory_kind": inventory_kind,
                        "path": str(inventory_path),
                        "field": field_name,
                    },
                )
            )
    return diagnostics


def _stage_inventory_contract_diagnostics(
    *,
    file_path: Path,
    authoring_plan: AuthoringPlan,
) -> list[GenerationDiagnostic]:
    if managed_generation_artifacts_root_for_path(file_path) is None:
        return []
    entity_inventory = _load_inventory_payload_if_valid(
        inventory_path=file_path.parent / ENTITY_INVENTORY_FILENAME,
        required_fields=("version", "source_id", "project", "surface", "entities"),
        list_fields={"entities"},
    )
    operation_inventory = _load_inventory_payload_if_valid(
        inventory_path=file_path.parent / OPERATION_INVENTORY_FILENAME,
        required_fields=("version", "source_id", "project", "surface", "entity_operations", "routes"),
        list_fields={"entity_operations", "routes", "db_verifications"},
    )
    if entity_inventory is None or operation_inventory is None:
        return []
    return _cross_check_authoring_plan_against_stage_inventories(
        authoring_plan=authoring_plan,
        file_path=file_path,
        entity_inventory=entity_inventory,
        operation_inventory=operation_inventory,
    )


def suppress_inventory_backed_same_state_warnings(
    *,
    file_path: Path,
    diagnostics: list[GenerationDiagnostic],
) -> list[GenerationDiagnostic]:
    if managed_generation_artifacts_root_for_path(file_path) is None:
        return diagnostics
    operation_inventory = _load_inventory_payload_if_valid(
        inventory_path=file_path.parent / OPERATION_INVENTORY_FILENAME,
        required_fields=("version", "source_id", "project", "surface", "entity_operations", "routes"),
        list_fields={"entity_operations", "routes", "db_verifications"},
    )
    if operation_inventory is None:
        return diagnostics
    route_specs = _route_inventory_specs(operation_inventory)
    same_state_route_shapes = {
        route_shape
        for (_, route_shape), route_spec in route_specs.items()
        if _has_explicit_same_state_contract(route_spec)
    }
    filtered: list[GenerationDiagnostic] = []
    for diagnostic in diagnostics:
        if diagnostic.code != "authoring_same_state_lifecycle_contract_unconfirmed":
            filtered.append(diagnostic)
            continue
        route_shape = _route_path_shape(str(diagnostic.details.get("route_path") or ""))
        if route_shape not in same_state_route_shapes:
            filtered.append(diagnostic)
    return filtered


def _load_inventory_payload_if_valid(
    *,
    inventory_path: Path,
    required_fields: tuple[str, ...],
    list_fields: set[str],
) -> dict[str, Any] | None:
    if not inventory_path.exists():
        return None
    try:
        import yaml

        payload = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if any(field_name not in payload for field_name in required_fields):
        return None
    if any(field_name in payload and not isinstance(payload.get(field_name), list) for field_name in list_fields):
        return None
    return payload


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
        if not expected_states:
            expected_state = _expected_precondition_state(case)
            expected_states = {expected_state} if expected_state is not None else set()
        if not expected_states or actual_state is None or actual_state in expected_states:
            continue
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_state_mismatch",
                "Workflow setup state derived from operation-inventory.yaml does not satisfy the case precondition.",
                source_ref=case_ref,
                details={
                    "expected_state": _single_or_sorted_state(expected_states),
                    "actual_state": actual_state,
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


def _entity_inventory_specs(entity_inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for item in entity_inventory.get("entities", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        specs[name] = item
    return specs


def _entity_operation_inventory_specs(operation_inventory: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    specs: dict[tuple[str, str], dict[str, Any]] = {}
    for item in operation_inventory.get("entity_operations", []):
        if not isinstance(item, dict):
            continue
        entity_name = str(item.get("entity") or "").strip()
        operation_name = str(item.get("operation") or "").strip()
        if not entity_name or not operation_name:
            continue
        specs[(entity_name, operation_name)] = item
    return specs


def _route_inventory_specs(operation_inventory: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    specs: dict[tuple[str, str], dict[str, Any]] = {}
    for item in operation_inventory.get("routes", []):
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "").strip().upper()
        path = str(item.get("path") or "").strip()
        if not method or not path:
            continue
        specs[_route_inventory_key(method, path)] = item
    return specs


def _db_verification_inventory_specs(operation_inventory: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    specs: dict[tuple[str, str], dict[str, Any]] = {}
    for item in operation_inventory.get("db_verifications", []):
        if not isinstance(item, dict):
            continue
        entity_name = str(item.get("entity") or "").strip()
        operation_name = str(item.get("operation") or "").strip()
        if not entity_name or not operation_name:
            continue
        specs[(entity_name, operation_name)] = item
    return specs


def _infer_setup_state_from_inventory(
    setup_steps: list[AuthoringSetupStep],
    operation_specs: dict[tuple[str, str], dict[str, Any]],
    *,
    route_entity: str | None = None,
) -> str | None:
    state: str | None = None
    for step in setup_steps:
        entity_name = step.use_entity.strip()
        if route_entity is not None and entity_name != route_entity:
            continue
        operation_spec = operation_specs.get((step.use_entity.strip(), step.operation.strip()))
        if operation_spec is None:
            continue
        state = _normalized_inventory_state(operation_spec.get("effect_state")) or state
    return state


def _normalized_scoped_by_fields(value: Any) -> list[str]:
    if isinstance(value, list):
        return [field_name for item in value if (field_name := str(item or "").strip())]
    field_name = str(value or "").strip()
    return [field_name] if field_name else []


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item_text for item in value if (item_text := str(item or "").strip())]


def _scope_matches_entity_identity(
    *,
    scoped_by: list[str],
    id_field: str,
    key_fields: list[str],
) -> bool:
    scoped_set = set(scoped_by)
    identity_fields = set(key_fields)
    if id_field:
        identity_fields.add(id_field)
    return bool(identity_fields) and scoped_set.issubset(identity_fields)


def _infer_route_entity(path: str, entity_specs: dict[str, dict[str, Any]]) -> str | None:
    matches: list[str] = []
    for entity_name, entity_spec in entity_specs.items():
        id_field = str(entity_spec.get("id_field") or "").strip()
        if id_field and _path_contains_placeholder(path, id_field):
            matches.append(entity_name)
    if len(matches) == 1:
        return matches[0]
    return None


def _path_contains_placeholder(path: str, placeholder_name: str) -> bool:
    for match in _ROUTE_PLACEHOLDER_PATTERN.finditer(path):
        if match.group(0).strip("{} ").strip() == placeholder_name:
            return True
    return False


def _route_inventory_key(method: Any, path: Any) -> tuple[str, str]:
    return (str(method or "").strip().upper(), _route_path_shape(str(path or "").strip()))


def _route_path_shape(path: str) -> str:
    return _ROUTE_PLACEHOLDER_PATTERN.sub("{{*}}", path.strip())


def _is_declared_failure_status(expected_status: Any, failure_statuses: set[int]) -> bool:
    return isinstance(expected_status, int) and not (200 <= expected_status < 300) and expected_status in failure_statuses


def _normalized_inventory_states(value: Any) -> set[str]:
    if isinstance(value, list):
        return {
            normalized
            for item in value
            if (normalized := _normalized_inventory_state(item)) is not None
        }
    normalized = _normalized_inventory_state(value)
    return set() if normalized is None else {normalized}


def _single_or_sorted_state(states: set[str]) -> str | list[str]:
    if len(states) == 1:
        return next(iter(states))
    return sorted(states)


def _has_explicit_same_state_contract(route_spec: dict[str, Any]) -> bool:
    return (
        _normalized_inventory_state(route_spec.get("target_state")) is not None
        and str(route_spec.get("same_state_behavior") or "").strip() != ""
        and _maybe_int(route_spec.get("same_state_status")) is not None
        and _has_same_state_evidence(route_spec.get("same_state_evidence"))
    )


def _has_same_state_evidence(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(isinstance(item, str) and item.strip() for item in value)
    return False
