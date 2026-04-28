"""Shared helpers for the authoring-plan compiler."""

from __future__ import annotations

import re
from typing import Any

from tools.generation.domain.models import PlannedRouteIntent

from .models import AuthoringCase, AuthoringEntityOperation, AuthoringPlan, AuthoringStateChange

_PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")
_VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _build_route_intent(execute: Any) -> PlannedRouteIntent | None:
    if execute is None or execute.route is None:
        return None
    return PlannedRouteIntent(
        http_method=execute.route.method.upper(),
        endpoint_path=execute.route.path,
    )


def _merge_default_headers(authoring_plan: AuthoringPlan, authored_headers: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(authoring_plan.defaults.headers)
    merged.update(dict(authored_headers or {}))
    return merged


def _api_expected_outcomes(oracle: Any) -> list[str]:
    if oracle is None:
        return []
    outcomes: list[str] = []
    if oracle.status_code is not None:
        outcomes.append(f"HTTP {oracle.status_code}")
    outcomes.extend(str(item) for item in oracle.business_checks)
    return outcomes


def _capture_targets(capture_rules: list[str]) -> set[str]:
    targets: set[str] = set()
    for rule in capture_rules:
        if "->" not in rule:
            continue
        _, variable_name = rule.split("->", 1)
        normalized = variable_name.strip()
        if normalized:
            targets.add(normalized)
    return targets


def _declared_variable_names(authoring_plan: AuthoringPlan, case: AuthoringCase) -> set[str]:
    return _scenario_variable_names(authoring_plan.defaults.scenario_variables) | _scenario_variable_names(
        case.scenario_variables
    )


def _scenario_variable_names(definitions: list[str]) -> set[str]:
    variable_names: set[str] = set()
    for definition in definitions:
        if not isinstance(definition, str) or "=" not in definition:
            continue
        variable_name = definition.split("=", 1)[0].strip().strip("`")
        if variable_name and _VARIABLE_NAME_PATTERN.fullmatch(variable_name):
            variable_names.add(variable_name)
    return variable_names


def _extract_placeholders(value: Any) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, str):
        return set()
    return {match.group(1).strip() for match in _PLACEHOLDER_PATTERN.finditer(value)}


def _extract_placeholders_from_value(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return _extract_placeholders(value)
    if isinstance(value, dict):
        placeholders: set[str] = set()
        for nested_value in value.values():
            placeholders.update(_extract_placeholders_from_value(nested_value))
        return placeholders
    if isinstance(value, (list, tuple, set)):
        placeholders: set[str] = set()
        for nested_value in value:
            placeholders.update(_extract_placeholders_from_value(nested_value))
        return placeholders
    return set()


def _operation_uses_placeholder(operation: AuthoringEntityOperation, variable_name: str) -> bool:
    placeholders: set[str] = set()
    if operation.route is not None:
        placeholders.update(_extract_placeholders(operation.route.path))
    placeholders.update(_extract_placeholders_from_value(operation.request_headers))
    placeholders.update(_extract_placeholders_from_value(operation.request_params))
    placeholders.update(_extract_placeholders_from_value(operation.request_body))
    placeholders.update(_extract_placeholders(operation.sql))
    placeholders.update(_extract_placeholders_from_value(operation.params))
    return variable_name in placeholders


def _requires_persistence(state_change: str) -> bool:
    parsed = AuthoringStateChange.from_raw(state_change)
    if parsed is None:
        return False
    return parsed.requires_persistence


def _authoring_defaults_metadata(authoring_plan: AuthoringPlan) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if authoring_plan.defaults.environment.strip():
        metadata["default_environment"] = authoring_plan.defaults.environment.strip()
    if authoring_plan.defaults.actor.strip():
        metadata["default_actor"] = authoring_plan.defaults.actor.strip()
    if authoring_plan.defaults.auth.strip():
        metadata["default_auth"] = authoring_plan.defaults.auth.strip()
    return metadata


def _persistance_template_mixes_primary_key_and_entity_id(
    *,
    sql: str,
    expected_outcomes: list[str],
    entity_id_field: str,
) -> bool:
    normalized_id_field = entity_id_field.strip()
    if not normalized_id_field or normalized_id_field == "id":
        return False
    sql_pattern = re.compile(
        rf'(?i)(?:\b\w+\.)?"?id"?\s*=\s*:{re.escape(normalized_id_field)}\b'
    )
    if sql_pattern.search(sql) is None:
        return False
    expected_pattern = re.compile(
        rf"`{re.escape(normalized_id_field)}`\s*=\s*`{{{{\s*{re.escape(normalized_id_field)}\s*}}}}`"
    )
    return any(expected_pattern.search(outcome) for outcome in expected_outcomes)


def _numeric_path_parts(path: str) -> list[str]:
    normalized = path.replace("[", ".").replace("]", "")
    return [part for part in normalized.split(".") if part]


def _normalize_case_field_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")
