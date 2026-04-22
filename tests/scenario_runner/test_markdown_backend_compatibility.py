from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.scenario_runner.parser import ScenarioParseError
from tools.scenario_runner.parsing.loader import load_scenario_source
from tools.scenario_runner.parsing.markdown_document import (
    MarkdownScenarioDocument,
    parse_markdown_document_from_backend,
)
from tools.scenario_runner.parsing.step_blocks import split_step_blocks


class MarkdownBackendDocumentRegressionTests(unittest.TestCase):
    def test_representative_scenario_document_shape_is_stable(self) -> None:
        document = _parse_backend(
            """
            # Scenario: Compatibility

            ## Project
            code/demo

            ## Environment
            env/demo.env

            ## Notes
            Optional notes.

            ## Preconditions
            - API is running
            - DB is reachable

            ## Steps

            ### Step 1
            Type: api
            Name: create
            Method: POST
            Path: /items
            Body:
            ```json
            {
              "name": "abc"
            }
            ```
            Expected:
            - HTTP 200

            ### Step 2
            Type: db
            Name: verify
            SQL:
            ```sql
            SELECT id FROM items
            WHERE name = :name
            ```
            Params:
            ```json
            {"name": "abc"}
            ```

            ## Final expectations
            - all steps pass
            """,
        )

        self.assertEqual(
            _document_signature(document),
            {
                "title": "Compatibility",
                "sections": [
                    {"name": "Project", "line_number": 3, "line_count": 2},
                    {"name": "Environment", "line_number": 6, "line_count": 2},
                    {"name": "Notes", "line_number": 9, "line_count": 2},
                    {"name": "Preconditions", "line_number": 12, "line_count": 3},
                    {"name": "Steps", "line_number": 16, "line_count": 28},
                    {"name": "Final expectations", "line_number": 45, "line_count": 2},
                ],
            },
        )
        self.assertEqual(
            _step_signature(document),
            {
                "warnings": [],
                "steps": [
                    {"step_number": 1, "line_number": 2, "line_count": 13},
                    {"step_number": 2, "line_number": 16, "line_count": 12},
                ],
            },
        )

    def test_heading_like_text_inside_fences_does_not_create_sections_or_steps(self) -> None:
        document = _parse_backend(
            """
            # Scenario: Fenced Headings

            ## Notes
            ```text
            ## Not A Section
            ### Step 99
            # Scenario: Not A Scenario
            ```

            ## Steps

            ### Step 1
            Type: db
            Name: verify
            SQL:
            ```sql
            -- ## Not A Section
            -- ### Step 88
            SELECT 1
            ```
            """,
        )

        self.assertEqual(
            _document_signature(document),
            {
                "title": "Fenced Headings",
                "sections": [
                    {"name": "Notes", "line_number": 3, "line_count": 6},
                    {"name": "Steps", "line_number": 10, "line_count": 11},
                ],
            },
        )
        self.assertEqual(
            _step_signature(document),
            {
                "warnings": [],
                "steps": [{"step_number": 1, "line_number": 2, "line_count": 9}],
            },
        )

    def test_empty_lines_lists_and_multiple_steps_keep_stable_boundaries(self) -> None:
        document = _parse_backend(
            """
            # Scenario: Spacing And Lists


            ## Preconditions

            - first precondition

            - second precondition

            ## Steps

            setup text before first step

            ### Step 1
            Type: api
            Name: first
            Method: GET
            Path: /first
            Expected:
            - HTTP 200
            - response contains field "id"

            ### Step 2
            Type: api
            Name: second
            Method: POST
            Path: /second
            Headers:
            ```json
            {"X-Step": "2"}
            ```

            ## Report output
            artifacts/agent/report.md
            """,
        )

        self.assertEqual(
            _document_signature(document),
            {
                "title": "Spacing And Lists",
                "sections": [
                    {"name": "Preconditions", "line_number": 4, "line_count": 5},
                    {"name": "Steps", "line_number": 10, "line_count": 22},
                    {"name": "Report output", "line_number": 33, "line_count": 2},
                ],
            },
        )
        self.assertEqual(
            _step_signature(document),
            {
                "warnings": ["Ignored content before first step in 'scenario.md': 'setup text before first step'"],
                "steps": [
                    {"step_number": 1, "line_number": 4, "line_count": 8},
                    {"step_number": 2, "line_number": 13, "line_count": 9},
                ],
            },
        )

    def test_duplicate_section_error_is_stable(self) -> None:
        with self.assertRaisesRegex(ScenarioParseError, "Duplicate top-level section") as error:
            _parse_backend(
                """
                # Scenario: Duplicate

                ## Project
                code/demo

                ## Project
                code/other
                """,
            )

        self.assertIn("first declared at line 3", str(error.exception))
        self.assertIn("at line 6", str(error.exception))

    def test_missing_title_error_is_stable(self) -> None:
        with TemporaryDirectory() as tmp:
            source = _write_source(
                Path(tmp),
                """
                ## Project
                code/demo
                """,
            )

            with self.assertRaisesRegex(ScenarioParseError, "missing '# Scenario: ...' title"):
                parse_markdown_document_from_backend(source, error_type=ScenarioParseError)


def _parse_backend(content: str) -> MarkdownScenarioDocument:
    with TemporaryDirectory() as tmp:
        source = _write_source(Path(tmp), content)
        return parse_markdown_document_from_backend(source, error_type=ScenarioParseError)


def _document_signature(document: MarkdownScenarioDocument):
    return {
        "title": document.title,
        "sections": [
            {
                "name": section.name,
                "line_number": section.line_number,
                "line_count": len(section.lines),
            }
            for section in document.sections
        ],
    }


def _step_signature(document: MarkdownScenarioDocument):
    steps_section = next((section for section in document.sections if section.name.lower() == "steps"), None)
    if steps_section is None:
        return {"warnings": [], "steps": []}
    step_blocks, warnings = split_step_blocks(steps_section, document.source.path)
    return {
        "warnings": warnings,
        "steps": [
            {
                "step_number": block.step_number,
                "line_number": block.line_number,
                "line_count": len(block.lines),
            }
            for block in step_blocks
        ],
    }


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
