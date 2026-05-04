"""Variable and placeholder helpers shared by case diagnostics."""

from __future__ import annotations

import re
from typing import Any

from tools.scenario_runner.domain.models import ScenarioVariableDefinition, ScenarioVariableSource
from tools.scenario_runner.parsing.variables.validation import build_variable_definition

from ..helpers import _PLACEHOLDER_PATTERN, _VARIABLE_NAME_PATTERN, _extract_placeholders
from ..models import AuthoringCase, AuthoringPlan

_EXACT_PLACEHOLDER_PATTERN = re.compile(r"^\s*{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}\s*$")
_EXPECTATION_COMPARISON_RE = re.compile(
    r"^\s*(?:response\s+)?(?P<left>.+?)\s*(?P<operator>=|!=)\s*(?P<right>.+?)\s*$",
    re.IGNORECASE,
)


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


def _get_path_value(value: Any, path: str) -> Any:
    current = value
    for part in [item for item in path.split(".") if item]:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _exact_placeholder_name(value: str) -> str | None:
    normalized = _strip_wrapping_quotes(value.strip()).strip()
    match = _EXACT_PLACEHOLDER_PATTERN.fullmatch(normalized)
    return match.group(1) if match is not None else None


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        return value[1:-1]
    return value


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
