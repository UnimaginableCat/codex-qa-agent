from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.scenario_runner.parsing.markdown.backend import (
    MarkdownBlock,
    MarkdownBlockKind,
    MarkdownItBackend,
)
from tools.scenario_runner.parsing.source.loader import load_scenario_source


class MarkdownItBackendTests(unittest.TestCase):
    def test_headings_are_normalized_with_levels_and_line_spans(self) -> None:
        with TemporaryDirectory() as tmp:
            source = _write_source(
                Path(tmp),
                """
                # Scenario: Backend

                ## Project
                code/demo

                ## Steps

                ### Step 1
                Type: api
                """,
            )

            document = MarkdownItBackend().parse(source)

        headings = document.headings
        self.assertEqual([heading.heading_level for heading in headings], [1, 2, 2, 3])
        self.assertEqual([heading.content for heading in headings], [
            "Scenario: Backend",
            "Project",
            "Steps",
            "Step 1",
        ])
        self.assertEqual(headings[0].line_span.line_start, 1)
        self.assertEqual(headings[0].line_span.line_end, 1)
        self.assertEqual(headings[-1].line_span.line_start, 8)

    def test_fenced_code_is_normalized_and_inner_heading_text_is_not_heading(self) -> None:
        with TemporaryDirectory() as tmp:
            source = _write_source(
                Path(tmp),
                """
                # Scenario: Fences

                ## Steps

                ### Step 1
                Type: db
                SQL:
                ```sql
                ## Not a section
                ### Not a step
                SELECT 1
                ```
                """,
            )

            document = MarkdownItBackend().parse(source)

        headings = document.headings
        fences = document.blocks_by_kind(MarkdownBlockKind.FENCE)
        self.assertEqual([heading.content for heading in headings], ["Scenario: Fences", "Steps", "Step 1"])
        self.assertEqual(len(fences), 1)
        self.assertEqual(fences[0].fence_info, "sql")
        self.assertIn("## Not a section", fences[0].content)
        self.assertIn("### Not a step", fences[0].content)
        self.assertEqual(fences[0].line_span.line_start, 8)
        self.assertEqual(fences[0].line_span.line_end, 12)

    def test_paragraph_and_list_blocks_are_exposed_without_library_tokens(self) -> None:
        with TemporaryDirectory() as tmp:
            source = _write_source(
                Path(tmp),
                """
                # Scenario: Blocks

                ## Preconditions
                - API is running
                - DB is reachable

                ## Notes
                Plain note paragraph.
                """,
            )

            document = MarkdownItBackend().parse(source)

        block_types = {type(block) for block in document.blocks}
        self.assertEqual(block_types, {MarkdownBlock})
        self.assertTrue(document.blocks_by_kind(MarkdownBlockKind.BULLET_LIST))
        self.assertEqual(
            [block.content for block in document.blocks_by_kind(MarkdownBlockKind.PARAGRAPH)],
            ["API is running", "DB is reachable", "Plain note paragraph."],
        )
        self.assertFalse(any(type(block).__module__.startswith("markdown_it") for block in document.blocks))


def _write_source(root: Path, content: str):
    root.mkdir(parents=True, exist_ok=True)
    scenario_path = root / "scenario.md"
    scenario_path.write_text(_dedent(content), encoding="utf-8")
    return load_scenario_source(scenario_path)


def _dedent(value: str) -> str:
    lines = value.strip("\n").splitlines()
    non_empty_lines = [line for line in lines if line.strip()]
    indent = min((len(line) - len(line.lstrip())) for line in non_empty_lines) if non_empty_lines else 0
    return "\n".join(line[indent:] for line in lines) + "\n"


if __name__ == "__main__":
    unittest.main()
