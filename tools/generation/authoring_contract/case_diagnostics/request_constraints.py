"""Request-constraint diagnostics for authored API payloads."""

from __future__ import annotations

from typing import Any

from tools.generation.domain.models import GenerationDiagnostic, PlannedWorkflowStep
from tools.scenario_runner.domain.models import ScenarioVariableDefinition

from ..diagnostics import authoring_diagnostic
from ..models import AuthoringCase, AuthoringPlan
from .variables import (
    _dict_list,
    _get_path_value,
    _scenario_variable_definitions,
    _value_guarantees_numeric,
)


def _request_constraint_diagnostics(
    *,
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    setup_steps: list[PlannedWorkflowStep],
) -> list[GenerationDiagnostic]:
    variable_definitions = _scenario_variable_definitions(authoring_plan, case)
    risky_bindings: list[dict[str, Any]] = []

    for scope, body, constraints in _iter_constrained_api_request_bodies(authoring_plan, case, setup_steps):
        for constraint in constraints:
            if not _request_constraint_applies(body, constraint):
                continue
            field_path = str(constraint.get("field") or "").strip()
            value = _get_path_value(body, field_path)
            if _constraint_value_satisfies(value, constraint, variable_definitions):
                continue
            risky_bindings.append(
                {
                    "scope": scope,
                    "field": field_path,
                    "format": str(constraint.get("format") or "").strip(),
                    "value": value,
                    "when": dict(constraint.get("when") or {}) if isinstance(constraint.get("when"), dict) else {},
                }
            )

    if not risky_bindings:
        return []
    return [
        authoring_diagnostic(
            "authoring_request_constraint_unsatisfied",
            (
                "Authored request body does not satisfy a declarative request constraint from the operation contract. "
                "For numeric string fields, use a numeric literal or `numeric_suffix = generated:numeric_suffix`."
            ),
            source_ref=case_ref,
            details={"bindings": risky_bindings},
        )
    ]


def _iter_constrained_api_request_bodies(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    setup_steps: list[PlannedWorkflowStep],
) -> list[tuple[str, Any, list[dict[str, Any]]]]:
    bodies: list[tuple[str, Any, list[dict[str, Any]]]] = []
    for step in setup_steps:
        if step.step_type.strip().lower() != "api":
            continue
        constraints = _dict_list(step.metadata.get("request_constraints"))
        if constraints:
            bodies.append((step.title or "setup", step.request_body, constraints))
    if case.execute is not None:
        constraints = _request_constraints_for_execute(authoring_plan, case)
        if constraints:
            bodies.append(("execute", case.execute.body, constraints))
    return bodies


def _request_constraints_for_execute(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
) -> list[dict[str, Any]]:
    if case.execute is None or case.execute.route is None:
        return []
    method = case.execute.route.method.strip().upper()
    path = case.execute.route.path.strip()
    for entity_spec in authoring_plan.entities.values():
        for operation in entity_spec.operations.values():
            if operation.route is None:
                continue
            if operation.route.method.strip().upper() == method and operation.route.path.strip() == path:
                return [dict(item) for item in operation.request_constraints]
    return []


def _request_constraint_applies(body: Any, constraint: dict[str, Any]) -> bool:
    if not isinstance(body, dict):
        return False
    field_path = str(constraint.get("field") or "").strip()
    if not field_path:
        return False
    condition = constraint.get("when")
    if isinstance(condition, dict):
        for key, expected_value in condition.items():
            actual_value = _get_path_value(body, str(key))
            if str(actual_value).strip().lower() != str(expected_value).strip().lower():
                return False
    return True


def _constraint_value_satisfies(
    value: Any,
    constraint: dict[str, Any],
    definitions: dict[str, ScenarioVariableDefinition],
) -> bool:
    constraint_format = str(constraint.get("format") or "").strip().lower()
    if constraint_format in {"numeric_string", "digits", "digits_only"}:
        return _value_guarantees_numeric(value, definitions)
    return True
