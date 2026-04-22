"""Intermediate structures for scenario variable parsing."""

from __future__ import annotations

from dataclasses import dataclass, field

from tools.scenario_runner.domain.models import ScenarioVariableDefinition


def empty_variable_definitions() -> list[ScenarioVariableDefinition]:
    """Create a typed empty variable definition list."""

    return []


def empty_variable_messages() -> list[str]:
    """Create a typed empty warning/error list for variable parsing."""

    return []


@dataclass(frozen=True, slots=True)
class ParsedVariable:
    """One machine-readable variable entry before domain conversion."""

    name: str
    raw_value: str
    used_best_effort: bool = False


@dataclass(slots=True)
class VariableParseResult:
    """Parsed Variables section with compatibility warnings and validation errors."""

    definitions: list[ScenarioVariableDefinition] = field(default_factory=empty_variable_definitions)
    warnings: list[str] = field(default_factory=empty_variable_messages)
    errors: list[str] = field(default_factory=empty_variable_messages)
