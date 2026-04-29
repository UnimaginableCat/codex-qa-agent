"""Case-level diagnostics for compact authoring plans."""

from __future__ import annotations

import re
from typing import Any

from tools.generation.domain.models import (
    DiagnosticSeverity,
    GenerationDiagnostic,
    PlannedDbVerification,
    PlannedWorkflowStep,
)
from tools.scenario_runner.domain.models import ScenarioVariableDefinition, ScenarioVariableSource
from tools.scenario_runner.parsing.variables.validation import build_variable_definition

from .diagnostics import authoring_diagnostic
from .helpers import (
    _PLACEHOLDER_PATTERN,
    _VARIABLE_NAME_PATTERN,
    _extract_placeholders,
    _normalize_case_field_name,
    _numeric_path_parts,
)
from .models import AuthoringCase, AuthoringPlan, AuthoringSetupStep, _maybe_int

_EXACT_PLACEHOLDER_PATTERN = re.compile(r"^\s*{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}\s*$")
_EXPECTATION_COMPARISON_RE = re.compile(
    r"^\s*(?:response\s+)?(?P<left>.+?)\s*(?P<operator>=|!=)\s*(?P<right>.+?)\s*$",
    re.IGNORECASE,
)
_STRING_LENGTH_OVERFLOW_PATTERN = re.compile(
    r"\b(?:longer than|more than|over|above)\s+(\d+)\s+characters?\b",
    re.IGNORECASE,
)
_NUMERIC_GREATER_THAN_PATTERN = re.compile(
    r"\b(?P<field>[A-Za-z_][A-Za-z0-9_-]*)\s+(?:greater than|more than|over|above)\s+(?P<threshold>-?\d+)\b",
    re.IGNORECASE,
)
_NEGATIVE_FIELD_PATTERN = re.compile(
    r"\bnegative\s+(?P<field>[A-Za-z_][A-Za-z0-9_-]*)\b",
    re.IGNORECASE,
)
_ZERO_FIELD_PATTERN = re.compile(
    r"\bzero\s+(?P<field>[A-Za-z_][A-Za-z0-9_-]*)\b",
    re.IGNORECASE,
)
_SUPPORTED_SAME_STATE_BEHAVIORS = {"reject", "idempotent_success"}


def _boundary_case_diagnostics(
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if case.execute is None:
        return diagnostics
    body = case.execute.body
    params = case.execute.params
    case_text = " ".join(part.strip() for part in (case.title, case.objective) if part and part.strip())
    if not case_text:
        return diagnostics
    diagnostics.extend(_string_boundary_diagnostics(body, case_text, case_ref, index=index))
    diagnostics.extend(_numeric_boundary_diagnostics(params, body, case_text, case_ref, index=index))
    return diagnostics


def _string_length_overflow_threshold(value: str) -> int | None:
    match = _STRING_LENGTH_OVERFLOW_PATTERN.search(value)
    if match is None:
        return None
    return int(match.group(1))


def _collect_string_literals(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        collected: list[str] = []
        for nested_value in value.values():
            collected.extend(_collect_string_literals(nested_value))
        return collected
    if isinstance(value, (list, tuple, set)):
        collected: list[str] = []
        for nested_value in value:
            collected.extend(_collect_string_literals(nested_value))
        return collected
    return []


def _string_boundary_diagnostics(
    body: Any,
    case_text: str,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    threshold = _string_length_overflow_threshold(case_text)
    if threshold is None:
        return []
    string_lengths = [
        len(value)
        for value in _collect_string_literals(body)
        if value and not _extract_placeholders(value)
    ]
    if not string_lengths:
        return []
    actual_max_length = max(string_lengths)
    if actual_max_length > threshold:
        return []
    return [
        authoring_diagnostic(
            "authoring_case_boundary_mismatch",
            (
                "Case text indicates a string-overflow boundary, but the authored request body does not exceed it. "
                "Use a literal longer than the stated threshold."
            ),
            source_ref=case_ref,
            details={
                "case_index": index,
                "threshold": threshold,
                "actual_max_length": actual_max_length,
            },
        )
    ]


def _numeric_boundary_diagnostics(
    params: dict[str, Any],
    body: Any,
    case_text: str,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    numeric_literals = [
        (path, value)
        for path, value in _collect_numeric_literals({"params": params, "body": body})
        if not _numeric_path_has_placeholder(path)
    ]
    if not numeric_literals:
        return diagnostics

    for match in _NUMERIC_GREATER_THAN_PATTERN.finditer(case_text):
        field_name = match.group("field")
        threshold = int(match.group("threshold"))
        diagnostics.extend(
            _numeric_case_boundary_mismatch_diagnostics(
                numeric_literals,
                field_name=field_name,
                case_ref=case_ref,
                case_index=index,
                predicate=lambda value, limit=threshold: value > limit,
                message=(
                    "Case text indicates a numeric overflow boundary, but the authored value does not exceed it. "
                    "Use a literal greater than the stated threshold."
                ),
                details={"threshold": threshold, "field": field_name, "rule": "greater_than"},
            )
        )

    for match in _NEGATIVE_FIELD_PATTERN.finditer(case_text):
        field_name = match.group("field")
        diagnostics.extend(
            _numeric_case_boundary_mismatch_diagnostics(
                numeric_literals,
                field_name=field_name,
                case_ref=case_ref,
                case_index=index,
                predicate=lambda value: value < 0,
                message=(
                    "Case text indicates a negative numeric boundary, but the authored value is not negative. "
                    "Use a negative literal for the stated field."
                ),
                details={"field": field_name, "rule": "negative"},
            )
        )

    for match in _ZERO_FIELD_PATTERN.finditer(case_text):
        field_name = match.group("field")
        diagnostics.extend(
            _numeric_case_boundary_mismatch_diagnostics(
                numeric_literals,
                field_name=field_name,
                case_ref=case_ref,
                case_index=index,
                predicate=lambda value: value == 0,
                message=(
                    "Case text indicates a zero-value boundary, but the authored value is not zero. "
                    "Use zero for the stated field."
                ),
                details={"field": field_name, "rule": "zero"},
            )
        )

    return diagnostics


def _numeric_case_boundary_mismatch_diagnostics(
    numeric_literals: list[tuple[str, int | float]],
    *,
    field_name: str,
    case_ref: str,
    case_index: int,
    predicate: Any,
    message: str,
    details: dict[str, Any],
) -> list[GenerationDiagnostic]:
    relevant_literals = _relevant_numeric_literals(numeric_literals, field_name)
    if not relevant_literals:
        return [
            authoring_diagnostic(
                "authoring_case_boundary_mismatch",
                "Case text indicates a numeric boundary, but no authored numeric literal was found for the stated field.",
                source_ref=case_ref,
                details={**details, "case_index": case_index, "actual_values": []},
            )
        ]
    if any(predicate(value) for _, value in relevant_literals):
        return []
    return [
        authoring_diagnostic(
            "authoring_case_boundary_mismatch",
            message,
            source_ref=case_ref,
            details={
                **details,
                "case_index": case_index,
                "actual_values": [value for _, value in relevant_literals],
            },
        )
    ]


def _collect_numeric_literals(value: Any, *, path: str = "") -> list[tuple[str, int | float]]:
    if value is None:
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [(path, value)]
    if isinstance(value, str):
        return []
    if isinstance(value, dict):
        collected: list[tuple[str, int | float]] = []
        for key, nested_value in value.items():
            nested_path = f"{path}.{key}" if path else str(key)
            collected.extend(_collect_numeric_literals(nested_value, path=nested_path))
        return collected
    if isinstance(value, (list, tuple, set)):
        collected: list[tuple[str, int | float]] = []
        for index, nested_value in enumerate(value):
            nested_path = f"{path}[{index}]" if path else f"[{index}]"
            collected.extend(_collect_numeric_literals(nested_value, path=nested_path))
        return collected
    return []


def _relevant_numeric_literals(
    numeric_literals: list[tuple[str, int | float]],
    field_name: str,
) -> list[tuple[str, int | float]]:
    normalized_field = _normalize_case_field_name(field_name)
    relevant = [
        (path, value)
        for path, value in numeric_literals
        if normalized_field in {_normalize_case_field_name(part) for part in _numeric_path_parts(path)}
    ]
    if relevant:
        return relevant
    return numeric_literals


def _numeric_path_has_placeholder(path: str) -> bool:
    return bool(_extract_placeholders(path))


def _workflow_setup_state_mismatch_diagnostics(
    *,
    case: AuthoringCase,
    case_ref: str,
) -> list[GenerationDiagnostic]:
    if case.kind.strip().lower() != "workflow" or not case.setup or case.execute is None or case.execute.route is None:
        return []
    actual_state = _infer_setup_state(case.setup)
    if actual_state is None:
        return []
    expected_state = _expected_precondition_state(case)
    if expected_state is None or expected_state == actual_state:
        return []
    return [
        authoring_diagnostic(
            "authoring_workflow_setup_state_mismatch",
            (
                "Workflow setup appears to leave the entity in a different lifecycle state than the case objective "
                "or execute route expects. This often produces the wrong HTTP status at execution time."
            ),
            severity=DiagnosticSeverity.WARNING,
            source_ref=case_ref,
            details={
                "expected_state": expected_state,
                "actual_state": actual_state,
                "setup_operations": [step.operation for step in case.setup],
                "route_path": case.execute.route.path,
            },
        )
    ]


def _workflow_same_state_contract_warning(
    *,
    case: AuthoringCase,
    case_ref: str,
) -> list[GenerationDiagnostic]:
    if case.kind.strip().lower() != "workflow" or not case.setup or case.execute is None or case.execute.route is None:
        return []
    actual_state = _infer_setup_state(case.setup)
    target_state = _inferred_route_target_state(case.execute.route.path)
    if actual_state is None or target_state is None or actual_state != target_state:
        return []
    return [
        authoring_diagnostic(
            "authoring_same_state_lifecycle_contract_unconfirmed",
            (
                "Workflow case appears to invoke a lifecycle command when the entity is already in the target state. "
                "Do not assume rejection or idempotent success from route names alone; confirm same-state behavior in "
                "code/tests and record it explicitly in operation-inventory.yaml."
            ),
            severity=DiagnosticSeverity.WARNING,
            source_ref=case_ref,
            details={
                "actual_state": actual_state,
                "target_state": target_state,
                "route_path": case.execute.route.path,
                "setup_operations": [step.operation for step in case.setup],
            },
        )
    ]


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
    risky_bindings: list[dict[str, Any]] = []
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


def _iter_api_request_bodies(
    case: AuthoringCase,
    setup_steps: list[PlannedWorkflowStep],
) -> list[tuple[str, Any]]:
    bodies: list[tuple[str, Any]] = []
    for step in setup_steps:
        if step.step_type.strip().lower() == "api":
            bodies.append((step.title or "setup", step.request_body))
    if case.execute is not None:
        bodies.append(("execute", case.execute.body))
    return bodies


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


def _get_path_value(value: Any, path: str) -> Any:
    current = value
    for part in [item for item in path.split(".") if item]:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _value_guarantees_numeric(
    value: Any,
    definitions: dict[str, ScenarioVariableDefinition],
    *,
    _stack: set[str] | None = None,
) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, int):
        return value >= 0
    if isinstance(value, float):
        return value.is_integer() and value >= 0
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    dependencies = _extract_placeholders(stripped)
    literal_text = _PLACEHOLDER_PATTERN.sub("", stripped).strip()
    if literal_text and not literal_text.isdigit():
        return False
    if not dependencies:
        return stripped.isdigit()
    return all(_variable_guarantees_numeric(dependency, definitions, _stack=_stack) for dependency in dependencies)


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


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _scenario_variable_definitions(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
) -> dict[str, ScenarioVariableDefinition]:
    definitions: dict[str, ScenarioVariableDefinition] = {}
    for entry in [*authoring_plan.defaults.scenario_variables, *case.scenario_variables]:
        if "=" not in entry:
            continue
        variable_name, raw_value = entry.split("=", 1)
        variable_name = variable_name.strip()
        if not variable_name or not _VARIABLE_NAME_PATTERN.fullmatch(variable_name):
            continue
        try:
            definitions[variable_name] = build_variable_definition(variable_name, raw_value.strip())
        except Exception:
            continue
    return definitions


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


def _exact_placeholder_name(value: str) -> str | None:
    normalized = _strip_wrapping_quotes(value.strip()).strip()
    match = _EXACT_PLACEHOLDER_PATTERN.fullmatch(normalized)
    return match.group(1) if match is not None else None


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        return value[1:-1]
    return value


def _variable_guarantees_lowercase(
    variable_name: str,
    definitions: dict[str, ScenarioVariableDefinition],
    *,
    _stack: set[str] | None = None,
) -> bool:
    definition = definitions.get(variable_name)
    if definition is None:
        return False
    stack = set() if _stack is None else set(_stack)
    if variable_name in stack:
        return False
    stack.add(variable_name)
    if definition.source == ScenarioVariableSource.LITERAL:
        return definition.raw_value == definition.raw_value.lower()
    if definition.source == ScenarioVariableSource.TEMPLATE:
        literal_text = _PLACEHOLDER_PATTERN.sub("", definition.raw_value)
        if literal_text != literal_text.lower():
            return False
        dependencies = _extract_placeholders(definition.raw_value)
        return all(_variable_guarantees_lowercase(dependency, definitions, _stack=stack) for dependency in dependencies)
    if definition.source == ScenarioVariableSource.DERIVED:
        guaranteed = (
            _variable_guarantees_lowercase(definition.source_name, definitions, _stack=stack)
            if definition.source_name
            else False
        )
        for transform in definition.transforms:
            normalized = transform.strip().lower()
            if normalized == "lower":
                guaranteed = True
            elif normalized == "upper":
                guaranteed = False
            elif normalized == "trim":
                continue
            else:
                return False
        return guaranteed
    if definition.source == ScenarioVariableSource.GENERATED:
        return definition.raw_value.strip().lower().endswith(":uuid")
    return False


def _variable_guarantees_numeric(
    variable_name: str,
    definitions: dict[str, ScenarioVariableDefinition],
    *,
    _stack: set[str] | None = None,
) -> bool:
    definition = definitions.get(variable_name)
    if definition is None:
        return False
    stack = set() if _stack is None else set(_stack)
    if variable_name in stack:
        return False
    stack.add(variable_name)
    if definition.source == ScenarioVariableSource.LITERAL:
        return definition.raw_value.strip().isdigit()
    if definition.source == ScenarioVariableSource.TEMPLATE:
        return _value_guarantees_numeric(definition.raw_value, definitions, _stack=stack)
    if definition.source == ScenarioVariableSource.DERIVED:
        if not definition.source_name:
            return False
        return _variable_guarantees_numeric(definition.source_name, definitions, _stack=stack)
    if definition.source == ScenarioVariableSource.GENERATED:
        generated_name = definition.raw_value.split(":", 1)[-1].strip().lower()
        return generated_name in {"numeric_suffix", "numeric_timestamp_suffix"} or generated_name.endswith("_numeric_suffix")
    return False


def _infer_setup_state(setup_steps: list[AuthoringSetupStep]) -> str | None:
    state: str | None = None
    for step in setup_steps:
        hinted_state = _operation_state_hint(step.operation)
        if hinted_state is not None:
            state = hinted_state
    return state


def _operation_state_hint(operation_name: str) -> str | None:
    normalized = operation_name.strip().lower()
    if not normalized:
        return None
    if "archive" in normalized:
        return "archived"
    if "suspend" in normalized:
        return "suspended"
    if "activate" in normalized:
        return "active"
    if "create" in normalized:
        return "active"
    return None


def _expected_precondition_state(case: AuthoringCase) -> str | None:
    route_path = "" if case.execute is None or case.execute.route is None else case.execute.route.path.strip().lower()
    expected_status = case.oracle.status_code if case.oracle is not None else None
    if route_path.endswith("/activate") and isinstance(expected_status, int) and 200 <= expected_status < 300:
        return "suspended"
    if route_path.endswith("/suspend") and isinstance(expected_status, int) and 200 <= expected_status < 300:
        return "active"
    case_text = " ".join(part.strip().lower() for part in (case.title, case.objective) if part and part.strip())
    if "archived user" in case_text or "for archived user" in case_text:
        return "archived"
    if "suspended user" in case_text or "already suspended" in case_text:
        return "suspended"
    if "active user" in case_text or "already active" in case_text:
        return "active"
    return None


def _inferred_route_target_state(route_path: str) -> str | None:
    normalized_path = route_path.strip().lower()
    if normalized_path.endswith("/activate"):
        return "active"
    if normalized_path.endswith("/suspend"):
        return "suspended"
    if normalized_path.endswith("/archive"):
        return "archived"
    return None


def _same_state_inventory_contract_diagnostics(
    *,
    case: AuthoringCase,
    case_ref: str,
    route_spec: dict[str, Any],
    route_key: tuple[str, str],
    actual_state: str | None,
) -> list[GenerationDiagnostic]:
    if actual_state is None or case.oracle is None or not isinstance(case.oracle.status_code, int):
        return []

    explicit_target_state = _normalized_inventory_state(route_spec.get("target_state"))
    inferred_target_state = _inferred_route_target_state(route_key[1])
    target_state = explicit_target_state or inferred_target_state
    if target_state is None or actual_state != target_state:
        return []

    details = {
        "route_path": route_key[1],
        "actual_state": actual_state,
        "target_state": target_state,
        "setup_operations": [step.operation for step in case.setup],
    }
    missing_fields: list[str] = []
    if explicit_target_state is None:
        missing_fields.append("target_state")

    same_state_behavior = _normalized_inventory_same_state_behavior(route_spec.get("same_state_behavior"))
    same_state_status = _maybe_int(route_spec.get("same_state_status"))
    if same_state_behavior is None:
        missing_fields.append("same_state_behavior")
    if same_state_status is None:
        missing_fields.append("same_state_status")
    if missing_fields:
        return [
            authoring_diagnostic(
                "authoring_stage_inventory_same_state_behavior_missing",
                (
                    "Same-state lifecycle case is authored, but operation-inventory.yaml does not fully document the "
                    "route contract for reissuing the command on an entity already in the target state."
                ),
                source_ref=case_ref,
                details={**details, "missing_fields": missing_fields},
            )
        ]

    if case.oracle.status_code != same_state_status:
        return [
            authoring_diagnostic(
                "authoring_stage_inventory_same_state_mismatch",
                (
                    "Authoring case HTTP status for a same-state lifecycle command does not match the explicit "
                    "same-state contract recorded in operation-inventory.yaml."
                ),
                source_ref=case_ref,
                details={
                    **details,
                    "same_state_behavior": same_state_behavior,
                    "authored_status": case.oracle.status_code,
                    "inventory_same_state_status": same_state_status,
                },
            )
        ]
    if same_state_behavior == "idempotent_success" and case.oracle.persisted_state is None:
        return [
            authoring_diagnostic(
                "authoring_stage_inventory_idempotency_persistence_missing",
                (
                    "Same-state lifecycle case is documented as idempotent_success, but the authoring case does not "
                    "verify persisted state after reissuing the command."
                ),
                source_ref=case_ref,
                details={
                    **details,
                    "same_state_behavior": same_state_behavior,
                    "same_state_status": same_state_status,
                },
            )
        ]
    return []


def _is_same_state_inventory_case(
    *,
    route_spec: dict[str, Any],
    route_key: tuple[str, str],
    actual_state: str | None,
) -> bool:
    if actual_state is None:
        return False
    target_state = _normalized_inventory_state(route_spec.get("target_state")) or _inferred_route_target_state(route_key[1])
    return target_state is not None and actual_state == target_state


def _normalized_inventory_same_state_behavior(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in _SUPPORTED_SAME_STATE_BEHAVIORS:
        return normalized
    return None


def _normalized_inventory_state(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None
