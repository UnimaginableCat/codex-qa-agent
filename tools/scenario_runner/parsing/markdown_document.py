"""Markdown document splitting for scenario sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .errors import ScenarioParseError
from .loader import ScenarioSource
from .markdown_backend import MarkdownBackend, MarkdownBlock, MarkdownItBackend

MARKDOWN_SCENARIO_TITLE_RE = re.compile(r"^#\s+Scenario:\s*(?P<name>.+?)\s*$")


@dataclass(frozen=True, slots=True)
class MarkdownSection:
    """Top-level markdown section captured from a scenario document."""

    name: str
    line_number: int
    lines: list[str]


@dataclass(frozen=True, slots=True)
class MarkdownScenarioDocument:
    """Early parsed markdown scenario document before domain conversion."""

    source: ScenarioSource
    title: str
    sections: list[MarkdownSection]


def parse_markdown_document_from_backend(
    source: ScenarioSource,
    backend: MarkdownBackend | None = None,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> MarkdownScenarioDocument:
    """Build a legacy-shaped markdown document using a markdown backend."""

    token_document = (backend or MarkdownItBackend()).parse(source)
    headings = [
        block
        for block in token_document.headings
        if block.line_span is not None and block.heading_level in {1, 2}
    ]
    title = _title_from_backend_headings(headings, source.path, error_type=error_type)
    sections = _sections_from_backend_headings(source, headings, error_type=error_type)
    return MarkdownScenarioDocument(source=source, title=title, sections=sections)


def _title_from_backend_headings(
    headings: list[MarkdownBlock],
    scenario_path: Path,
    error_type: type[ScenarioParseError],
) -> str:
    title: str | None = None
    title_line_number = 0
    for heading in headings:
        if heading.heading_level != 1:
            continue
        match = MARKDOWN_SCENARIO_TITLE_RE.match(f"# {heading.content}")
        if match is None:
            continue
        line_number = heading.line_span.line_start if heading.line_span is not None else 0
        if title is not None:
            raise error_type(
                f"Scenario '{scenario_path}' is malformed: duplicate '# Scenario:' title "
                f"at line {line_number}; first declared at line {title_line_number}."
            )
        title = match.group("name").strip()
        title_line_number = line_number

    if title is not None:
        return title

    raise error_type(f"Scenario '{scenario_path}' is malformed: missing '# Scenario: ...' title.")


def _sections_from_backend_headings(
    source: ScenarioSource,
    headings: list[MarkdownBlock],
    error_type: type[ScenarioParseError],
) -> list[MarkdownSection]:
    sections: list[MarkdownSection] = []
    seen_sections: dict[str, int] = {}
    section_headings = [heading for heading in headings if heading.heading_level == 2]

    for index, heading in enumerate(section_headings):
        if heading.line_span is None:
            continue
        section_name = heading.content.strip()
        line_number = heading.line_span.line_start
        normalized_name = section_name.lower()
        if normalized_name in seen_sections:
            raise error_type(
                f"Duplicate top-level section '## {section_name}' at line {line_number}; "
                f"first declared at line {seen_sections[normalized_name]}."
            )
        seen_sections[normalized_name] = line_number

        next_heading = section_headings[index + 1] if index + 1 < len(section_headings) else None
        section_end_line = (
            next_heading.line_span.line_start - 1
            if next_heading is not None and next_heading.line_span is not None
            else len(source.lines)
        )
        sections.append(
            MarkdownSection(
                name=section_name,
                line_number=line_number,
                lines=source.lines[line_number:section_end_line],
            )
        )

    return sections

