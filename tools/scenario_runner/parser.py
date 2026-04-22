"""Markdown scenario parser for normalized scenario runner plans."""

from __future__ import annotations

from hashlib import sha1
import re
from pathlib import Path

from .models import ScenarioDefinition, ScenarioVariableDefinition
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
from .parsing.scenario_assembly import (
    ScenarioAssemblyInput,
    assemble_scenario_definition,
    parse_section_bullets,
    parse_section_text,
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

        assembly_input = ScenarioAssemblyInput(
            scenario_path=resolved_scenario_path,
            scenario_slug=self._build_scenario_slug(document.title, resolved_scenario_path),
            scenario_name=document.title,
            source_format=self.source_format,
        )
        warnings: list[str] = []
        variable_warnings: list[str] = []
        variable_errors: list[str] = []

        normalized_section_names = {section.name.lower() for section in document.sections}
        for section in document.sections:
            normalized_name = section.name.lower()
            if normalized_name == "steps":
                step_drafts, step_warnings = self._parse_steps(section, resolved_scenario_path)
                assembly_input.step_drafts = step_drafts
                warnings.extend(step_warnings)
                continue

            if normalized_name == "variables":
                variable_definitions, section_variable_warnings, section_variable_errors = self._parse_variables(
                    section.lines
                )
                assembly_input.variables = variable_definitions
                variable_warnings.extend(section_variable_warnings)
                variable_errors.extend(section_variable_errors)
                warnings.extend(section_variable_warnings)
                continue

            if normalized_name in self._simple_sections:
                setattr(assembly_input, self._simple_sections[normalized_name], parse_section_text(section.lines))
                continue

            if normalized_name in self._list_sections:
                setattr(
                    assembly_input,
                    self._list_sections[normalized_name],
                    parse_section_bullets(section.lines),
                )
                continue

            warnings.append(f"Unknown scenario section '{section.name}' was ignored.")

        if not assembly_input.project:
            warnings.append("Section '## Project' is missing or empty.")
        if not assembly_input.environment:
            warnings.append("Section '## Environment' is missing or empty.")
        if "steps" not in normalized_section_names:
            warnings.append("Section '## Steps' is missing.")

        assembly_input.parse_warnings = warnings
        assembly_input.variables_parse_warnings = variable_warnings
        assembly_input.variables_validation_errors = variable_errors
        return assemble_scenario_definition(assembly_input, error_type=ScenarioParseError)

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
    ) -> tuple[list[ParsedStepDraft], list[str]]:
        step_blocks, warnings = split_step_blocks(section, scenario_path)
        step_drafts = [
            parse_step_block(block, error_type=ScenarioParseError)
            for block in step_blocks
        ]
        return step_drafts, warnings

    def _parse_variables(
        self,
        lines: list[str],
    ) -> tuple[list[ScenarioVariableDefinition], list[str], list[str]]:
        result = parse_variables_section(lines, error_type=ScenarioParseError)
        return result.definitions, result.warnings, result.errors

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


