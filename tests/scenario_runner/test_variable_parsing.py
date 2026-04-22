from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.scenario_runner.domain.models import ScenarioVariableSource
from tools.scenario_runner.parser import MarkdownScenarioParser, ScenarioParseError
from tools.scenario_runner.parsing.variables.parser import parse_variables_section


class VariableParsingTests(unittest.TestCase):
    def test_parse_simple_machine_readable_variables(self) -> None:
        result = parse_variables_section(
            [
                "- company_guid = env:COMPANY_GUID",
                "- run_suffix = generated:run_suffix",
                "- generated_name = template:Item {{run_suffix}}",
                '- literal_name = "Fixed literal"',
            ],
            error_type=ScenarioParseError,
        )

        self.assertEqual(result.warnings, [])
        self.assertEqual(result.errors, [])
        self.assertEqual([item.name for item in result.definitions], [
            "company_guid",
            "run_suffix",
            "generated_name",
            "literal_name",
        ])
        self.assertEqual([item.source for item in result.definitions], [
            ScenarioVariableSource.ENV,
            ScenarioVariableSource.GENERATED,
            ScenarioVariableSource.TEMPLATE,
            ScenarioVariableSource.LITERAL,
        ])
        self.assertEqual(result.definitions[0].env_name, "COMPANY_GUID")
        self.assertEqual(result.definitions[2].raw_value, "Item {{run_suffix}}")
        self.assertEqual(result.definitions[3].raw_value, "Fixed literal")

    def test_parse_typed_values_and_placeholder_preservation(self) -> None:
        result = parse_variables_section(
            [
                "- run_suffix = generated:run_suffix",
                "- email_suffix = derived:{{run_suffix}}|lower",
                "- primary_email = template:autotest.primary.{{email_suffix}}@example.com",
            ],
            error_type=ScenarioParseError,
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.definitions[1].source, ScenarioVariableSource.DERIVED)
        self.assertEqual(result.definitions[1].source_name, "run_suffix")
        self.assertEqual(result.definitions[1].transforms, ["lower"])
        self.assertEqual(
            result.definitions[2].raw_value,
            "autotest.primary.{{email_suffix}}@example.com",
        )

    def test_table_and_best_effort_parsing_preserve_warnings(self) -> None:
        result = parse_variables_section(
            [
                "| Variable | Source | Env | Value |",
                "| --- | --- | --- | --- |",
                "| company_guid | env | COMPANY_GUID | |",
                "| unique_suffix | generated | | run_suffix |",
                "| generated_name | template | | AUTOTEST {{unique_suffix}} |",
            ],
            error_type=ScenarioParseError,
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(
            result.warnings,
            [
                "Variables section used best-effort parsing for 'company_guid' at relative line 3.",
                "Variables section used best-effort parsing for 'unique_suffix' at relative line 4.",
                "Variables section used best-effort parsing for 'generated_name' at relative line 5.",
            ],
        )
        self.assertEqual([item.name for item in result.definitions], [
            "company_guid",
            "unique_suffix",
            "generated_name",
        ])

    def test_duplicate_variable_keeps_first_and_reports_error(self) -> None:
        result = parse_variables_section(
            [
                "- company_guid = env:COMPANY_GUID",
                "- company_guid = env:OTHER_GUID",
            ],
            error_type=ScenarioParseError,
        )

        self.assertEqual(len(result.definitions), 1)
        self.assertEqual(result.definitions[0].env_name, "COMPANY_GUID")
        self.assertEqual(
            result.errors,
            ["Variables section contains duplicate variable 'company_guid' at relative line 2; first definition was kept."],
        )

    def test_malformed_variable_line_reports_compatibility_error(self) -> None:
        result = parse_variables_section(
            [
                "- company_guid comes from environment",
                "- @@@ this is not a variable definition",
            ],
            error_type=ScenarioParseError,
        )

        self.assertEqual(result.definitions, [])
        self.assertEqual(len(result.errors), 2)
        self.assertIn("unsupported or ambiguous content at relative line 1", result.errors[0])
        self.assertIn("company_guid comes from environment", result.errors[0])
        self.assertIn("@@@ this is not a variable definition", result.errors[1])

    def test_validation_errors_preserve_existing_messages(self) -> None:
        result = parse_variables_section(
            [
                "- run_suffix = generated:run_suffix",
                "- email_suffix = derived:run_suffix|slugify",
                "- empty_value =",
            ],
            error_type=ScenarioParseError,
        )

        self.assertEqual([item.name for item in result.definitions], ["run_suffix"])
        self.assertEqual(len(result.errors), 2)
        self.assertIn("unsupported transform(s): slugify", result.errors[0])
        self.assertIn("empty variable definitions are not supported", result.errors[1])

    def test_backticks_and_dash_assignments_stay_compatible(self) -> None:
        result = parse_variables_section(
            [
                '- `literal_name`: "Fixed literal"',
                "- dashed_template вЂ” Item {{run_suffix}}",
            ],
            error_type=ScenarioParseError,
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(
            [(item.name, item.raw_value, item.source) for item in result.definitions],
            [
                ("literal_name", "Fixed literal", ScenarioVariableSource.LITERAL),
                ("dashed_template", "Item {{run_suffix}}", ScenarioVariableSource.TEMPLATE),
            ],
        )

    def test_parser_metadata_shape_stays_compatible_with_variable_errors(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(
                Path(tmp),
                """
                # Scenario: Variables Metadata

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - run_suffix = generated:run_suffix
                - email_suffix = the lowercase form of `run_suffix`

                ## Steps

                ### Step 1
                Type: api
                Name: first
                Method: GET
                Path: /users/{{email_suffix}}
                """,
            )

            scenario = MarkdownScenarioParser().parse(scenario_path)

        self.assertEqual(
            sorted(scenario.metadata),
            ["parse_warnings", "source_format", "variables_parse_warnings", "variables_validation_errors"],
        )
        self.assertEqual(scenario.metadata["variables_parse_warnings"], [])
        self.assertEqual(len(scenario.metadata["variables_validation_errors"]), 1)
        self.assertIn("ambiguous untyped value", scenario.metadata["variables_validation_errors"][0])
        self.assertEqual(scenario.steps[0].api.path, "/users/{{email_suffix}}")


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
