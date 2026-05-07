"""Request-constraint diagnostics for authored API payloads."""

from __future__ import annotations

import re
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
        return _request_body_schema_source_diagnostics(
            authoring_plan,
            case,
            case_ref,
            method,
        ) + _request_body_field_evidence_diagnostics(authoring_plan, case, case_ref, method)
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


def _request_body_schema_source_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    method: str,
) -> list[GenerationDiagnostic]:
    evidence_values = _request_body_evidence_values(authoring_plan, case)
    if any(_evidence_value_has_schema_source(value) for value in evidence_values):
        return []
    return [
        authoring_diagnostic(
            "authoring_request_body_schema_source_required",
            (
                "Case has request body evidence for an action-like request body, but the evidence is not tied "
                "to a serializer, schema, request parser, or OpenAPI/request-body contract. Field lists from "
                "service notes or arbitrary metadata can still describe the wrong payload shape."
            ),
            source_ref=case_ref,
            details={
                "method": method,
                "path": "" if case.execute is None or case.execute.route is None else case.execute.route.path,
                "suggestion": (
                    "Use explicit schema-capable evidence such as `source_role: request_schema` or an inline "
                    "schema-shaped `schema`/`properties`/`request_body_schema` contract. File paths and service "
                    "names are not treated as schema proof."
                ),
            },
        )
    ]


def _request_body_field_evidence_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    method: str,
) -> list[GenerationDiagnostic]:
    body_fields = _top_level_request_body_fields(case.execute.body if case.execute is not None else None)
    if not body_fields:
        return []
    evidence_values = _request_body_evidence_values(authoring_plan, case)
    field_evidence = _request_body_evidence_fields(evidence_values)
    constraints = _request_constraints_for_execute(authoring_plan, case)
    field_evidence.update(
        str(item.get("field") or "").split(".", 1)[0].strip().lower()
        for item in constraints
        if str(item.get("field") or "").strip()
    )
    missing_fields = sorted(field for field in body_fields if field not in field_evidence)
    if not missing_fields:
        return []
    return [
        authoring_diagnostic(
            "authoring_request_body_field_evidence_required",
            (
                "Case has serializer/schema evidence for an action-like request body, but the evidence does "
                "not name every authored top-level body field. Generic evidence such as 'uses serializer' can "
                "still allow the wrong payload shape and cause HTTP 400 before the intended behavior is tested."
            ),
            source_ref=case_ref,
            details={
                "method": method,
                "path": "" if case.execute is None or case.execute.route is None else case.execute.route.path,
                "body_fields": sorted(body_fields),
                "evidence_fields": sorted(field_evidence),
                "missing_fields": missing_fields,
                "suggestion": (
                    "Make request_body_evidence/request_body_schema field-specific, for example with "
                    "`required: [...]`, `fields: [...]`, or request_constraints entries for each authored body key."
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
    if any(_value_has_evidence(value) for value in _case_request_body_evidence_values(case)):
        return True
    operation = _matching_execute_operation(authoring_plan, case)
    if operation is None:
        return False
    if _value_has_evidence(operation.request_body_evidence):
        return True
    return bool(operation.request_constraints)


def _request_body_evidence_values(authoring_plan: AuthoringPlan, case: AuthoringCase) -> list[Any]:
    values = list(_case_request_body_evidence_values(case))
    operation = _matching_execute_operation(authoring_plan, case)
    if operation is not None:
        values.append(operation.request_body_evidence)
        values.extend(operation.request_constraints)
    return [value for value in values if _value_has_evidence(value)]


def _case_request_body_evidence_values(case: AuthoringCase) -> list[Any]:
    return [
        case.metadata.get("request_body_evidence"),
        case.metadata.get("request_body_schema"),
        case.metadata.get("serializer_evidence"),
    ]


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


def _top_level_request_body_fields(body: Any) -> set[str]:
    if not isinstance(body, dict):
        return set()
    return {str(key).strip().lower() for key in body if str(key).strip()}


def _request_body_evidence_fields(values: list[Any]) -> set[str]:
    fields: set[str] = set()
    for value in values:
        fields.update(_fields_from_evidence_value(value))
    return fields


def _fields_from_evidence_value(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return set(_identifier_tokens(value))
    if isinstance(value, dict):
        fields: set[str] = set()
        for key, nested in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in {
                "field",
                "fields",
                "required",
                "required_fields",
                "body_fields",
                "request_fields",
                "properties",
            }:
                fields.update(_field_names_from_declared_value(nested))
            elif isinstance(nested, (dict, list, tuple, set)):
                fields.update(_fields_from_evidence_value(nested))
        return fields
    if isinstance(value, (list, tuple, set)):
        fields: set[str] = set()
        for item in value:
            fields.update(_fields_from_evidence_value(item))
        return fields
    return set()


def _evidence_value_has_schema_source(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return False
    if isinstance(value, dict):
        if _dict_has_schema_source(value):
            return True
        return any(
            _evidence_value_has_schema_source(nested)
            for nested in value.values()
            if isinstance(nested, (dict, list, tuple, set))
        )
    if isinstance(value, (list, tuple, set)):
        return any(_evidence_value_has_schema_source(item) for item in value)
    return False


def _dict_has_schema_source(value: dict[Any, Any]) -> bool:
    normalized_keys = {str(key).strip().lower() for key in value}
    if normalized_keys.intersection({"properties", "request_body_schema", "body_schema", "schema"}):
        return True
    for key, nested in value.items():
        normalized_key = str(key).strip().lower()
        if normalized_key in {
            "source_role",
            "role",
            "source_type",
            "evidence_role",
            "kind",
        } and _value_is_schema_role(nested):
            return True
    return False


def _value_is_schema_role(value: Any) -> bool:
    if isinstance(value, (list, tuple, set)):
        return any(_value_is_schema_role(item) for item in value)
    if isinstance(value, dict):
        return False
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in {
            "request_schema",
            "body_schema",
            "request_body_schema",
            "request_body",
            "request_serializer",
            "input_serializer",
            "serializer",
            "schema",
            "openapi",
            "request_parser",
            "parser",
    }


def _field_names_from_declared_value(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.split(".", 1)[0].strip().lower()} if value.strip() else set()
    if isinstance(value, dict):
        return {str(key).split(".", 1)[0].strip().lower() for key in value if str(key).strip()}
    if isinstance(value, (list, tuple, set)):
        fields: set[str] = set()
        for item in value:
            fields.update(_field_names_from_declared_value(item))
        return fields
    return set()


def _identifier_tokens(value: str) -> set[str]:
    return {match.group(0).lower() for match in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", value)}


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
