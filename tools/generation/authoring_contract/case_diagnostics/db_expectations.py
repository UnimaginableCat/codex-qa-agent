"""DB expectation diagnostics for authored persisted-state checks."""

from __future__ import annotations

from tools.generation.domain.models import GenerationDiagnostic, PlannedDbVerification

from ..diagnostics import authoring_diagnostic
from ..helpers import _normalize_case_field_name, _numeric_path_parts
from ..models import AuthoringCase, AuthoringPlan
from .variables import (
    _EXPECTATION_COMPARISON_RE,
    _exact_placeholder_name,
    _scenario_variable_definitions,
    _strip_wrapping_quotes,
    _variable_guarantees_numeric,
)


def _db_string_placeholder_quoting_diagnostics(
    *,
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    persisted_verification: PlannedDbVerification | None,
) -> list[GenerationDiagnostic]:
    if persisted_verification is None:
        return []
    column_types = _persisted_state_column_types(authoring_plan, case)
    if not column_types:
        return []
    variable_definitions = _scenario_variable_definitions(authoring_plan, case)
    risky_bindings: list[dict[str, object]] = []
    for expectation in persisted_verification.expected_outcomes:
        binding = _db_string_placeholder_binding(expectation, column_types)
        if binding is None:
            continue
        variable_name, field_path = binding
        if not _variable_guarantees_numeric(variable_name, variable_definitions):
            continue
        risky_bindings.append({"field": field_path, "variable": variable_name, "rule": expectation})
    if not risky_bindings:
        return []
    return [
        authoring_diagnostic(
            "authoring_db_string_placeholder_requires_quotes",
            (
                "DB expectation compares a string-like column to a numeric generated placeholder. Quote the placeholder "
                "inside the expectation, for example ``subject` = `\"{{telegram_subject}}\"``."
            ),
            source_ref=case_ref,
            details={"bindings": risky_bindings},
        )
    ]


def _db_string_placeholder_binding(
    expectation: str,
    column_types: dict[str, str],
) -> tuple[str, str] | None:
    match = _EXPECTATION_COMPARISON_RE.fullmatch(expectation.strip())
    if match is None:
        return None
    field_path = _strip_wrapping_quotes(match.group("left").strip()).strip()
    if not _path_targets_string_db_column(field_path, column_types):
        return None
    right = match.group("right").strip()
    if _rhs_quotes_placeholder_as_string(right):
        return None
    placeholder_name = _exact_placeholder_name(right)
    if placeholder_name is None:
        return None
    return placeholder_name, field_path


def _path_targets_string_db_column(path: str, column_types: dict[str, str]) -> bool:
    if not path.strip():
        return False
    last_part = _numeric_path_parts(path)[-1] if _numeric_path_parts(path) else path
    normalized = _normalize_case_field_name(last_part)
    normalized_types = {
        _normalize_case_field_name(str(key)): str(value).strip().lower()
        for key, value in column_types.items()
    }
    return normalized_types.get(normalized) in {"str", "string", "text", "varchar", "uuid"}


def _rhs_quotes_placeholder_as_string(value: str) -> bool:
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == "`":
        normalized = normalized[1:-1].strip()
    if len(normalized) < 2 or normalized[0] != normalized[-1] or normalized[0] not in {'"', "'"}:
        return False
    return _exact_placeholder_name(normalized[1:-1]) is not None


def _persisted_state_column_types(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
) -> dict[str, str]:
    if case.oracle is None or case.oracle.persisted_state is None:
        return {}
    state_ref = case.oracle.persisted_state
    entity_spec = authoring_plan.entities.get(state_ref.entity.strip())
    if entity_spec is None:
        return {}
    operation = entity_spec.operations.get(state_ref.operation.strip())
    if operation is None:
        return {}
    return dict(operation.column_types)
