"""Normalization helpers for the scenario Variables DSL."""

from __future__ import annotations

import re

from .ir import ParsedVariable

VARIABLE_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:(?:\s*=|\s*:)\s*(?P<value>.*))?$")
VARIABLE_BACKTICK_ASSIGNMENT_RE = re.compile(
    r"^`(?P<name>[A-Za-z_][A-Za-z0-9_]*)`\s*(?:(?:=|:|-{1,2}|–|—|вЂ“|вЂ”)\s*(?P<value>.*))?$"
)
VARIABLE_LOOSE_ASSIGNMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+(?:=|:|-{1,2}|–|—|вЂ“|вЂ”)\s*(?P<value>.+)$"
)
VARIABLE_TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?$")


def parse_variable_line(stripped_line: str) -> ParsedVariable | None:
    """Parse one non-table variable definition line."""

    backtick_assignment = VARIABLE_BACKTICK_ASSIGNMENT_RE.match(stripped_line)
    if backtick_assignment:
        variable_name = backtick_assignment.group("name").strip()
        raw_value = (backtick_assignment.group("value") or "").strip()
        return ParsedVariable(name=variable_name, raw_value=raw_value)

    variable_match = VARIABLE_RE.match(stripped_line)
    if variable_match:
        variable_name = variable_match.group("name").strip()
        raw_value = (variable_match.group("value") or "").strip()
        return ParsedVariable(name=variable_name, raw_value=raw_value)

    loose_assignment = VARIABLE_LOOSE_ASSIGNMENT_RE.match(stripped_line)
    if loose_assignment:
        variable_name = loose_assignment.group("name").strip()
        raw_value = loose_assignment.group("value").strip()
        return ParsedVariable(name=variable_name, raw_value=raw_value)

    return None


def parse_variable_table_line(
    stripped_line: str,
    table_headers: list[str] | None,
) -> tuple[ParsedVariable | None, list[str] | None]:
    """Parse one markdown-table variable row or detect table headers."""

    if not stripped_line.startswith("|") or not stripped_line.endswith("|"):
        return None, None

    cells = [cell.strip() for cell in stripped_line.strip("|").split("|")]
    if not cells or all(not cell for cell in cells):
        return None, None

    normalized_cells = [normalize_variable_table_header(cell) for cell in cells]
    if table_headers is None and any(cell in {"name", "variable", "key"} for cell in normalized_cells):
        return None, normalized_cells

    if table_headers:
        row = {
            header: cells[index].strip()
            for index, header in enumerate(table_headers)
            if index < len(cells)
        }
        variable_name = first_present_cell(row, "name", "variable", "key")
        if variable_name is None:
            return None, None
        raw_value = raw_value_from_variable_table_row(row)
        return ParsedVariable(
            name=variable_name.strip("` "),
            raw_value=raw_value,
            used_best_effort=True,
        ), None

    variable_name = cells[0].strip("` ")
    if variable_name.lower() in {"name", "variable", "key"}:
        return None, normalized_cells
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable_name):
        return None, None

    raw_value = normalize_variable_raw_value(cells[1].strip() if len(cells) > 1 else "")
    return ParsedVariable(name=variable_name, raw_value=raw_value, used_best_effort=True), None


def is_variable_table_line(stripped_line: str) -> bool:
    """Return whether a line looks like a markdown table row."""

    return stripped_line.startswith("|") and stripped_line.endswith("|")


def is_variable_table_separator(stripped_line: str) -> bool:
    """Return whether a line is a markdown table separator row."""

    return bool(VARIABLE_TABLE_SEPARATOR_RE.fullmatch(stripped_line))


def raw_value_from_variable_table_row(row: dict[str, str]) -> str:
    """Normalize a markdown table row into the legacy raw variable value format."""

    direct_value = first_present_cell(row, "value", "raw_value", "default")
    source = (first_present_cell(row, "source", "type") or "").strip().lower()
    env_name = first_present_cell(row, "env", "env_name", "environment", "environment_variable")

    if source in {"env", "environment"}:
        return f"env:{env_name or direct_value}"
    if source in {"generated", "runtime"}:
        return f"generated:{direct_value}" if direct_value else "generated"
    if source == "template":
        return f"template:{direct_value}"
    if source == "literal":
        return f"literal:{direct_value}"
    if source in {"derived", "transform"}:
        transform_value = first_present_cell(row, "transform", "transforms")
        source_value = first_present_cell(row, "from", "input", "source_variable", "source_name")
        if source == "transform" and transform_value and (source_value or direct_value):
            return f"transform:{transform_value}:{source_value or direct_value}"
        if transform_value and (source_value or direct_value):
            return f"derived:{source_value or direct_value}|{transform_value}"
        return f"{source}:{direct_value}"
    return normalize_variable_raw_value(direct_value or "")


def normalize_variable_raw_value(raw_value: str) -> str:
    """Trim a raw variable value and unwrap matching quotes/backticks."""

    value = str(raw_value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        return value[1:-1].strip()
    return value


def is_wrapped_literal(raw_value: str) -> bool:
    """Return whether a raw variable value is wrapped in literal quotes."""

    value = str(raw_value).strip()
    return len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}


def normalize_variable_table_header(value: str) -> str:
    """Normalize markdown table header names to the legacy aliases."""

    normalized = value.strip().strip("`").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    aliases = {
        "variable_name": "name",
        "var": "name",
        "key": "key",
        "env_var": "env",
        "env_variable": "env",
        "environment_variable": "environment_variable",
        "default_value": "default",
        "derived_from": "from",
        "source_name": "source_name",
        "source_variable": "source_variable",
        "transform": "transform",
        "transformation": "transform",
        "transformations": "transforms",
    }
    return aliases.get(normalized, normalized)


def first_present_cell(row: dict[str, str], *keys: str) -> str | None:
    """Return the first non-empty cell value for the given candidate keys."""

    for key in keys:
        value = row.get(key)
        if value is not None and value.strip():
            return value.strip()
    return None
