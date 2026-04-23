from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.generation.authoring import AgentPlanAuthoringService


class AgentPlanAuthoringServiceTests(unittest.TestCase):
    def test_build_template_returns_valid_starter_plan(self) -> None:
        service = AgentPlanAuthoringService()

        template = service.build_template(
            source_id="users-api",
            project="code/demo",
            title="Users API",
            goal="Cover user API behavior.",
        )
        validation = service.validate(template)

        self.assertEqual(validation.status, StepStatus.PASS)
        self.assertEqual(template.source_id, "users-api")
        self.assertEqual(template.project, "code/demo")
        self.assertEqual(template.planned_test_cases[0].title, "Replace with case title")
        self.assertEqual(template.metadata["template_version"], "agent-plan-template-v1")

    def test_validate_file_reports_missing_required_top_level_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text(
                json.dumps(
                    {
                        "source_id": "",
                        "project": "",
                        "title": "",
                        "planned_test_cases": [
                            {
                                "title": "Create user",
                                "objective": "Verify user creation.",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = AgentPlanAuthoringService().validate_file(path)

        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertIn("agent_plan_missing_source_id", codes)
        self.assertIn("agent_plan_missing_project", codes)
        self.assertIn("agent_plan_missing_title", codes)

    def test_validate_file_reports_zero_cases(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text(
                json.dumps(
                    {
                        "source_id": "users",
                        "project": "code/demo",
                        "title": "Users API",
                        "planned_test_cases": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = AgentPlanAuthoringService().validate_file(path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(any(diagnostic.code == "agent_plan_no_cases" for diagnostic in result.diagnostics))

    def test_validate_file_reports_missing_case_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text(
                json.dumps(
                    {
                        "source_id": "users",
                        "project": "code/demo",
                        "title": "Users API",
                        "planned_test_cases": [
                            {
                                "title": "",
                                "objective": "",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = AgentPlanAuthoringService().validate_file(path)

        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertIn("agent_plan_case_missing_title", codes)
        self.assertIn("agent_plan_case_missing_objective", codes)

    def test_validate_file_reports_shape_errors(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text(
                json.dumps(
                    {
                        "source_id": "users",
                        "project": "code/demo",
                        "title": "Users API",
                        "planned_test_cases": "not-a-list",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = AgentPlanAuthoringService().validate_file(path)

        self.assertEqual(result.status, StepStatus.ERROR)
        self.assertTrue(any(diagnostic.code == "agent_plan_field_not_list" for diagnostic in result.diagnostics))

    def test_validate_file_reports_invalid_evidence_scope_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text(
                json.dumps(
                    {
                        "source_id": "users",
                        "project": "code/demo",
                        "title": "Users API",
                        "planned_test_cases": [
                            {
                                "title": "Create user",
                                "objective": "Verify user creation.",
                            }
                        ],
                        "evidence_scope": {
                            "paths": "api.py",
                            "stack_hint": "unknown_stack",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = AgentPlanAuthoringService().validate_file(path)

        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertEqual(result.status, StepStatus.ERROR)
        self.assertIn("agent_plan_evidence_scope_paths_not_list", codes)
        self.assertIn("agent_plan_evidence_scope_invalid_stack_hint", codes)


if __name__ == "__main__":
    unittest.main()
