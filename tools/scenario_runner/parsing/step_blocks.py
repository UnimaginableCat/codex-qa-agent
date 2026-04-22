"""Step boundary detection for scenario markdown sections."""

from __future__ import annotations

from pathlib import Path
import re

from .markdown_document import MarkdownSection
from .step_ir import StepBlock

MARKDOWN_STEP_RE = re.compile(r"^###\s+Step\s+(?P<number>\d+)\s*$", re.IGNORECASE)


def split_step_blocks(
    section: MarkdownSection,
    scenario_path: Path,
) -> tuple[list[StepBlock], list[str]]:
    """Split a Steps section into raw step blocks using H3 step headings."""

    step_blocks: list[StepBlock] = []
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
                    StepBlock(
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
            StepBlock(
                step_number=current_step_number,
                line_number=current_step_line_number,
                lines=current_block,
            )
        )

    return step_blocks, warnings


def is_fence_line(line: str) -> bool:
    """Return whether a stripped markdown line starts a fenced block boundary."""

    return line.startswith("```")
