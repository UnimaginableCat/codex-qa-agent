"""Markdown scenario parser for normalized scenario runner plans."""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path

from tools.common.slugging import stable_slug

from .domain.models import ScenarioDefinition, ScenarioVariableDefinition
from .parsing.contracts.errors import ScenarioParseError as _ScenarioParseError
from .parsing.contracts.interfaces import ScenarioParseOptions
from .parsing.contracts.result import ScenarioParseResult
from .parsing.markdown.document import (
    MarkdownSection,
    parse_markdown_document_from_backend,
)
from .parsing.parse_result_adapter import adapt_legacy_parse_result
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

_SCENARIO_SLUG_MAX_LENGTH = 120


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
        """Parse one markdown scenario into the stable runtime ScenarioDefinition."""

        source = load_scenario_source(scenario_path, error_type=ScenarioParseError)
        document = parse_markdown_document_from_backend(source, error_type=ScenarioParseError)
        resolved_scenario_path = document.source.path

        assembly_input = self._build_assembly_input(document.title, resolved_scenario_path)
        normalized_section_names = self._normalize_section_names(document.sections)
        warnings, variable_warnings, variable_errors = self._route_document_sections(
            document.sections,
            assembly_input,
            resolved_scenario_path,
        )
        self._append_missing_section_warnings(assembly_input, normalized_section_names, warnings)
        self._attach_parse_metadata(assembly_input, warnings, variable_warnings, variable_errors)
        return assemble_scenario_definition(assembly_input, error_type=ScenarioParseError)

    def parse_result(
        self,
        scenario_path: Path,
        options: ScenarioParseOptions | None = None,
    ) -> ScenarioParseResult:
        """Return the new parse-result contract without changing legacy parse behavior."""

        del options
        return adapt_legacy_parse_result(
            self.parse,
            Path(scenario_path),
            source_format=self.source_format,
            error_type=ScenarioParseError,
        )

    def _parse_steps(
        self,
        section: MarkdownSection,
        scenario_path: Path,
    ) -> tuple[list[ParsedStepDraft], list[str]]:
        """Parse the Steps section into step drafts plus compatibility warnings."""

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
        """Parse the Variables section into definitions, warnings, and validation errors."""

        result = parse_variables_section(lines, error_type=ScenarioParseError)
        return result.definitions, result.warnings, result.errors

    def _build_assembly_input(self, scenario_title: str, scenario_path: Path) -> ScenarioAssemblyInput:
        """Create the scenario assembly draft populated with identity and source metadata."""

        return ScenarioAssemblyInput(
            scenario_path=scenario_path,
            scenario_slug=self._build_scenario_slug(scenario_title, scenario_path),
            scenario_name=scenario_title,
            source_format=self.source_format,
        )

    @staticmethod
    def _normalize_section_names(sections: list[MarkdownSection]) -> set[str]:
        """Collect normalized top-level section names for missing-section checks."""

        return {section.name.lower() for section in sections}

    def _route_document_sections(
        self,
        sections: list[MarkdownSection],
        assembly_input: ScenarioAssemblyInput,
        scenario_path: Path,
    ) -> tuple[list[str], list[str], list[str]]:
        """Dispatch all document sections into the appropriate section-level parsers."""

        warnings: list[str] = []
        variable_warnings: list[str] = []
        variable_errors: list[str] = []

        for section in sections:
            self._route_section(
                section,
                assembly_input,
                scenario_path,
                warnings,
                variable_warnings,
                variable_errors,
            )

        return warnings, variable_warnings, variable_errors

    def _route_section(
        self,
        section: MarkdownSection,
        assembly_input: ScenarioAssemblyInput,
        scenario_path: Path,
        warnings: list[str],
        variable_warnings: list[str],
        variable_errors: list[str],
    ) -> None:
        """Route one top-level section into assembly input or compatibility warnings."""

        normalized_name = section.name.lower()

        if normalized_name == "steps":
            step_drafts, step_warnings = self._parse_steps(section, scenario_path)
            assembly_input.step_drafts = step_drafts
            warnings.extend(step_warnings)
            return

        if normalized_name == "variables":
            variable_definitions, section_variable_warnings, section_variable_errors = self._parse_variables(
                section.lines
            )
            assembly_input.variables = variable_definitions
            variable_warnings.extend(section_variable_warnings)
            variable_errors.extend(section_variable_errors)
            # Variable parse warnings historically also surfaced through the general warning channel.
            warnings.extend(section_variable_warnings)
            return

        simple_section_target = self._simple_sections.get(normalized_name)
        if simple_section_target is not None:
            setattr(assembly_input, simple_section_target, parse_section_text(section.lines))
            return

        list_section_target = self._list_sections.get(normalized_name)
        if list_section_target is not None:
            setattr(assembly_input, list_section_target, parse_section_bullets(section.lines))
            return

        warnings.append(f"Unknown scenario section '{section.name}' was ignored.")

    @staticmethod
    def _append_missing_section_warnings(
        assembly_input: ScenarioAssemblyInput,
        normalized_section_names: set[str],
        warnings: list[str],
    ) -> None:
        """Append legacy missing-section warnings after section routing is complete."""

        if not assembly_input.project:
            warnings.append("Section '## Project' is missing or empty.")
        if not assembly_input.environment:
            warnings.append("Section '## Environment' is missing or empty.")
        if "steps" not in normalized_section_names:
            warnings.append("Section '## Steps' is missing.")

    @staticmethod
    def _attach_parse_metadata(
        assembly_input: ScenarioAssemblyInput,
        warnings: list[str],
        variable_warnings: list[str],
        variable_errors: list[str],
    ) -> None:
        """Persist parse-time compatibility messages onto the assembly input metadata draft."""

        assembly_input.parse_warnings = warnings
        assembly_input.variables_parse_warnings = variable_warnings
        assembly_input.variables_validation_errors = variable_errors

    @classmethod
    def _build_scenario_slug(cls, title: str, scenario_path: Path) -> str:
        title_slug = cls._slugify(title)
        path_slug = cls._slugify(scenario_path.stem)
        path_hash = sha1(str(scenario_path).encode("utf-8")).hexdigest()[:8]
        if path_slug and path_slug != title_slug:
            base_slug = f"{title_slug}-{path_slug}-{path_hash}"
        else:
            base_slug = f"{title_slug}-{path_hash}"
        return stable_slug(
            base_slug,
            fallback="scenario",
            max_length=_SCENARIO_SLUG_MAX_LENGTH,
            invalid_chars_re=r"[^a-z0-9]+",
            hash_input=base_slug,
        )

    @staticmethod
    def _slugify(value: str) -> str:
        return stable_slug(
            value,
            fallback="scenario",
            invalid_chars_re=r"[^a-z0-9]+",
        )


