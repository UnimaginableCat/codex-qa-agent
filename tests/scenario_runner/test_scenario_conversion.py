from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.scenario_runner.domain.models import (
    ScenarioDefinition,
    ScenarioStepType,
    ScenarioVariableDefinition,
    ScenarioVariableSource,
)
from tools.scenario_runner.parser import ScenarioParseError
from tools.scenario_runner.parsing.scenario_assembly import (
    ScenarioAssemblyInput,
    assemble_scenario_definition,
)
from tools.scenario_runner.parsing.scenario_converter import convert_step_draft
from tools.scenario_runner.parsing.steps.ir import ParsedStepDraft


class ScenarioConversionTests(unittest.TestCase):
    def test_api_step_draft_is_converted_into_stable_runtime_step(self) -> None:
        step = convert_step_draft(
            ParsedStepDraft(
                step_number=1,
                line_number=2,
                fields={
                    "type": "api",
                    "name": "create item",
                    "method": "post",
                    "path": "/items",
                    "headers": {"Content-Type": "application/json"},
                    "params": {"companyGuid": "{{company_guid}}"},
                    "body": {"name": "{{generated_name}}"},
                    "retry": {"enabled": True, "max_attempts": 3},
                    "capture": ["response.body.id -> item_id"],
                    "expected": ["HTTP 200"],
                },
                warnings=["Trailing markdown comment was ignored."],
            ),
            error_type=ScenarioParseError,
        )

        self.assertEqual(step.step_id, "step-1")
        self.assertEqual(step.step_number, 1)
        self.assertEqual(step.title, "create item")
        self.assertEqual(step.step_type, ScenarioStepType.API)
        self.assertEqual(step.metadata, {"parse_warnings": ["Trailing markdown comment was ignored."], "source_line": 2})
        self.assertIsNotNone(step.api)
        self.assertIsNone(step.db)
        self.assertEqual(step.api.name, "create item")
        self.assertEqual(step.api.method, "POST")
        self.assertEqual(step.api.path, "/items")
        self.assertEqual(step.api.headers, {"Content-Type": "application/json"})
        self.assertEqual(step.api.params, {"companyGuid": "{{company_guid}}"})
        self.assertEqual(step.api.body, {"name": "{{generated_name}}"})
        self.assertEqual(step.api.retry, {"enabled": True, "max_attempts": 3})
        self.assertEqual(step.api.capture, ["response.body.id -> item_id"])
        self.assertEqual(step.api.expected, ["HTTP 200"])

    def test_db_step_draft_is_converted_into_stable_runtime_step(self) -> None:
        step = convert_step_draft(
            ParsedStepDraft(
                step_number=2,
                line_number=11,
                fields={
                    "type": "db",
                    "name": "verify item",
                    "sql": "SELECT id FROM items WHERE id = :id",
                    "params": {"id": "{{item_id}}"},
                    "capture": ["rows[0].id -> verified_item_id"],
                    "expected": ["one row exists"],
                },
            ),
            error_type=ScenarioParseError,
        )

        self.assertEqual(step.step_id, "step-2")
        self.assertEqual(step.step_number, 2)
        self.assertEqual(step.title, "verify item")
        self.assertEqual(step.step_type, ScenarioStepType.DB)
        self.assertEqual(step.metadata, {"parse_warnings": [], "source_line": 11})
        self.assertIsNotNone(step.db)
        self.assertIsNone(step.api)
        self.assertEqual(step.db.name, "verify item")
        self.assertEqual(step.db.sql, "SELECT id FROM items WHERE id = :id")
        self.assertEqual(step.db.params, {"id": "{{item_id}}"})
        self.assertEqual(step.db.capture, ["rows[0].id -> verified_item_id"])
        self.assertEqual(step.db.expected, ["one row exists"])

    def test_invalid_step_conversion_errors_remain_compatible_by_meaning(self) -> None:
        with self.assertRaisesRegex(ScenarioParseError, "unsupported type 'shell'"):
            convert_step_draft(
                ParsedStepDraft(
                    step_number=3,
                    line_number=20,
                    fields={"type": "shell", "name": "bad"},
                ),
                error_type=ScenarioParseError,
            )

        with self.assertRaisesRegex(ScenarioParseError, "API step missing 'Method:'"):
            convert_step_draft(
                ParsedStepDraft(
                    step_number=4,
                    line_number=24,
                    fields={"type": "api", "name": "missing method", "path": "/demo"},
                ),
                error_type=ScenarioParseError,
            )

        with self.assertRaisesRegex(ScenarioParseError, "DB step missing 'SQL:'"):
            convert_step_draft(
                ParsedStepDraft(
                    step_number=5,
                    line_number=30,
                    fields={"type": "db", "name": "missing sql"},
                ),
                error_type=ScenarioParseError,
            )

    def test_final_scenario_definition_assembly_preserves_domain_shape(self) -> None:
        scenario_path = Path("scenarios/demo.md")
        scenario = assemble_scenario_definition(
            ScenarioAssemblyInput(
                scenario_path=scenario_path,
                scenario_slug="mixed-flow-abc12345",
                scenario_name="Mixed Flow",
                project="code/demo",
                environment="env/demo.env",
                goal="Verify mixed API and DB flow",
                preconditions=["seed data exists"],
                notes="Keep response id for DB verification.",
                final_expectations=["API create succeeded", "DB row exists"],
                report_output="summary.md",
                variables=[
                    ScenarioVariableDefinition(
                        name="company_guid",
                        raw_value="env:COMPANY_GUID",
                        source=ScenarioVariableSource.ENV,
                        env_name="COMPANY_GUID",
                    ),
                    ScenarioVariableDefinition(
                        name="run_suffix",
                        raw_value="generated:run_suffix",
                        source=ScenarioVariableSource.GENERATED,
                    ),
                ],
                step_drafts=[
                    ParsedStepDraft(
                        step_number=1,
                        line_number=2,
                        fields={
                            "type": "api",
                            "name": "create item",
                            "method": "post",
                            "path": "/companies/{{company_guid}}/items",
                            "headers": {"Content-Type": "application/json"},
                            "body": {"name": "AUTOTEST {{run_suffix}}"},
                            "capture": ["response.body.id -> created_id"],
                            "expected": ["HTTP 200"],
                        },
                        warnings=["Trailing note after step 1 was ignored."],
                    ),
                    ParsedStepDraft(
                        step_number=2,
                        line_number=18,
                        fields={
                            "type": "db",
                            "name": "verify item",
                            "sql": "SELECT id FROM items WHERE id = :id",
                            "params": {"id": "{{created_id}}"},
                            "expected": ["one row exists"],
                        },
                    ),
                ],
                parse_warnings=[
                    "Variables section used best-effort parsing for 'company_guid' at relative line 1.",
                    "Unknown scenario section 'Extra' was ignored.",
                ],
                variables_parse_warnings=[
                    "Variables section used best-effort parsing for 'company_guid' at relative line 1.",
                ],
                variables_validation_errors=[
                    "Variables section has invalid definition for 'email_suffix' at relative line 2: unsupported transform(s): slugify",
                ],
                source_format="markdown",
            ),
            error_type=ScenarioParseError,
        )

        self.assertIsInstance(scenario, ScenarioDefinition)
        self.assertEqual(
            scenario.to_dict(),
            {
                "scenario_path": str(scenario_path),
                "scenario_slug": "mixed-flow-abc12345",
                "scenario_name": "Mixed Flow",
                "project": "code/demo",
                "environment": "env/demo.env",
                "goal": "Verify mixed API and DB flow",
                "preconditions": ["seed data exists"],
                "notes": "Keep response id for DB verification.",
                "final_expectations": ["API create succeeded", "DB row exists"],
                "report_output": "summary.md",
                "variables": [
                    {
                        "name": "company_guid",
                        "raw_value": "env:COMPANY_GUID",
                        "source": "env",
                        "env_name": "COMPANY_GUID",
                        "source_name": None,
                        "transforms": [],
                    },
                    {
                        "name": "run_suffix",
                        "raw_value": "generated:run_suffix",
                        "source": "generated",
                        "env_name": None,
                        "source_name": None,
                        "transforms": [],
                    },
                ],
                "steps": [
                    {
                        "step_id": "step-1",
                        "step_number": 1,
                        "title": "create item",
                        "step_type": "api",
                        "api": {
                            "name": "create item",
                            "method": "POST",
                            "path": "/companies/{{company_guid}}/items",
                            "description": "",
                            "headers": {"Content-Type": "application/json"},
                            "params": {},
                            "body": {"name": "AUTOTEST {{run_suffix}}"},
                            "retry": None,
                            "capture": ["response.body.id -> created_id"],
                            "expected": ["HTTP 200"],
                        },
                        "db": None,
                        "metadata": {
                            "parse_warnings": ["Trailing note after step 1 was ignored."],
                            "source_line": 2,
                        },
                    },
                    {
                        "step_id": "step-2",
                        "step_number": 2,
                        "title": "verify item",
                        "step_type": "db",
                        "api": None,
                        "db": {
                            "name": "verify item",
                            "sql": "SELECT id FROM items WHERE id = :id",
                            "description": "",
                            "params": {"id": "{{created_id}}"},
                            "capture": [],
                            "expected": ["one row exists"],
                        },
                        "metadata": {
                            "parse_warnings": [],
                            "source_line": 18,
                        },
                    },
                ],
                "metadata": {
                    "parse_warnings": [
                        "Variables section used best-effort parsing for 'company_guid' at relative line 1.",
                        "Unknown scenario section 'Extra' was ignored.",
                    ],
                    "variables_parse_warnings": [
                        "Variables section used best-effort parsing for 'company_guid' at relative line 1.",
                    ],
                    "variables_validation_errors": [
                        "Variables section has invalid definition for 'email_suffix' at relative line 2: unsupported transform(s): slugify",
                    ],
                    "source_format": "markdown",
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
