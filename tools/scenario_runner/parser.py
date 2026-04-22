"""Markdown scenario parser for normalized scenario runner plans."""

from __future__ import annotations

from hashlib import sha1
import re
from pathlib import Path
from typing import Any

from .models import (
    ApiStepDefinition,
    DbStepDefinition,
    ScenarioDefinition,
    ScenarioStep,
    ScenarioStepType,
    ScenarioVariableDefinition,
    ScenarioVariableSource,
)
from .parsing.errors import ScenarioParseError as _ScenarioParseError
from .parsing.interfaces import ScenarioParseOptions
from .parsing.loader import load_scenario_source
from .parsing.markdown_document import (
    MarkdownSection,
    parse_markdown_document_from_backend,
)
from .parsing.result import (
    ParseDiagnostic,
    ParseDiagnosticKind,
    ParseDiagnosticSeverity,
    ScenarioParseResult,
    SourceLocation,
)
from .parsing.step_blocks import split_step_blocks
from .parsing.step_fields import parse_step_block
from .parsing.step_ir import ParsedStepDraft

_VARIABLE_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:(?:\s*=|\s*:)\s*(?P<value>.*))?$"
)
_VARIABLE_BACKTICK_ASSIGNMENT_RE = re.compile(
    r"^`(?P<name>[A-Za-z_][A-Za-z0-9_]*)`\s*(?:(?:=|:|--?|[–—])\s*(?P<value>.*))?$"
)
_VARIABLE_LOOSE_ASSIGNMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+(?:=|:|--?|[–—])\s*(?P<value>.+)$"
)
_VARIABLE_GENERATED_AS_RE = re.compile(
    r"^`?(?P<name>[A-Za-z_][A-Za-z0-9_]*)`?\s+should\s+be\s+generated"
    r"(?:\s+dynamically)?(?:\s+as\s+(?P<value>.+))?$",
    re.IGNORECASE,
)
_ENV_VALUE_RE = re.compile(r"^env(?:\s*:\s*|\s+)(?P<name>[A-Za-z_][A-Za-z0-9_]*)$", re.IGNORECASE)
_RUNTIME_VALUE_RE = re.compile(
    r"^(?P<source>generated|runtime)(?:\s*:\s*|\s+)(?P<name>[A-Za-z_][A-Za-z0-9_]*)$",
    re.IGNORECASE,
)
_VARIABLE_SOURCE_PREFIX_RE = re.compile(
    r"^(?P<source>env|environment|generated|runtime|template|literal|derived|transform)"
    r"(?:\s*:\s*(?P<value>.*)|\s*)$",
    re.IGNORECASE,
)
_DERIVED_EXPRESSION_RE = re.compile(
    r"^(?P<source>\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}|[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*\|\s*(?P<transforms>[A-Za-z_][A-Za-z0-9_]*(?:\s*\|\s*[A-Za-z_][A-Za-z0-9_]*)*)$"
)
_TRANSFORM_EXPRESSION_RE = re.compile(
    r"^(?P<transform>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*"
    r"(?P<source>\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}|[A-Za-z_][A-Za-z0-9_]*)$"
)
_VARIABLE_TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?$")
_LOOSE_VARIABLE_NAME_RE = re.compile(r"^`?(?P<name>[A-Za-z_][A-Za-z0-9_]*)`?(?:\s+|$)")
_BACKTICK_VARIABLE_NAME_RE = re.compile(r"`(?P<name>[A-Za-z_][A-Za-z0-9_]*)`")
_KNOWN_BEST_EFFORT_VARIABLE_NAMES = {
    "company_guid",
    "generated_price_list_name",
    "run_suffix",
}
_SUPPORTED_TRANSFORMS = {"lower", "upper", "trim"}
_SUPPORTED_GENERATED_VALUES = {
    "run_id",
    "run_suffix",
    "timestamp",
    "timestamp_suffix",
    "generated_timestamp",
    "current_timestamp",
    "uuid",
}
_SLUG_INVALID_CHARS_RE = re.compile(r"[^a-z0-9]+")


class ScenarioParseError(_ScenarioParseError):
    """Raised when a markdown scenario cannot be normalized safely."""


class MarkdownScenarioParser:
    """Parses markdown scenario files into normalized typed definitions."""

    source_format = "markdown"

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
        source = load_scenario_source(scenario_path, error_type=ScenarioParseError)
        document = parse_markdown_document_from_backend(source, error_type=ScenarioParseError)
        resolved_scenario_path = document.source.path

        warnings: list[str] = []
        variable_warnings: list[str] = []
        variable_errors: list[str] = []
        scenario_definition = ScenarioDefinition(
            scenario_path=resolved_scenario_path,
            scenario_slug=self._build_scenario_slug(document.title, resolved_scenario_path),
            scenario_name=document.title,
        )

        normalized_section_names = {section.name.lower() for section in document.sections}
        for section in document.sections:
            normalized_name = section.name.lower()
            if normalized_name == "steps":
                step_definitions, step_warnings = self._parse_steps(section, resolved_scenario_path)
                scenario_definition.steps = step_definitions
                warnings.extend(step_warnings)
                continue

            if normalized_name == "variables":
                variable_definitions, section_variable_warnings, section_variable_errors = self._parse_variables(
                    section.lines
                )
                scenario_definition.variables = variable_definitions
                variable_warnings.extend(section_variable_warnings)
                variable_errors.extend(section_variable_errors)
                warnings.extend(section_variable_warnings)
                continue

            if normalized_name in self._simple_sections:
                setattr(
                    scenario_definition,
                    self._simple_sections[normalized_name],
                    self._parse_text(section.lines),
                )
                continue

            if normalized_name in self._list_sections:
                setattr(
                    scenario_definition,
                    self._list_sections[normalized_name],
                    self._parse_bullets(section.lines),
                )
                continue

            warnings.append(f"Unknown scenario section '{section.name}' was ignored.")

        if not scenario_definition.project:
            warnings.append("Section '## Project' is missing or empty.")
        if not scenario_definition.environment:
            warnings.append("Section '## Environment' is missing or empty.")
        if "steps" not in normalized_section_names:
            warnings.append("Section '## Steps' is missing.")

        scenario_definition.metadata = {
            "parse_warnings": warnings,
            "variables_parse_warnings": variable_warnings,
            "variables_validation_errors": variable_errors,
            "source_format": "markdown",
        }
        return scenario_definition

    def parse_result(
        self,
        scenario_path: Path,
        options: ScenarioParseOptions | None = None,
    ) -> ScenarioParseResult:
        """Return the new parse-result contract without changing legacy parse behavior."""

        del options
        source_path = Path(scenario_path)
        try:
            scenario_definition = self.parse(source_path)
        except ScenarioParseError as exc:
            return ScenarioParseResult(
                scenario=None,
                diagnostics=[
                    ParseDiagnostic(
                        severity=ParseDiagnosticSeverity.FATAL,
                        code="scenario.parse_failed",
                        message=str(exc),
                        kind=ParseDiagnosticKind.SYNTAX,
                        location=SourceLocation(path=source_path),
                    )
                ],
                source_format=self.source_format,
                source_path=source_path,
            )

        return ScenarioParseResult(
            scenario=scenario_definition,
            diagnostics=self._build_legacy_diagnostics(scenario_definition),
            source_format=str(scenario_definition.metadata.get("source_format") or self.source_format),
            source_path=scenario_definition.scenario_path,
        )

    @staticmethod
    def _build_legacy_diagnostics(scenario_definition: ScenarioDefinition) -> list[ParseDiagnostic]:
        diagnostics: list[ParseDiagnostic] = []
        source_path = scenario_definition.scenario_path
        for warning in scenario_definition.metadata.get("parse_warnings", []):
            diagnostics.append(
                ParseDiagnostic(
                    severity=ParseDiagnosticSeverity.WARNING,
                    code="scenario.parse_warning",
                    message=str(warning),
                    kind=ParseDiagnosticKind.COMPATIBILITY,
                    location=SourceLocation(path=source_path),
                )
            )
        for error in scenario_definition.metadata.get("variables_validation_errors", []):
            diagnostics.append(
                ParseDiagnostic(
                    severity=ParseDiagnosticSeverity.ERROR,
                    code="scenario.variables_validation_error",
                    message=str(error),
                    kind=ParseDiagnosticKind.VALIDATION,
                    location=SourceLocation(path=source_path, section="Variables"),
                )
            )
        return diagnostics

    def _parse_steps(
        self,
        section: MarkdownSection,
        scenario_path: Path,
    ) -> tuple[list[ScenarioStep], list[str]]:
        step_blocks, warnings = split_step_blocks(section, scenario_path)
        steps = [
            self._build_step(parse_step_block(block, error_type=ScenarioParseError))
            for block in step_blocks
        ]
        return steps, warnings

    def _parse_variables(self, lines: list[str]) -> tuple[list[ScenarioVariableDefinition], list[str], list[str]]:
        variables: list[ScenarioVariableDefinition] = []
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

            if self._is_variable_table_separator(stripped_line):
                continue

            if self._is_variable_table_line(stripped_line):
                parsed_variable, parsed_headers = self._parse_variable_table_line(stripped_line, table_headers)
                if parsed_headers is not None:
                    table_headers = parsed_headers
                    continue
            else:
                parsed_variable = self._parse_variable_line(stripped_line)

            if parsed_variable is None:
                errors.append(
                    "Variables section contains unsupported or ambiguous content at relative line "
                    f"{line_number}: {line.strip()!r}. Use an explicit machine-readable definition such as "
                    "'name = env:ENV_NAME', 'name = generated:run_suffix', 'name = template:... ', "
                    "'name = derived:source|lower', or 'name = literal:...'."
                )
                continue

            variable_name, raw_value, used_best_effort = parsed_variable
            if variable_name in seen_names:
                errors.append(
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
            try:
                variables.append(self._build_variable_definition(variable_name, raw_value))
            except ScenarioParseError as exc:
                errors.append(
                    f"Variables section has invalid definition for '{variable_name}' at relative line "
                    f"{line_number}: {exc}"
                )

        return variables, warnings, errors

    def _parse_variable_line(self, stripped_line: str) -> tuple[str, str, bool] | None:
        backtick_assignment = _VARIABLE_BACKTICK_ASSIGNMENT_RE.match(stripped_line)
        if backtick_assignment:
            variable_name = backtick_assignment.group("name").strip()
            raw_value = (backtick_assignment.group("value") or "").strip()
            return variable_name, raw_value, False

        variable_match = _VARIABLE_RE.match(stripped_line)
        if variable_match:
            variable_name = variable_match.group("name").strip()
            raw_value = (variable_match.group("value") or "").strip()
            return variable_name, raw_value, False

        loose_assignment = _VARIABLE_LOOSE_ASSIGNMENT_RE.match(stripped_line)
        if loose_assignment:
            variable_name = loose_assignment.group("name").strip()
            raw_value = loose_assignment.group("value").strip()
            return variable_name, raw_value, False
        return None

    @classmethod
    def _parse_variable_table_line(
        cls,
        stripped_line: str,
        table_headers: list[str] | None,
    ) -> tuple[tuple[str, str, bool] | None, list[str] | None]:
        if not stripped_line.startswith("|") or not stripped_line.endswith("|"):
            return None, None

        cells = [cell.strip() for cell in stripped_line.strip("|").split("|")]
        if not cells or all(not cell for cell in cells):
            return None, None

        normalized_cells = [_normalize_variable_table_header(cell) for cell in cells]
        if table_headers is None and any(cell in {"name", "variable", "key"} for cell in normalized_cells):
            return None, normalized_cells

        if table_headers:
            row = {
                header: cells[index].strip()
                for index, header in enumerate(table_headers)
                if index < len(cells)
            }
            variable_name = _first_present_cell(row, "name", "variable", "key")
            if variable_name is None:
                return None, None
            raw_value = cls._raw_value_from_variable_table_row(row)
            return (variable_name.strip("` "), raw_value, True), None

        variable_name = cells[0].strip("` ")
        if variable_name.lower() in {"name", "variable", "key"}:
            return None, normalized_cells
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable_name):
            return None, None

        raw_value = cls._normalize_variable_raw_value(cells[1].strip() if len(cells) > 1 else "")
        return (variable_name, raw_value, True), None

    def _build_variable_definition(self, variable_name: str, raw_value: str) -> ScenarioVariableDefinition:
        raw_value = str(raw_value).strip()
        quoted_literal = self._is_wrapped_literal(raw_value)
        normalized_raw_value = self._normalize_variable_raw_value(raw_value)
        source_match = _VARIABLE_SOURCE_PREFIX_RE.fullmatch(raw_value)
        source = source_match.group("source").lower() if source_match else ""
        source_value = (source_match.group("value") or "").strip() if source_match else ""

        env_match = _ENV_VALUE_RE.fullmatch(raw_value)
        if source in {"env", "environment"} or env_match:
            env_name = source_value or (env_match.group("name") if env_match else "")
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=raw_value,
                source=ScenarioVariableSource.ENV,
                env_name=env_name or variable_name.upper(),
            )

        runtime_match = _RUNTIME_VALUE_RE.fullmatch(raw_value)
        if source in {"generated", "runtime"} or runtime_match:
            generated_value = source_value or (
                runtime_match.group("name") if runtime_match else variable_name
            )
            generated_value = generated_value or variable_name
            self._validate_generated_variable(variable_name, generated_value)
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=f"generated:{generated_value}",
                source=ScenarioVariableSource.GENERATED,
            )

        if self._is_generated_runtime_variable(variable_name, raw_value):
            self._validate_generated_variable(variable_name, variable_name)
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=f"generated:{variable_name}",
                source=ScenarioVariableSource.GENERATED,
            )

        if source == "template":
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=self._normalize_variable_raw_value(source_value),
                source=ScenarioVariableSource.TEMPLATE,
            )

        if source == "literal":
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=self._normalize_variable_raw_value(source_value),
                source=ScenarioVariableSource.LITERAL,
            )

        if source in {"derived", "transform"}:
            source_name, transforms = self._parse_derived_variable(source, source_value)
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=raw_value,
                source=ScenarioVariableSource.DERIVED,
                source_name=source_name,
                transforms=transforms,
            )

        if "{{" in raw_value and "}}" in raw_value:
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=normalized_raw_value,
                source=ScenarioVariableSource.TEMPLATE,
            )

        if quoted_literal:
            return ScenarioVariableDefinition(
                name=variable_name,
                raw_value=normalized_raw_value,
                source=ScenarioVariableSource.LITERAL,
            )

        if not raw_value:
            raise ScenarioParseError(
                "empty variable definitions are not supported; use env:NAME, generated:kind, "
                "template:..., derived:source|transform, or literal:..."
            )

        raise ScenarioParseError(
            f"ambiguous untyped value {raw_value!r}; prose or bare literals are not allowed in "
            "Variables. Use an explicit type prefix."
        )

    @staticmethod
    def _is_variable_table_line(stripped_line: str) -> bool:
        return stripped_line.startswith("|") and stripped_line.endswith("|")

    @staticmethod
    def _is_variable_table_separator(stripped_line: str) -> bool:
        return bool(_VARIABLE_TABLE_SEPARATOR_RE.fullmatch(stripped_line))

    @classmethod
    def _raw_value_from_variable_table_row(cls, row: dict[str, str]) -> str:
        direct_value = _first_present_cell(row, "value", "raw_value", "default")
        source = (_first_present_cell(row, "source", "type") or "").strip().lower()
        env_name = _first_present_cell(row, "env", "env_name", "environment", "environment_variable")

        if source in {"env", "environment"}:
            return f"env:{env_name or direct_value}"
        if source in {"generated", "runtime"}:
            return f"generated:{direct_value}" if direct_value else "generated"
        if source == "template":
            return f"template:{direct_value}"
        if source == "literal":
            return f"literal:{direct_value}"
        if source in {"derived", "transform"}:
            transform_value = _first_present_cell(row, "transform", "transforms")
            source_value = _first_present_cell(row, "from", "input", "source_variable", "source_name")
            if source == "transform" and transform_value and (source_value or direct_value):
                return f"transform:{transform_value}:{source_value or direct_value}"
            if transform_value and (source_value or direct_value):
                return f"derived:{source_value or direct_value}|{transform_value}"
            return f"{source}:{direct_value}"
        return cls._normalize_variable_raw_value(direct_value or "")

    @staticmethod
    def _normalize_variable_raw_value(raw_value: str) -> str:
        value = str(raw_value).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
            return value[1:-1].strip()
        return value

    @staticmethod
    def _is_wrapped_literal(raw_value: str) -> bool:
        value = str(raw_value).strip()
        return len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}

    @classmethod
    def _parse_derived_variable(cls, source: str, raw_expression: str) -> tuple[str, list[str]]:
        expression = raw_expression.strip()
        if not expression:
            raise ScenarioParseError(
                "derived variables require an expression such as derived:run_suffix|lower"
            )

        if source == "transform":
            match = _TRANSFORM_EXPRESSION_RE.fullmatch(expression)
            if match is None:
                raise ScenarioParseError(
                    "transform variables require transform:<transform>:<source>, for example "
                    "transform:lower:run_suffix"
                )
            source_name = cls._normalize_derived_source_name(match.group("source"))
            transforms = [match.group("transform").strip().lower()]
        else:
            match = _DERIVED_EXPRESSION_RE.fullmatch(expression)
            if match is None:
                raise ScenarioParseError(
                    "derived variables require derived:<source>|<transform>, for example "
                    "derived:run_suffix|lower"
                )
            source_name = cls._normalize_derived_source_name(match.group("source"))
            transforms = [item.strip().lower() for item in match.group("transforms").split("|")]

        unsupported = [transform for transform in transforms if transform not in _SUPPORTED_TRANSFORMS]
        if unsupported:
            raise ScenarioParseError(
                "unsupported transform(s): "
                f"{', '.join(unsupported)}. Supported transforms: {', '.join(sorted(_SUPPORTED_TRANSFORMS))}."
            )
        return source_name, transforms

    @staticmethod
    def _normalize_derived_source_name(raw_source: str) -> str:
        source = raw_source.strip()
        placeholder_match = re.fullmatch(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", source)
        return placeholder_match.group(1) if placeholder_match else source

    @staticmethod
    def _validate_generated_variable(variable_name: str, generated_value: str) -> None:
        normalized_value = generated_value.strip().lower()
        normalized_name = variable_name.strip().lower()
        if normalized_value in _SUPPORTED_GENERATED_VALUES:
            return
        if normalized_value == normalized_name and (
            normalized_name.endswith("_suffix")
            or normalized_name.endswith("_run_id")
            or normalized_name in {"run_id", "timestamp", "generated_timestamp"}
            or (normalized_name.startswith("missing_") and normalized_name.endswith("_id"))
        ):
            return
        raise ScenarioParseError(
            f"unsupported generated value '{generated_value}'. Supported generated values: "
            f"{', '.join(sorted(_SUPPORTED_GENERATED_VALUES))}."
        )

    @classmethod
    def _normalize_generated_variable_value(cls, variable_name: str, raw_value: str) -> str:
        value = cls._normalize_variable_raw_value(raw_value)
        lowered = value.lower()
        if not value:
            return f"generated:{variable_name}"
        if "{{" in value and "}}" in value:
            return value
        if any(token in lowered for token in ("uuid", "timestamp", "unique", "dynamically")):
            return f"generated:{variable_name}"
        return value

    @staticmethod
    def _is_generated_runtime_variable(variable_name: str, raw_value: str) -> bool:
        normalized_value = raw_value.strip().lower()
        if normalized_value not in {"", "generated", "runtime"}:
            return False
        normalized_name = variable_name.lower()
        return (
            normalized_name == "run_suffix"
            or normalized_name.endswith("_suffix")
            or normalized_name.endswith("_run_id")
            or normalized_name in {"run_id", "timestamp", "generated_timestamp"}
        )

    def _build_step(self, draft: ParsedStepDraft) -> ScenarioStep:
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


def _normalize_variable_table_header(value: str) -> str:
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


def _first_present_cell(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and value.strip():
            return value.strip()
    return None
