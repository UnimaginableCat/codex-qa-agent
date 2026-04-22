"""Markdown document splitting for scenario sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .errors import ScenarioParseError
from .loader import ScenarioSource
from .markdown_backend import MarkdownBackend, MarkdownBlock, MarkdownItBackend

MARKDOWN_STEP_RE = re.compile(r"^###\s+Step\s+(?P<number>\d+)\s*$", re.IGNORECASE)
MARKDOWN_SCENARIO_TITLE_RE = re.compile(r"^#\s+Scenario:\s*(?P<name>.+?)\s*$")


@dataclass(frozen=True, slots=True)
class MarkdownSection:
    """Top-level markdown section captured from a scenario document."""

    name: str
    line_number: int
    lines: list[str]


@dataclass(frozen=True, slots=True)
class MarkdownStepBlock:
    """Raw markdown lines for one scenario step before field-level parsing."""

    step_number: int
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


def split_step_blocks(
    section: MarkdownSection,
    scenario_path: Path,
) -> tuple[list[MarkdownStepBlock], list[str]]:
    step_blocks: list[MarkdownStepBlock] = []
    current_step_number: int | None = None
    current_step_line_number = 0
    current_block: list[str] = []
    warnings: list[str] = []
    inside_fence = False

    for offset, line in enumerate(section.lines, start=1):
        stripped_line = line.strip()
        if is_fence_line(stripped_line):
            inside_fence = not inside_fence

        match = MARKDOWN_STEP_RE.match(stripped_line) if not inside_fence else None
        if match:
            if current_step_number is not None:
                step_blocks.append(
                    MarkdownStepBlock(
                        step_number=current_step_number,
                        line_number=current_step_line_number,
                        lines=current_block,
                    )
                )
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
        step_blocks.append(
            MarkdownStepBlock(
                step_number=current_step_number,
                line_number=current_step_line_number,
                lines=current_block,
            )
        )

    return step_blocks, warnings


def is_fence_line(line: str) -> bool:
    return line.startswith("```")
