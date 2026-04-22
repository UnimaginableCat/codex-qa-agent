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
)
from .parsing.contracts.errors import ScenarioParseError as _ScenarioParseError
from .parsing.contracts.interfaces import ScenarioParseOptions
from .parsing.contracts.result import (
    ParseDiagnostic,
    ParseDiagnosticKind,
    ParseDiagnosticSeverity,
    ScenarioParseResult,
    SourceLocation,
)
from .parsing.markdown.document import (
    MarkdownSection,
    parse_markdown_document_from_backend,
)
from .parsing.source.loader import load_scenario_source
from .parsing.steps.blocks import split_step_blocks
from .parsing.steps.fields import parse_step_block
from .parsing.steps.ir import ParsedStepDraft
from .parsing.variables.parser import parse_variables_section

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

    def _parse_variables(
        self,
        lines: list[str],
    ) -> tuple[list[ScenarioVariableDefinition], list[str], list[str]]:
        result = parse_variables_section(lines, error_type=ScenarioParseError)
        return result.definitions, result.warnings, result.errors

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


