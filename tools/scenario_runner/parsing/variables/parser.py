"""Section-level parser for the scenario Variables DSL."""

from __future__ import annotations

from tools.scenario_runner.models import ScenarioVariableDefinition

from ..contracts.errors import ScenarioParseError
from .ir import VariableParseResult
from .normalization import (
    is_variable_table_line,
    is_variable_table_separator,
    parse_variable_line,
    parse_variable_table_line,
)
from .validation import build_variable_definition


def parse_variables_section(
    lines: list[str],
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> VariableParseResult:
    """Parse a Variables section into definitions plus compatibility metadata messages."""

    definitions: list[ScenarioVariableDefinition] = []
    warnings: list[str] = []
    errors: list[str] = []
    seen_names: set[str] = set()
    table_headers: list[str] | None = None

    for line_number, line in enumerate(lines, start=1):
        stripped_line = line.strip()
        if not stripped_line:
            continue
        if stripped_line.startswith("- "):
            stripped_line = stripped_line[2:].strip()

        if is_variable_table_separator(stripped_line):
            continue

        if is_variable_table_line(stripped_line):
            parsed_variable, parsed_headers = parse_variable_table_line(stripped_line, table_headers)
            if parsed_headers is not None:
                table_headers = parsed_headers
                continue
        else:
            parsed_variable = parse_variable_line(stripped_line)

        if parsed_variable is None:
            errors.append(
                "Variables section contains unsupported or ambiguous content at relative line "
                f"{line_number}: {line.strip()!r}. Use an explicit machine-readable definition such as "
                "'name = env:ENV_NAME', 'name = generated:run_suffix', 'name = template:... ', "
                "'name = derived:source|lower', or 'name = literal:...'."
            )
            continue

        variable_name = parsed_variable.name
        if variable_name in seen_names:
            errors.append(
                f"Variables section contains duplicate variable '{variable_name}' at relative line "
                f"{line_number}; first definition was kept."
            )
            continue
        seen_names.add(variable_name)
        if parsed_variable.used_best_effort:
            warnings.append(
                f"Variables section used best-effort parsing for '{variable_name}' at relative line "
                f"{line_number}."
            )
        try:
            definitions.append(
                build_variable_definition(
                    variable_name,
                    parsed_variable.raw_value,
                    error_type=error_type,
                )
            )
        except error_type as exc:
            errors.append(
                f"Variables section has invalid definition for '{variable_name}' at relative line "
                f"{line_number}: {exc}"
            )

    return VariableParseResult(definitions=definitions, warnings=warnings, errors=errors)
