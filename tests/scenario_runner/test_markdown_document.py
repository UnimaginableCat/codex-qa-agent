from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.scenario_runner.parser import MarkdownScenarioParser, ScenarioParseError
from tools.scenario_runner.parsing.loader import load_scenario_source
from tools.scenario_runner.parsing.markdown_document import (
    parse_markdown_document,
    split_step_blocks,
)


class MarkdownDocumentParsingTests(unittest.TestCase):
    def test_loader_reads_utf8_source_and_missing_path_uses_legacy_error_type(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_path = root / "scenario.md"
            scenario_path.write_text("# Scenario: UTF8\n\n## Notes\nhello\n", encoding="utf-8")

            source = load_scenario_source(scenario_path, error_type=ScenarioParseError)

            self.assertEqual(source.path, scenario_path.resolve())
            self.assertIn("hello", source.text)
            with self.assertRaisesRegex(ScenarioParseError, "Scenario file does not exist"):
                load_scenario_source(root / "missing.md", error_type=ScenarioParseError)

    def test_document_split_ignores_markdown_markers_inside_fences(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(
                Path(tmp),
                """
                # Scenario: Fenced Sections

                ## Project
                code/demo

                ## Notes
                ```text
                ## Not A Real Section
                # Scenario: Not A Real Title
                ```

                ## Steps

                ### Step 1
                Type: db
                Name: verify
                SQL:
                ```sql
                -- ### Step 99
                SELECT 1
                ```
                """,
            )

            document = parse_markdown_document(
                load_scenario_source(scenario_path, error_type=ScenarioParseError),
                error_type=ScenarioParseError,
            )
            steps_section = next(section for section in document.sections if section.name == "Steps")
            step_blocks, warnings = split_step_blocks(steps_section, scenario_path)

        self.assertEqual(document.title, "Fenced Sections")
        self.assertEqual([section.name for section in document.sections], ["Project", "Notes", "Steps"])
        self.assertEqual([block.step_number for block in step_blocks], [1])
        self.assertEqual(step_blocks[0].line_number, 2)
        self.assertFalse(warnings)

    def test_legacy_parser_output_shape_is_stable_for_api_db_scenario(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(
                Path(tmp),
                """
                # Scenario: Output Shape

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - company_guid = env:COMPANY_GUID
                - run_suffix = generated:run_suffix
                - generated_name = template:Item {{run_suffix}}

                ## Steps

                ### Step 1
                Type: api
                Name: create
                Method: post
                Path: /companies/{{company_guid}}/items
                Headers:
                ```json
                {"Content-Type": "application/json"}
                ```
                Body:
                ```json
                {"name": "{{generated_name}}"}
                ```
                Capture:
                - response.body.id -> created_id
                Expected:
                - HTTP 200

                ### Step 2
                Type: db
                Name: verify
                SQL:
                ```sql
                SELECT id FROM items WHERE id = :id
                ```
                Params:
                ```json
                {"id": "{{created_id}}"}
                ```
                Expected:
                - one row exists
                """,
            )

            scenario = MarkdownScenarioParser().parse(scenario_path)
            payload = scenario.to_dict()

        self.assertEqual(payload["scenario_name"], "Output Shape")
        self.assertTrue(payload["scenario_slug"].startswith("output-shape-"))
        self.assertEqual(payload["project"], "code/demo")
        self.assertEqual(payload["environment"], "env/demo.env")
        self.assertEqual(
            sorted(payload["metadata"].keys()),
            ["parse_warnings", "source_format", "variables_parse_warnings", "variables_validation_errors"],
        )
        self.assertEqual(payload["metadata"]["source_format"], "markdown")
        self.assertEqual([variable["name"] for variable in payload["variables"]], [
            "company_guid",
            "run_suffix",
            "generated_name",
        ])
        self.assertEqual([step["step_id"] for step in payload["steps"]], ["step-1", "step-2"])
        self.assertEqual([step["step_type"] for step in payload["steps"]], ["api", "db"])
        self.assertEqual(payload["steps"][0]["metadata"]["source_line"], 2)
        self.assertEqual(payload["steps"][1]["metadata"]["source_line"], 20)
        self.assertEqual(payload["steps"][0]["api"]["method"], "POST")
        self.assertEqual(payload["steps"][0]["api"]["headers"]["Content-Type"], "application/json")
        self.assertEqual(payload["steps"][0]["api"]["capture"], ["response.body.id -> created_id"])
        self.assertEqual(payload["steps"][1]["db"]["sql"], "SELECT id FROM items WHERE id = :id")
        self.assertEqual(payload["steps"][1]["db"]["params"], {"id": "{{created_id}}"})


def _write_scenario(root: Path, content: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    scenario_path = root / "scenario.md"
    scenario_path.write_text(_dedent(content), encoding="utf-8")
    return scenario_path


def _dedent(value: str) -> str:
    lines = value.strip("\n").splitlines()
    non_empty_lines = [line for line in lines if line.strip()]
    indent = min((len(line) - len(line.lstrip())) for line in non_empty_lines) if non_empty_lines else 0
    return "\n".join(line[indent:] for line in lines) + "\n"


if __name__ == "__main__":
    unittest.main()
