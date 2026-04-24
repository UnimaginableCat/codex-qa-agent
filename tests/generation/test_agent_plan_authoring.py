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

    def test_validate_file_accepts_multi_step_workflow_case_with_db_verification(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text(
                json.dumps(
                    {
                        "source_id": "sessions",
                        "project": "code/demo",
                        "title": "Sessions workflow",
                        "planned_test_cases": [
                            {
                                "title": "Authenticate and revoke session workflow",
                                "objective": "Verify the full session lifecycle.",
                                "kind": "workflow",
                                "workflow_steps": [
                                    {
                                        "step_type": "api",
                                        "title": "Authenticate session",
                                        "route": {
                                            "http_method": "POST",
                                            "endpoint_path": "/api/sessions/authenticate",
                                        },
                                        "expected_outcomes": ["HTTP 200"],
                                        "capture": ["response.json.sessionId -> session_id"],
                                    },
                                    {
                                        "step_type": "api",
                                        "title": "Revoke session",
                                        "route": {
                                            "http_method": "POST",
                                            "endpoint_path": "/api/sessions/{{session_id}}/revoke",
                                        },
                                        "expected_outcomes": ["HTTP 204"],
                                    },
                                    {
                                        "step_type": "db",
                                        "title": "Confirm session is revoked in storage",
                                        "sql": "SELECT status FROM user_sessions WHERE id = :session_id",
                                        "params": {
                                            "session_id": "{{session_id}}"
                                        },
                                        "expected_outcomes": ["one row exists", "`status` = `REVOKED`"],
                                    },
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = AgentPlanAuthoringService().validate_file(path)

        self.assertEqual(result.status, StepStatus.PASS)

    def test_validate_file_accepts_case_level_db_verification_with_no_rows_exist(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "db-verification.json"
            path.write_text(
                json.dumps(
                    {
                        "source_id": "identities",
                        "project": "code/demo",
                        "title": "Identity deletion",
                        "planned_test_cases": [
                            {
                                "title": "Delete identity removes persisted row",
                                "objective": "Verify deleted identities no longer exist in storage.",
                                "kind": "api",
                                "route": {
                                    "http_method": "DELETE",
                                    "endpoint_path": "/api/users/{{user_id}}/identities/{{identity_id}}",
                                },
                                "expected_outcomes": ["HTTP 204"],
                                "requires_db_verification": True,
                                "db_verification": {
                                    "name": "Confirm row was deleted",
                                    "sql": "SELECT id FROM user_identities WHERE id = :identity_id",
                                    "params": {"identity_id": "{{identity_id}}"},
                                    "expected_outcomes": ["no rows exist"],
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = AgentPlanAuthoringService().validate_file(path)

        self.assertEqual(result.status, StepStatus.PASS)

    def test_validate_file_blocks_mutating_workflow_without_db_verification(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text(
                json.dumps(
                    {
                        "source_id": "sessions",
                        "project": "code/demo",
                        "title": "Sessions workflow",
                        "planned_test_cases": [
                            {
                                "title": "Authenticate and revoke session workflow",
                                "objective": "Verify the full session lifecycle.",
                                "kind": "workflow",
                                "workflow_steps": [
                                    {
                                        "step_type": "api",
                                        "title": "Authenticate session",
                                        "route": {
                                            "http_method": "POST",
                                            "endpoint_path": "/api/sessions/authenticate",
                                        },
                                        "expected_outcomes": ["HTTP 200"],
                                        "capture": ["response.json.sessionId -> session_id"],
                                    },
                                    {
                                        "step_type": "api",
                                        "title": "Revoke session",
                                        "route": {
                                            "http_method": "POST",
                                            "endpoint_path": "/api/sessions/{{session_id}}/revoke",
                                        },
                                        "expected_outcomes": ["HTTP 204"],
                                    },
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = AgentPlanAuthoringService().validate_file(path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(diagnostic.code == "agent_plan_workflow_db_verification_required" for diagnostic in result.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
