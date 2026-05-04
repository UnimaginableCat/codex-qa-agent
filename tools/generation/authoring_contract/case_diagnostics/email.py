"""Email normalization diagnostics for authored expectations."""

from __future__ import annotations

from typing import Any

from tools.generation.domain.models import (
    DiagnosticSeverity,
    GenerationDiagnostic,
    PlannedDbVerification,
    PlannedWorkflowStep,
)

from ..diagnostics import authoring_diagnostic
from ..helpers import _extract_placeholders, _normalize_case_field_name, _numeric_path_parts
from ..models import AuthoringCase, AuthoringPlan
from .variables import (
    _EXPECTATION_COMPARISON_RE,
    _exact_placeholder_name,
    _scenario_variable_definitions,
    _strip_wrapping_quotes,
    _variable_guarantees_lowercase,
)


def _normalized_email_expectation_diagnostics(
    *,
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    setup_steps: list[PlannedWorkflowStep],
    persisted_verification: PlannedDbVerification | None,
) -> list[GenerationDiagnostic]:
    request_email_variables = set()
    if case.execute is not None:
        request_email_variables.update(_collect_email_placeholders(case.execute.body))
    for step in setup_steps:
        if step.step_type.strip().lower() != "api":
            continue
        request_email_variables.update(_collect_email_placeholders(step.request_body))
    if not request_email_variables:
        return []

    variable_definitions = _scenario_variable_definitions(authoring_plan, case)
    risky_bindings: list[dict[str, Any]] = []
    for expectation in [] if case.oracle is None else case.oracle.business_checks:
        binding = _email_expectation_binding(expectation)
        if binding is None:
            continue
        variable_name, field_path = binding
        if variable_name not in request_email_variables:
            continue
        if _variable_guarantees_lowercase(variable_name, variable_definitions):
            continue
        risky_bindings.append(
            {
                "scope": "api",
                "field": field_path,
                "variable": variable_name,
                "rule": expectation,
            }
        )
    if persisted_verification is not None:
        for expectation in persisted_verification.expected_outcomes:
            binding = _email_expectation_binding(expectation)
            if binding is None:
                continue
            variable_name, field_path = binding
            if variable_name not in request_email_variables:
                continue
            if _variable_guarantees_lowercase(variable_name, variable_definitions):
                continue
            risky_bindings.append(
                {
                    "scope": "db",
                    "field": field_path,
                    "variable": variable_name,
                    "rule": expectation,
                }
            )
    if not risky_bindings:
        return []

    variables = sorted({str(item["variable"]) for item in risky_bindings})
    return [
        authoring_diagnostic(
            "authoring_expected_value_case_ambiguous",
            (
                "Expected email checks reuse the same placeholder as request input, but that variable is not "
                "guaranteed lowercase. If the system normalizes email casing, author separate submitted and expected "
                "variables, for example `submitted_email` plus `expected_email = derived:submitted_email|lower`."
            ),
            severity=DiagnosticSeverity.WARNING,
            source_ref=case_ref,
            details={
                "variables": variables,
                "bindings": risky_bindings,
            },
        )
    ]


def _collect_email_placeholders(value: Any, *, path: str = "") -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return set(_extract_placeholders(value)) if _path_targets_email(path) else set()
    if isinstance(value, dict):
        names: set[str] = set()
        for key, nested_value in value.items():
            nested_path = f"{path}.{key}" if path else str(key)
            names.update(_collect_email_placeholders(nested_value, path=nested_path))
        return names
    if isinstance(value, (list, tuple, set)):
        names: set[str] = set()
        for index, nested_value in enumerate(value):
            nested_path = f"{path}[{index}]" if path else f"[{index}]"
            names.update(_collect_email_placeholders(nested_value, path=nested_path))
        return names
    return set()


def _path_targets_email(path: str) -> bool:
    if not path.strip():
        return False
    last_part = _numeric_path_parts(path)[-1] if _numeric_path_parts(path) else path
    normalized = _normalize_case_field_name(last_part)
    return "email" in normalized


def _email_expectation_binding(expectation: str) -> tuple[str, str] | None:
    match = _EXPECTATION_COMPARISON_RE.fullmatch(expectation.strip())
    if match is None:
        return None
    field_path = _strip_wrapping_quotes(match.group("left").strip()).strip()
    if not _path_targets_email(field_path):
        return None
    placeholder_name = _exact_placeholder_name(match.group("right"))
    if placeholder_name is None:
        return None
    return placeholder_name, field_path
