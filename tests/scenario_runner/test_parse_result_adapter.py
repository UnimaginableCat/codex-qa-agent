from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.scenario_runner.models import ScenarioDefinition
from tools.scenario_runner.parser import ScenarioParseError
from tools.scenario_runner.parsing import (
    ParseDiagnosticKind,
    ParseDiagnosticSeverity,
    adapt_legacy_parse_result,
    build_legacy_parse_diagnostics,
    build_parse_failure_diagnostic,
)


class ParseResultAdapterTests(unittest.TestCase):
    def test_diagnostics_bridge_maps_legacy_metadata_into_structured_diagnostics(self) -> None:
        scenario = ScenarioDefinition(
            scenario_path=Path("scenarios/demo.md"),
            scenario_slug="demo-scenario",
            scenario_name="Demo Scenario",
            metadata={
                "parse_warnings": [
                    "Unknown scenario section 'Extra' was ignored.",
                    "Variables section used best-effort parsing for 'company_guid' at relative line 1.",
                ],
                "variables_parse_warnings": [
                    "Variables section used best-effort parsing for 'company_guid' at relative line 1.",
                ],
                "variables_validation_errors": [
                    "Variables section has invalid definition for 'email_suffix' at relative line 2: unsupported transform(s): slugify",
                ],
                "source_format": "markdown",
            },
        )

        diagnostics = build_legacy_parse_diagnostics(scenario)

        self.assertEqual(len(diagnostics), 3)
        self.assertEqual(
            [(diagnostic.code, diagnostic.severity, diagnostic.kind) for diagnostic in diagnostics],
            [
                ("scenario.parse_warning", ParseDiagnosticSeverity.WARNING, ParseDiagnosticKind.COMPATIBILITY),
                ("scenario.parse_warning", ParseDiagnosticSeverity.WARNING, ParseDiagnosticKind.COMPATIBILITY),
                (
                    "scenario.variables_validation_error",
                    ParseDiagnosticSeverity.ERROR,
                    ParseDiagnosticKind.VALIDATION,
                ),
            ],
        )
        self.assertEqual(diagnostics[0].location.path, Path("scenarios/demo.md"))
        self.assertEqual(diagnostics[2].location.section, "Variables")

    def test_parse_failure_diagnostic_is_fatal_and_uses_source_path(self) -> None:
        diagnostic = build_parse_failure_diagnostic(Path("scenarios/missing.md"), "Scenario file does not exist")

        self.assertEqual(diagnostic.severity, ParseDiagnosticSeverity.FATAL)
        self.assertEqual(diagnostic.code, "scenario.parse_failed")
        self.assertEqual(diagnostic.kind, ParseDiagnosticKind.SYNTAX)
        self.assertEqual(diagnostic.location.path, Path("scenarios/missing.md"))

    def test_parse_result_adapter_wraps_success_with_stable_result_contract(self) -> None:
        scenario = ScenarioDefinition(
            scenario_path=Path("scenarios/demo.md"),
            scenario_slug="demo-scenario",
            scenario_name="Demo Scenario",
            metadata={
                "parse_warnings": ["Unknown scenario section 'Extra' was ignored."],
                "variables_parse_warnings": [],
                "variables_validation_errors": [
                    "Variables section has invalid definition for 'email_suffix' at relative line 2: unsupported transform(s): slugify",
                ],
                "source_format": "markdown",
            },
        )

        result = adapt_legacy_parse_result(
            lambda path: scenario,
            Path("ignored.md"),
            source_format="markdown",
            error_type=ScenarioParseError,
        )

        self.assertIs(result.scenario, scenario)
        self.assertEqual(result.source_path, Path("scenarios/demo.md"))
        self.assertEqual(result.source_format, "markdown")
        self.assertTrue(result.has_errors)
        self.assertFalse(result.has_fatal_errors)
        self.assertEqual([diagnostic.code for diagnostic in result.warnings], ["scenario.parse_warning"])
        self.assertEqual(
            [diagnostic.code for diagnostic in result.errors],
            ["scenario.variables_validation_error"],
        )

    def test_parse_result_adapter_wraps_parse_failure_as_fatal_result(self) -> None:
        result = adapt_legacy_parse_result(
            lambda path: (_ for _ in ()).throw(ScenarioParseError("bad scenario")),
            Path("scenarios/bad.md"),
            source_format="markdown",
            error_type=ScenarioParseError,
        )

        self.assertIsNone(result.scenario)
        self.assertEqual(result.source_path, Path("scenarios/bad.md"))
        self.assertEqual(result.source_format, "markdown")
        self.assertTrue(result.has_errors)
        self.assertTrue(result.has_fatal_errors)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].code, "scenario.parse_failed")


if __name__ == "__main__":
    unittest.main()
