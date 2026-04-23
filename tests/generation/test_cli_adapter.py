from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation import cli


class GenerationCliAdapterTests(unittest.TestCase):
    def test_agent_plan_file_generates_plan_without_prose_scanning(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_plan_path = root / "agent-plan.json"
            agent_plan_path.write_text(
                json.dumps(
                    {
                        "source_id": "sessions-agent-plan",
                        "project": "code/demo",
                        "title": "Internal user sessions",
                        "goal": "Cover session lifecycle behavior.",
                        "planned_test_cases": [
                            {
                                "title": "Authenticate session",
                                "objective": "Verify session authentication.",
                                "actions": ["Call the authenticate session API."],
                                "expected_outcomes": ["Session token is returned."],
                                "priority": "high",
                            },
                            {
                                "title": "List sessions",
                                "objective": "Verify sessions can be listed.",
                                "actions": ["Call the list sessions API."],
                                "expected_outcomes": ["Existing sessions are returned."],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--agent-plan-file",
                        str(agent_plan_path),
                        "--workspace-root",
                        str(root),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["input_mode"], "agent_plan")
        self.assertEqual(payload["source_id"], "sessions-agent-plan")
        self.assertEqual(payload["test_case_count"], 2)

    def test_plan_only_mode_generates_plan_and_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--source-id",
                        "users",
                        "--project",
                        "code/demo",
                        "--prose",
                        "Verify create user and get user by id",
                        "--workspace-root",
                        tmp,
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["input_mode"], "prose")
        self.assertEqual(payload["code_facts"], "not_requested")
        self.assertEqual(payload["enrichment"], "not_requested")
        self.assertGreaterEqual(payload["test_case_count"], 2)
        self.assertIn("normalized_plan", payload["artifact_paths"])

    def test_plan_with_evidence_mode_applies_enrichment_from_explicit_scope(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "code" / "demo"
            project.mkdir(parents=True)
            (project / "api.py").write_text(
                "\n".join(
                    [
                        "from fastapi import APIRouter",
                        "router = APIRouter()",
                        "",
                        "@router.post('/users')",
                        "def create_user(payload: dict) -> dict:",
                        "    return payload",
                    ]
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--source-id",
                        "users",
                        "--project",
                        "code/demo",
                        "--prose",
                        "Verify create user",
                        "--workspace-root",
                        str(root),
                        "--project-path",
                        str(project),
                        "--collect-code-facts",
                        "--enrich",
                        "--evidence-scope-path",
                        "api.py",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["code_facts"], "collected")
        self.assertEqual(payload["evidence_fact_count"], 1)
        self.assertEqual(payload["enrichment"], "applied")
        self.assertEqual(payload["applied_evidence_count"], 1)
        self.assertIn("evidence", payload["artifact_paths"])
        self.assertIn("enriched_plan", payload["artifact_paths"])
        self.assertIn("enrichment_result", payload["artifact_paths"])

    def test_agent_plan_file_can_use_evidence_enrichment(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "code" / "demo"
            project.mkdir(parents=True)
            (project / "api.py").write_text(
                "\n".join(
                    [
                        "from fastapi import APIRouter",
                        "router = APIRouter()",
                        "@router.post('/users')",
                        "def create_user(payload: dict) -> dict:",
                        "    return payload",
                    ]
                ),
                encoding="utf-8",
            )
            agent_plan_path = root / "agent-plan.json"
            agent_plan_path.write_text(
                json.dumps(
                    {
                        "source_id": "users-agent-plan",
                        "project": "code/demo",
                        "title": "Users API",
                        "planned_test_cases": [
                            {
                                "title": "Create user",
                                "objective": "Verify user creation.",
                                "actions": ["Call the create user API."],
                                "expected_outcomes": ["User is created."],
                                "unresolved_items": ["API endpoint executable detail is not resolved."],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--agent-plan-file",
                        str(agent_plan_path),
                        "--workspace-root",
                        str(root),
                        "--project-path",
                        str(project),
                        "--collect-code-facts",
                        "--enrich",
                        "--evidence-scope-path",
                        "api.py",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["input_mode"], "agent_plan")
        self.assertEqual(payload["code_facts"], "collected")
        self.assertEqual(payload["enrichment"], "applied")
        self.assertEqual(payload["applied_evidence_count"], 1)

    def test_enrichment_requires_collect_code_facts(self) -> None:
        with TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--source-id",
                        "users",
                        "--project",
                        "code/demo",
                        "--prose",
                        "Verify create user",
                        "--workspace-root",
                        tmp,
                        "--enrich",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "ERROR")
        self.assertTrue(
            any(
                diagnostic["code"] == "adapter_enrichment_requires_code_facts"
                for diagnostic in payload["diagnostics"]
            )
        )

    def test_code_facts_require_explicit_scope_and_project_path(self) -> None:
        with TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--source-id",
                        "users",
                        "--project",
                        "code/demo",
                        "--prose",
                        "Verify create user",
                        "--workspace-root",
                        tmp,
                        "--collect-code-facts",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        diagnostic_codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertEqual(exit_code, 1)
        self.assertIn("adapter_code_facts_require_project_path", diagnostic_codes)
        self.assertIn("adapter_code_facts_require_explicit_scope", diagnostic_codes)

    def test_scope_paths_are_explicit_and_do_not_trigger_broad_scan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "code" / "demo"
            project.mkdir(parents=True)
            (project / "users.py").write_text(
                "\n".join(
                    [
                        "from fastapi import APIRouter",
                        "router = APIRouter()",
                        "@router.post('/users')",
                        "def create_user(payload: dict) -> dict:",
                        "    return payload",
                    ]
                ),
                encoding="utf-8",
            )
            (project / "tenants.py").write_text(
                "\n".join(
                    [
                        "from fastapi import APIRouter",
                        "router = APIRouter()",
                        "@router.post('/tenants')",
                        "def create_tenant(payload: dict) -> dict:",
                        "    return payload",
                    ]
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--source-id",
                        "users",
                        "--project",
                        "code/demo",
                        "--prose",
                        "Verify create user",
                        "--workspace-root",
                        str(root),
                        "--project-path",
                        str(project),
                        "--collect-code-facts",
                        "--enrich",
                        "--evidence-scope-path",
                        "users.py",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["evidence_fact_count"], 1)
        self.assertEqual(payload["applied_evidence_count"], 1)

    def test_plan_with_evidence_can_render_parser_valid_draft_preview(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "code" / "demo"
            project.mkdir(parents=True)
            (project / "api.py").write_text(
                "\n".join(
                    [
                        "from fastapi import APIRouter",
                        "router = APIRouter()",
                        "@router.post('/users')",
                        "def create_user(payload: dict) -> dict:",
                        "    return payload",
                    ]
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--source-id",
                        "users",
                        "--project",
                        "code/demo",
                        "--prose",
                        "Verify create user",
                        "--workspace-root",
                        str(root),
                        "--project-path",
                        str(project),
                        "--collect-code-facts",
                        "--enrich",
                        "--render-drafts",
                        "--evidence-scope-path",
                        "api.py",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["scenario_rendering"], "rendered")
        self.assertEqual(payload["scenario_draft_count"], 1)
        self.assertEqual(payload["scenario_parse_valid_count"], 1)
        self.assertIn("scenario_render_result", payload["artifact_paths"])

    def test_render_drafts_requires_persistence(self) -> None:
        with TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--source-id",
                        "users",
                        "--project",
                        "code/demo",
                        "--prose",
                        "Verify create user",
                        "--workspace-root",
                        tmp,
                        "--render-drafts",
                        "--no-persist",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 1)
        self.assertTrue(
            any(
                diagnostic["code"] == "adapter_render_drafts_requires_persistence"
                for diagnostic in payload["diagnostics"]
            )
        )


if __name__ == "__main__":
    unittest.main()
