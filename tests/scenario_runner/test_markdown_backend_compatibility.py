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
    parse_markdown_document,
    parse_markdown_document_from_backend,
    split_step_blocks,
)


class MarkdownBackendCompatibilityTests(unittest.TestCase):
    def test_representative_scenario_document_matches_legacy_splitter(self) -> None:
        legacy, backend = _parse_both(
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

        self.assertEqual(_document_signature(backend), _document_signature(legacy))
        self.assertEqual(_step_signature(backend), _step_signature(legacy))

    def test_heading_like_text_inside_fences_does_not_create_sections_or_steps(self) -> None:
        legacy, backend = _parse_both(
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

        self.assertEqual(_document_signature(backend), _document_signature(legacy))
        self.assertEqual(_step_signature(backend), _step_signature(legacy))

    def test_empty_lines_lists_and_multiple_steps_match_legacy_splitter(self) -> None:
        legacy, backend = _parse_both(
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

        self.assertEqual(_document_signature(backend), _document_signature(legacy))
        self.assertEqual(_step_signature(backend), _step_signature(legacy))

    def test_duplicate_section_error_matches_legacy_message(self) -> None:
        with self.assertRaisesRegex(ScenarioParseError, "Duplicate top-level section") as legacy_error:
            _parse_legacy(
                """
                # Scenario: Duplicate

                ## Project
                code/demo

                ## Project
                code/other
                """,
            )

        with self.assertRaisesRegex(ScenarioParseError, "Duplicate top-level section") as backend_error:
            _parse_backend(
                """
                # Scenario: Duplicate

                ## Project
                code/demo

                ## Project
                code/other
                """,
            )

        self.assertEqual(str(backend_error.exception), str(legacy_error.exception))

    def test_missing_title_error_matches_legacy_message(self) -> None:
        with TemporaryDirectory() as tmp:
            source = _write_source(
                Path(tmp),
                """
                ## Project
                code/demo
                """,
            )

            with self.assertRaisesRegex(ScenarioParseError, "missing '# Scenario: ...' title") as legacy_error:
                parse_markdown_document(source, error_type=ScenarioParseError)

            with self.assertRaisesRegex(ScenarioParseError, "missing '# Scenario: ...' title") as backend_error:
                parse_markdown_document_from_backend(source, error_type=ScenarioParseError)

        self.assertEqual(str(backend_error.exception), str(legacy_error.exception))


def _parse_both(content: str) -> tuple[MarkdownScenarioDocument, MarkdownScenarioDocument]:
    with TemporaryDirectory() as tmp:
        source = _write_source(Path(tmp), content)
        return (
            parse_markdown_document(source, error_type=ScenarioParseError),
            parse_markdown_document_from_backend(source, error_type=ScenarioParseError),
        )


def _parse_legacy(content: str) -> MarkdownScenarioDocument:
    with TemporaryDirectory() as tmp:
        source = _write_source(Path(tmp), content)
        return parse_markdown_document(source, error_type=ScenarioParseError)


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
                "lines": list(section.lines),
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
                "lines": list(block.lines),
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
