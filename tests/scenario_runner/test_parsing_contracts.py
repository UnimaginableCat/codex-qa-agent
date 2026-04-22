from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.scenario_runner.models import ScenarioDefinition
from tools.scenario_runner.parser import MarkdownScenarioParser, ScenarioParseError
from tools.scenario_runner.parsing import (
    ParseDiagnostic,
    ParseDiagnosticKind,
    ParseDiagnosticSeverity,
    ScenarioParseOptions,
    ScenarioParseResult,
    ScenarioParser,
    ScenarioParsingError,
    SourceLocation,
)


class ParsingContractTests(unittest.TestCase):
    def test_parse_result_reports_warning_error_and_fatal_helpers(self) -> None:
        source_path = Path("scenarios/demo.md")
        result = ScenarioParseResult(
            scenario=None,
            source_format="markdown",
            source_path=source_path,
            diagnostics=[
                ParseDiagnostic(
                    severity=ParseDiagnosticSeverity.WARNING,
                    code="scenario.warning",
                    message="warning",
                    kind=ParseDiagnosticKind.STRUCTURE,
                    location=SourceLocation(path=source_path, line=3, section="Project"),
                ),
                ParseDiagnostic(
                    severity=ParseDiagnosticSeverity.ERROR,
                    code="scenario.error",
                    message="error",
                    kind=ParseDiagnosticKind.VALIDATION,
                ),
                ParseDiagnostic(
                    severity=ParseDiagnosticSeverity.FATAL,
                    code="scenario.fatal",
                    message="fatal",
                    kind=ParseDiagnosticKind.SYNTAX,
                ),
            ],
        )

        self.assertTrue(result.has_errors)
        self.assertTrue(result.has_fatal_errors)
        self.assertEqual([diagnostic.code for diagnostic in result.warnings], ["scenario.warning"])
        self.assertEqual([diagnostic.code for diagnostic in result.errors], ["scenario.error", "scenario.fatal"])
        self.assertEqual(result.to_dict()["source_path"], str(source_path))
        self.assertEqual(result.to_dict()["diagnostics"][0]["location"]["line"], 3)

    def test_scenario_parser_protocol_accepts_new_contract_implementation(self) -> None:
        parser = _ContractParser()

        result = parser.parse(Path("scenario.md"), options=ScenarioParseOptions(strict=True))

        self.assertIsInstance(parser, ScenarioParser)
        self.assertIsInstance(result, ScenarioParseResult)
        self.assertEqual(result.source_format, "test")

    def test_legacy_markdown_parser_public_api_still_returns_scenario_definition(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(
                Path(tmp),
                """
                # Scenario: Contract Compatibility

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Steps

                ### Step 1
                Type: api
                Name: fetch
                Method: GET
                Path: /demo
                """,
            )

            scenario = MarkdownScenarioParser().parse(scenario_path)

        self.assertIsInstance(scenario, ScenarioDefinition)
        self.assertEqual(scenario.metadata["source_format"], "markdown")
        self.assertIn("parse_warnings", scenario.metadata)
        self.assertIn("variables_parse_warnings", scenario.metadata)
        self.assertIn("variables_validation_errors", scenario.metadata)
        self.assertTrue(scenario.scenario_slug.startswith("contract-compatibility-"))
        self.assertEqual(scenario.steps[0].metadata["source_line"], 2)

    def test_legacy_markdown_parser_can_emit_new_parse_result_without_changing_parse(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(
                Path(tmp),
                """
                # Scenario: Parse Result Bridge

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - run_suffix = generated:run_suffix
                - email_suffix = derived:run_suffix|slugify

                ## Steps

                ### Step 1
                Type: api
                Name: fetch
                Method: GET
                Path: /demo/{{email_suffix}}
                """,
            )

            parser = MarkdownScenarioParser()
            legacy_scenario = parser.parse(scenario_path)
            result = parser.parse_result(scenario_path)

        self.assertIsNotNone(result.scenario)
        self.assertEqual(result.scenario.to_dict(), legacy_scenario.to_dict())
        self.assertTrue(result.has_errors)
        self.assertFalse(result.has_fatal_errors)
        self.assertTrue(
            any(diagnostic.code == "scenario.variables_validation_error" for diagnostic in result.diagnostics)
        )

    def test_legacy_parse_error_is_parse_subsystem_error(self) -> None:
        error = ScenarioParseError("bad scenario")

        self.assertIsInstance(error, ScenarioParsingError)


class _ContractParser:
    source_format = "test"

    def parse(
        self,
        source: Path,
        options: ScenarioParseOptions | None = None,
    ) -> ScenarioParseResult:
        del options
        return ScenarioParseResult(scenario=None, source_format=self.source_format, source_path=source)


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
