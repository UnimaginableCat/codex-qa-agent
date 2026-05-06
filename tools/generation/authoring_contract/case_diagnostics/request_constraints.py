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
    diagnostics = _request_body_evidence_diagnostics(authoring_plan, case, case_ref)

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
        return diagnostics
    diagnostics.append(
        authoring_diagnostic(
            "authoring_request_constraint_unsatisfied",
            (
                "Authored request body does not satisfy a declarative request constraint from the operation contract. "
                "For numeric string fields, use a numeric literal or `numeric_suffix = generated:numeric_suffix`."
            ),
            source_ref=case_ref,
            details={"bindings": risky_bindings},
        )
    )
    return diagnostics


def _request_body_evidence_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
) -> list[GenerationDiagnostic]:
    if case.execute is None or case.execute.route is None or case.execute.body is None:
        return []
    method = case.execute.route.method.strip().upper()
    if method not in {"POST", "PUT", "PATCH"}:
        return []
    if not _request_body_evidence_required(authoring_plan, case):
        return []
    if _case_has_request_body_evidence(authoring_plan, case):
        return []
    return [
        authoring_diagnostic(
            "authoring_request_body_evidence_required",
            (
                "Case authors a request body for an action-like route without serializer/schema evidence. "
                "This can render a runnable scenario with the wrong payload shape, causing HTTP 400 before "
                "the intended behavior is tested."
            ),
            source_ref=case_ref,
            details={
                "method": method,
                "path": case.execute.route.path,
                "state_change": case.state_change,
                "suggestion": (
                    "Add request_body_evidence/request_body_schema/serializer_evidence to the matching entity "
                    "operation or case metadata, with source evidence for the required payload shape."
                ),
            },
        )
    ]


def _request_body_evidence_required(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    if _metadata_contract_bool(authoring_plan.metadata, "request_body", "evidence_required"):
        return True
    if _metadata_contract_bool(case.metadata, "request_body", "evidence_required"):
        return True
    state_change = str(case.state_change or "").strip().lower()
    success_status = case.oracle is not None and case.oracle.status_code is not None and 200 <= case.oracle.status_code < 300
    return state_change in {"read_only", "readonly"} and success_status


def _metadata_contract_bool(metadata: dict[str, Any], section: str, key: str) -> bool:
    contracts = metadata.get("contracts")
    if not isinstance(contracts, dict):
        return False
    contract_section = contracts.get(section)
    if not isinstance(contract_section, dict):
        return False
    return str(contract_section.get(key) or "").strip().lower() in {"1", "true", "yes", "required"}


def _case_has_request_body_evidence(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    if _value_has_evidence(case.metadata.get("request_body_evidence")):
        return True
    if _value_has_evidence(case.metadata.get("request_body_schema")):
        return True
    if _value_has_evidence(case.metadata.get("serializer_evidence")):
        return True
    operation = _matching_execute_operation(authoring_plan, case)
    if operation is None:
        return False
    if _value_has_evidence(operation.request_body_evidence):
        return True
    return bool(operation.request_constraints)


def _matching_execute_operation(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
):
    if case.execute is None or case.execute.route is None:
        return None
    method = case.execute.route.method.strip().upper()
    path = case.execute.route.path.strip()
    for entity_spec in authoring_plan.entities.values():
        for operation in entity_spec.operations.values():
            if operation.route is None:
                continue
            if operation.route.method.strip().upper() == method and operation.route.path.strip() == path:
                return operation
    return None


def _value_has_evidence(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list)):
        return bool(value)
    return False


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
