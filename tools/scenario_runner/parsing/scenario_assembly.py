"""Final scenario assembly from parsed section content and subsystem IR."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tools.scenario_runner.domain.models import ScenarioDefinition, ScenarioVariableDefinition

from .contracts.errors import ScenarioParseError
from .scenario_converter import convert_step_drafts
from .steps.ir import ParsedStepDraft


@dataclass(slots=True)
class ScenarioAssemblyInput:
    """Inputs required to assemble the stable runtime ScenarioDefinition."""

    scenario_path: Path
    scenario_slug: str
    scenario_name: str
    project: str = ""
    environment: str = ""
    goal: str = ""
    preconditions: list[str] = field(default_factory=list)
    notes: str = ""
    final_expectations: list[str] = field(default_factory=list)
    report_output: str = ""
    variables: list[ScenarioVariableDefinition] = field(default_factory=list)
    step_drafts: list[ParsedStepDraft] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)
    variables_parse_warnings: list[str] = field(default_factory=list)
    variables_validation_errors: list[str] = field(default_factory=list)
    source_format: str = "markdown"


def assemble_scenario_definition(
    assembly_input: ScenarioAssemblyInput,
    *,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> ScenarioDefinition:
    """Assemble the final runtime ScenarioDefinition without changing its shape."""

    return ScenarioDefinition(
        scenario_path=assembly_input.scenario_path,
        scenario_slug=assembly_input.scenario_slug,
        scenario_name=assembly_input.scenario_name,
        project=assembly_input.project,
        environment=assembly_input.environment,
        goal=assembly_input.goal,
        preconditions=list(assembly_input.preconditions),
        notes=assembly_input.notes,
        final_expectations=list(assembly_input.final_expectations),
        report_output=assembly_input.report_output,
        variables=list(assembly_input.variables),
        steps=convert_step_drafts(assembly_input.step_drafts, error_type=error_type),
        metadata=_build_scenario_metadata(assembly_input),
    )


def parse_section_text(lines: list[str]) -> str:
    """Normalize a free-form section body into the stable scenario text format."""

    return "\n".join(line.strip() for line in _trim_empty_lines(lines)).strip()


def parse_section_bullets(lines: list[str]) -> list[str]:
    """Normalize a bullet section body into the stable list format."""

    values = [line.strip()[2:].strip() for line in lines if line.strip().startswith("- ")]
    return [value for value in values if value]


def _build_scenario_metadata(assembly_input: ScenarioAssemblyInput) -> dict[str, object]:
    return {
        "parse_warnings": list(assembly_input.parse_warnings),
        "variables_parse_warnings": list(assembly_input.variables_parse_warnings),
        "variables_validation_errors": list(assembly_input.variables_validation_errors),
        "source_format": assembly_input.source_format,
    }


def _trim_empty_lines(lines: list[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and not trimmed[0].strip():
        trimmed.pop(0)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed
