"""Indexes and normalization helpers for staged inventory diagnostics."""

from __future__ import annotations

import re
from typing import Any

from ..case_diagnostics.lifecycle import _normalized_inventory_state
from ..models import AuthoringSetupStep, _maybe_int

_ROUTE_PLACEHOLDER_PATTERN = re.compile(r"{{\s*[^{}]+?\s*}}")


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
