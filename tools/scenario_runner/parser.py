"""Markdown scenario parser for normalized scenario runner plans."""

from __future__ import annotations

from hashlib import sha1
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.common.errors import ValidationError

from .models import (
    ApiStepDefinition,
    DbStepDefinition,
    ScenarioDefinition,
    ScenarioStep,
    ScenarioStepType,
    ScenarioVariableDefinition,
    ScenarioVariableSource,
)

_SECTION_RE = re.compile(r"^##\s+(?P<name>.+?)\s*$")
_STEP_RE = re.compile(r"^###\s+Step\s+(?P<number>\d+)\s*$", re.IGNORECASE)
_FIELD_RE = re.compile(r"^(?P<name>[A-Za-z ]+):(?:\s*(?P<value>.*))?$")
_VARIABLE_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:(?:\s*=|\s*:)\s*(?P<value>.*))?$"
)
_ENV_VALUE_RE = re.compile(r"^env:(?P<name>[A-Za-z_][A-Za-z0-9_]*)$", re.IGNORECASE)
_RUNTIME_VALUE_RE = re.compile(
    r"^(?P<source>generated|runtime):(?P<name>[A-Za-z_][A-Za-z0-9_]*)$",
    re.IGNORECASE,
)
_LOOSE_VARIABLE_NAME_RE = re.compile(r"^`?(?P<name>[A-Za-z_][A-Za-z0-9_]*)`?(?:\s+|$)")
_BACKTICK_VARIABLE_NAME_RE = re.compile(r"`(?P<name>[A-Za-z_][A-Za-z0-9_]*)`")
_KNOWN_BEST_EFFORT_VARIABLE_NAMES = {
    "company_guid",
    "generated_price_list_name",
    "run_suffix",
}
_SCENARIO_TITLE_RE = re.compile(r"^#\s+Scenario:\s*(?P<name>.+?)\s*$")
_SLUG_INVALID_CHARS_RE = re.compile(r"[^a-z0-9]+")
_KNOWN_STEP_FIELDS = {
    "type",
    "name",
    "method",
    "path",
    "headers",
    "body",
    "retry",
    "sql",
    "params",
    "capture",
    "expected",
}


class ScenarioParseError(ValidationError):
    """Raised when a markdown scenario cannot be normalized safely."""


@dataclass(slots=True)
class _ScenarioStepDraft:
    step_number: int
    line_number: int
    fields: dict[str, Any]
    warnings: list[str]


class MarkdownScenarioParser:
    """Parses markdown scenario files into normalized typed definitions."""

    _simple_sections = {
        "project": "project",
        "environment": "environment",
        "goal": "goal",
        "notes": "notes",
        "report output": "report_output",
    }
    _list_sections = {
        "preconditions": "preconditions",
        "final expectations": "final_expectations",
    }

    def parse(self, scenario_path: Path) -> ScenarioDefinition:
        if not scenario_path.exists():
            raise ScenarioParseError(f"Scenario file does not exist: {scenario_path}")

        resolved_scenario_path = scenario_path.resolve()
        raw_lines = resolved_scenario_path.read_text(encoding="utf-8").splitlines()
        title = self._parse_title(raw_lines, resolved_scenario_path)
        sections = self._split_sections(raw_lines)

        warnings: list[str] = []
        variable_warnings: list[str] = []
        scenario_definition = ScenarioDefinition(
            scenario_path=resolved_scenario_path,
            scenario_slug=self._build_scenario_slug(title, resolved_scenario_path),
            scenario_name=title,
        )

        normalized_section_names = {section_name.lower() for section_name in sections}
        for section_name, section_lines in sections.items():
            normalized_name = section_name.lower()
            if normalized_name == "steps":
                step_definitions, step_warnings = self._parse_steps(section_lines, resolved_scenario_path)
                scenario_definition.steps = step_definitions
                warnings.extend(step_warnings)
                continue

            if normalized_name == "variables":
                variable_definitions, section_variable_warnings = self._parse_variables(section_lines)
                scenario_definition.variables = variable_definitions
                variable_warnings.extend(section_variable_warnings)
                warnings.extend(section_variable_warnings)
                continue

            if normalized_name in self._simple_sections:
                setattr(
                    scenario_definition,
                    self._simple_sections[normalized_name],
                    self._parse_text(section_lines),
                )
                continue

            if normalized_name in self._list_sections:
                setattr(
                    scenario_definition,
                    self._list_sections[normalized_name],
                    self._parse_bullets(section_lines),
                )
                continue

            warnings.append(f"Unknown scenario section '{section_name}' was ignored.")

        if not scenario_definition.project:
            warnings.append("Section '## Project' is missing or empty.")
        if not scenario_definition.environment:
            warnings.append("Section '## Environment' is missing or empty.")
        if "steps" not in normalized_section_names:
            warnings.append("Section '## Steps' is missing.")

        scenario_definition.metadata = {
            "parse_warnings": warnings,
            "variables_parse_warnings": variable_warnings,
            "source_format": "markdown",
        }
        return scenario_definition

    def _parse_title(self, lines: list[str], scenario_path: Path) -> str:
        title: str | None = None
        title_line_number = 0
        inside_fence = False
        for line_number, line in enumerate(lines, start=1):
            stripped_line = line.strip()
            if self._is_fence_line(stripped_line):
                inside_fence = not inside_fence

            match = _SCENARIO_TITLE_RE.match(stripped_line) if not inside_fence else None
            if match:
                if title is not None:
                    raise ScenarioParseError(
                        f"Scenario '{scenario_path}' is malformed: duplicate '# Scenario:' title "
                        f"at line {line_number}; first declared at line {title_line_number}."
                    )
                title = match.group("name").strip()
                title_line_number = line_number

        if title is not None:
            return title

        raise ScenarioParseError(
            f"Scenario '{scenario_path}' is malformed: missing '# Scenario: ...' title."
        )

    def _split_sections(self, lines: list[str]) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {}
        seen_sections: dict[str, int] = {}
        current_name: str | None = None
        current_lines: list[str] = []
        inside_fence = False

        for line_number, line in enumerate(lines, start=1):
            stripped_line = line.strip()
            if self._is_fence_line(stripped_line):
                inside_fence = not inside_fence

            match = _SECTION_RE.match(stripped_line) if not inside_fence else None
            if match:
                if current_name is not None:
                    sections[current_name] = current_lines
                current_name = match.group("name").strip()
                normalized_name = current_name.lower()
                if normalized_name in seen_sections:
                    raise ScenarioParseError(
                        f"Duplicate top-level section '## {current_name}' at line {line_number}; "
                        f"first declared at line {seen_sections[normalized_name]}."
                    )
                seen_sections[normalized_name] = line_number
                current_lines = []
                continue

            if current_name is not None:
                current_lines.append(line)

        if current_name is not None:
            sections[current_name] = current_lines

        return sections

    def _parse_steps(
        self,
        lines: list[str],
        scenario_path: Path,
    ) -> tuple[list[ScenarioStep], list[str]]:
        step_blocks: list[tuple[int, int, list[str]]] = []
        current_step_number: int | None = None
        current_step_line_number = 0
        current_block: list[str] = []
        warnings: list[str] = []
        inside_fence = False

        for offset, line in enumerate(lines, start=1):
            stripped_line = line.strip()
            if self._is_fence_line(stripped_line):
                inside_fence = not inside_fence

            match = _STEP_RE.match(stripped_line) if not inside_fence else None
            if match:
                if current_step_number is not None:
                    step_blocks.append((current_step_number, current_step_line_number, current_block))
                current_step_number = int(match.group("number"))
                current_step_line_number = offset
                current_block = []
                continue

            if current_step_number is None:
                if line.strip():
                    warnings.append(
                        f"Ignored content before first step in '{scenario_path.name}': {line.strip()!r}"
                    )
                continue

            current_block.append(line)

        if current_step_number is not None:
            step_blocks.append((current_step_number, current_step_line_number, current_block))

        steps = [
            self._build_step(self._parse_step_block(number, line_number, block_lines))
            for number, line_number, block_lines in step_blocks
        ]
        return steps, warnings

    def _parse_variables(self, lines: list[str]) -> tuple[list[ScenarioVariableDefinition], list[str]]:
        variables: list[ScenarioVariableDefinition] = []
        warnings: list[str] = []
        seen_names: set[str] = set()

        for line_number, line in enumerate(lines, start=1):
            stripped_line = line.strip()
            if not stripped_line:
                continue
            if stripped_line.startswith("- "):
                stripped_line = stripped_line[2:].strip()

            parsed_variable = self._parse_variable_line(stripped_line)
            if parsed_variable is None:
                warnings.append(
                    f"Variables section contains unrecognized content at relative line {line_number}: "
                    f"{line.strip()!r}"
                )
                continue

            variable_name, raw_value, used_best_effort = parsed_variable
            if variable_name in seen_names:
                warnings.append(
                    f"Variables section contains duplicate variable '{variable_name}' at relative line "
                    f"{line_number}; first definition was kept."
                )
                continue
            seen_names.add(variable_name)
            if used_best_effort:
                warnings.append(
                    f"Variables section used best-effort parsing for '{variable_name}' at relative line "
                    f"{line_number}."
                )
            variables.append(self._build_variable_definition(variable_name, raw_value))

        return variables, warnings

    def _parse_variable_line(self, stripped_line: str) -> tuple[str, str, bool] | None:
        variable_match = _VARIABLE_RE.match(stripped_line)
        if variable_match:
            variable_name = variable_match.group("name").strip()
            raw_value = (variable_match.group("value") or "").strip()
            return variable_name, raw_value, False

        table_variable = self._parse_variable_table_line(stripped_line)
        if table_variable is not None:
            return table_variable

        backtick_match = _BACKTICK_VARIABLE_NAME_RE.search(stripped_line)
        if backtick_match:
            return backtick_match.group("name").strip(), "", True

        loose_match = _LOOSE_VARIABLE_NAME_RE.match(stripped_line)
        if loose_match and loose_match.group("name").strip() in _KNOWN_BEST_EFFORT_VARIABLE_NAMES:
            return loose_match.group("name").strip(), "", True
        return None

    @staticmethod
    def _parse_variable_table_line(stripped_line: str) -> tuple[str, str, bool] | None:
        if not stripped_line.startswith("|") or not stripped_line.endswith("|"):
            return None

        cells = [cell.strip() for cell in stripped_line.strip("|").split("|")]
        if not cells or all(not cell for cell in cells):
            return None
        if all(set(cell) <= {"-", ":"} for cell in cells if cell):
            return None

        variable_name = cells[0].strip("` ")
        if variable_name.lower() in {"name", "variable", "key"}:
            return None
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable_name):
            return None

        raw_value = cells[1].strip() if len(cells) > 1 else ""
        return variable_name, raw_value, True

    def _build_variable_definition(self, variable_name: str, raw_value: str) -> ScenarioVariableDefinition:
        env_match = _ENV_VALUE_RE.fullmatch(raw_value)
        if env_match:
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=raw_value,
                source=ScenarioVariableSource.ENV,
                env_name=env_match.group("name"),
            )

        runtime_match = _RUNTIME_VALUE_RE.fullmatch(raw_value)
        if runtime_match:
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=raw_value,
                source=ScenarioVariableSource.RUNTIME,
            )

        if variable_name == "run_suffix" and raw_value.lower() in {"", "generated", "runtime"}:
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=raw_value or "generated:run_suffix",
                source=ScenarioVariableSource.RUNTIME,
            )

        if variable_name == "generated_price_list_name" and not raw_value:
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value="AUTOTEST Attributes Flow {{run_suffix}}",
                source=ScenarioVariableSource.TEMPLATE,
            )

        if not raw_value:
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=raw_value,
                source=ScenarioVariableSource.ENV,
                env_name=variable_name.upper(),
            )

        if "{{" in raw_value and "}}" in raw_value:
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=raw_value,
                source=ScenarioVariableSource.TEMPLATE,
            )

        return ScenarioVariableDefinition(
            name=variable_name,
            raw_value=raw_value,
            source=ScenarioVariableSource.LITERAL,
        )

    def _parse_step_block(
        self,
        step_number: int,
        line_number: int,
        lines: list[str],
    ) -> _ScenarioStepDraft:
        fields: dict[str, Any] = {}
        warnings: list[str] = []
        index = 0

        while index < len(lines):
            stripped_line = lines[index].strip()
            if not stripped_line:
                index += 1
                continue

            field_match = _FIELD_RE.match(stripped_line)
            if not field_match:
                warnings.append(
                    f"Step {step_number} contains unrecognized content at relative line {index + 1}: "
                    f"{stripped_line!r}"
                )
                index += 1
                continue

            field_name = field_match.group("name").strip().lower()
            inline_value = (field_match.group("value") or "").strip()
            if field_name in fields:
                raise ScenarioParseError(
                    f"Step {step_number} is malformed: duplicate field '{field_name}' "
                    f"at relative line {index + 1}."
                )

            if field_name in {"type", "name", "method", "path"}:
                fields[field_name] = inline_value
                index += 1
                continue

            if field_name in {"headers", "body", "params"}:
                block_text, index = self._consume_block(lines, index + 1, step_number, field_name)
                if inline_value and not block_text:
                    block_text = inline_value
                if not block_text:
                    fields[field_name] = {} if field_name != "body" else None
                    continue
                fields[field_name] = self._parse_json_block(block_text, step_number, field_name)
                continue

            if field_name == "retry":
                block_text, index = self._consume_block(lines, index + 1, step_number, field_name)
                if inline_value and not block_text:
                    block_text = inline_value
                fields[field_name] = self._parse_retry_block(block_text, step_number)
                continue

            if field_name == "sql":
                block_text, index = self._consume_block(lines, index + 1, step_number, field_name)
                sql_value = inline_value if inline_value else block_text
                fields[field_name] = sql_value.strip()
                continue

            if field_name in {"capture", "expected"}:
                bullet_values, next_index = self._consume_bullets(lines, index + 1)
                if inline_value:
                    bullet_values.insert(0, inline_value)
                fields[field_name] = bullet_values
                index = next_index
                continue

            warnings.append(f"Step {step_number} field '{field_name}' is unknown and was ignored.")
            index += 1

        return _ScenarioStepDraft(
            step_number=step_number,
            line_number=line_number,
            fields=fields,
            warnings=warnings,
        )

    def _build_step(self, draft: _ScenarioStepDraft) -> ScenarioStep:
        raw_type = str(draft.fields.get("type", "")).strip().lower()
        if not raw_type:
            raise ScenarioParseError(f"Step {draft.step_number} is malformed: missing 'Type:'.")

        try:
            step_type = ScenarioStepType(raw_type)
        except ValueError as exc:
            raise ScenarioParseError(
                f"Step {draft.step_number} is malformed: unsupported type '{raw_type}'."
            ) from exc

        step_name = str(draft.fields.get("name") or "").strip()
        if not step_name:
            raise ScenarioParseError(f"Step {draft.step_number} is malformed: missing 'Name:'.")
        step_id = f"step-{draft.step_number}"
        capture = self._normalize_string_list(draft.fields.get("capture"))
        expected = self._normalize_string_list(draft.fields.get("expected"))

        if step_type == ScenarioStepType.API:
            method = str(draft.fields.get("method", "")).strip().upper()
            path = str(draft.fields.get("path", "")).strip()
            if not method:
                raise ScenarioParseError(
                    f"Step {draft.step_number} is malformed: API step missing 'Method:'."
                )
            if not path:
                raise ScenarioParseError(
                    f"Step {draft.step_number} is malformed: API step missing 'Path:'."
                )
            api_definition = ApiStepDefinition(
                name=step_name,
                method=method,
                path=path,
                headers=self._normalize_mapping(
                    draft.fields.get("headers"),
                    step_number=draft.step_number,
                    field_name="headers",
                ),
                params=self._normalize_mapping(
                    draft.fields.get("params"),
                    step_number=draft.step_number,
                    field_name="params",
                ),
                body=draft.fields.get("body"),
                retry=self._normalize_optional_mapping(
                    draft.fields.get("retry"),
                    step_number=draft.step_number,
                    field_name="retry",
                ),
                capture=capture,
                expected=expected,
            )
            return ScenarioStep(
                step_id=step_id,
                step_number=draft.step_number,
                title=step_name,
                step_type=step_type,
                api=api_definition,
                metadata={"parse_warnings": draft.warnings, "source_line": draft.line_number},
            )

        sql = str(draft.fields.get("sql", "")).strip()
        if not sql:
            raise ScenarioParseError(f"Step {draft.step_number} is malformed: DB step missing 'SQL:'.")
        db_definition = DbStepDefinition(
            name=step_name,
            sql=sql,
            params=self._normalize_mapping(
                draft.fields.get("params"),
                step_number=draft.step_number,
                field_name="params",
            ),
            capture=capture,
            expected=expected,
        )
        return ScenarioStep(
            step_id=step_id,
            step_number=draft.step_number,
            title=step_name,
            step_type=step_type,
            db=db_definition,
            metadata={"parse_warnings": draft.warnings, "source_line": draft.line_number},
        )

    def _consume_block(
        self,
        lines: list[str],
        start_index: int,
        step_number: int,
        field_name: str,
    ) -> tuple[str, int]:
        index = start_index
        while index < len(lines) and not lines[index].strip():
            index += 1

        if index >= len(lines):
            return "", index

        stripped_line = lines[index].strip()
        if stripped_line.startswith("```"):
            return self._consume_fenced_block(lines, index, step_number, field_name)

        collected: list[str] = []
        while index < len(lines):
            candidate = lines[index]
            stripped_candidate = candidate.strip()
            if self._is_step_field(stripped_candidate) or _STEP_RE.match(stripped_candidate):
                break
            collected.append(candidate)
            index += 1

        return "\n".join(self._trim_empty_lines(collected)).strip(), index

    def _consume_fenced_block(
        self,
        lines: list[str],
        start_index: int,
        step_number: int,
        field_name: str,
    ) -> tuple[str, int]:
        index = start_index + 1
        collected: list[str] = []

        while index < len(lines):
            if lines[index].strip().startswith("```"):
                return "\n".join(collected).strip(), index + 1
            collected.append(lines[index])
            index += 1

        raise ScenarioParseError(
            f"Step {step_number} has malformed fenced block for '{field_name}': missing closing ```."
        )

    def _consume_bullets(self, lines: list[str], start_index: int) -> tuple[list[str], int]:
        index = start_index
        values: list[str] = []

        while index < len(lines):
            stripped_line = lines[index].strip()
            if not stripped_line:
                index += 1
                continue
            if not stripped_line.startswith("- "):
                break
            values.append(stripped_line[2:].strip())
            index += 1

        return values, index

    def _parse_json_block(self, block_text: str, step_number: int, field_name: str) -> Any:
        try:
            return json.loads(block_text)
        except json.JSONDecodeError as exc:
            raise ScenarioParseError(
                f"Step {step_number} has invalid JSON in '{field_name}': {exc.msg}."
            ) from exc

    def _parse_retry_block(self, block_text: str, step_number: int) -> dict[str, Any] | None:
        normalized = block_text.strip()
        if not normalized:
            return None
        if normalized.startswith("{"):
            parsed = self._parse_json_block(normalized, step_number, "retry")
            if not isinstance(parsed, dict):
                raise ScenarioParseError(f"Step {step_number} is malformed: 'retry' must contain an object.")
            return parsed

        values: dict[str, Any] = {}
        lines = normalized.splitlines()
        index = 0
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped:
                index += 1
                continue
            if ":" not in stripped:
                raise ScenarioParseError(
                    f"Step {step_number} has invalid retry config at relative line {index + 1}: {stripped!r}."
                )
            key, raw_value = (part.strip() for part in stripped.split(":", 1))
            if not key:
                raise ScenarioParseError(f"Step {step_number} has invalid retry config with empty key.")
            if raw_value:
                values[key] = self._parse_scalar_retry_value(raw_value)
                index += 1
                continue

            list_values: list[Any] = []
            index += 1
            while index < len(lines):
                candidate = lines[index].strip()
                if not candidate:
                    index += 1
                    continue
                if not candidate.startswith("- "):
                    break
                list_values.append(self._parse_scalar_retry_value(candidate[2:].strip()))
                index += 1
            values[key] = list_values
        return values

    @staticmethod
    def _parse_scalar_retry_value(value: str) -> Any:
        normalized = value.strip()
        lowered = normalized.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if re.fullmatch(r"-?\d+", normalized):
            return int(normalized)
        if re.fullmatch(r"-?(?:\d+\.\d+|\d+\.|\.\d+)", normalized):
            return float(normalized)
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
            return normalized[1:-1]
        return normalized

    @staticmethod
    def _parse_text(lines: list[str]) -> str:
        return "\n".join(line.strip() for line in MarkdownScenarioParser._trim_empty_lines(lines)).strip()

    @staticmethod
    def _parse_bullets(lines: list[str]) -> list[str]:
        values = [line.strip()[2:].strip() for line in lines if line.strip().startswith("- ")]
        return [value for value in values if value]

    @staticmethod
    def _trim_empty_lines(lines: list[str]) -> list[str]:
        trimmed = list(lines)
        while trimmed and not trimmed[0].strip():
            trimmed.pop(0)
        while trimmed and not trimmed[-1].strip():
            trimmed.pop()
        return trimmed

    @staticmethod
    def _normalize_mapping(value: Any, step_number: int, field_name: str) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ScenarioParseError(
                f"Step {step_number} is malformed: '{field_name}' must contain a JSON object."
            )
        return value

    @staticmethod
    def _normalize_optional_mapping(value: Any, step_number: int, field_name: str) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ScenarioParseError(
                f"Step {step_number} is malformed: '{field_name}' must contain an object."
            )
        return value

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    @staticmethod
    def _is_step_field(line: str) -> bool:
        field_match = _FIELD_RE.match(line)
        return bool(field_match and field_match.group("name").strip().lower() in _KNOWN_STEP_FIELDS)

    @classmethod
    def _build_scenario_slug(cls, title: str, scenario_path: Path) -> str:
        title_slug = cls._slugify(title)
        path_slug = cls._slugify(scenario_path.stem)
        path_hash = sha1(str(scenario_path).encode("utf-8")).hexdigest()[:8]
        if path_slug and path_slug != title_slug:
            return f"{title_slug}-{path_slug}-{path_hash}"
        return f"{title_slug}-{path_hash}"

    @staticmethod
    def _slugify(value: str) -> str:
        slug = _SLUG_INVALID_CHARS_RE.sub("-", value.strip().lower()).strip("-")
        return slug or "scenario"

    @staticmethod
    def _is_fence_line(line: str) -> bool:
        return line.startswith("```")
