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
    def test_init_agent_plan_scaffolds_template_bundle(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "artifacts" / "agent" / "generation"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--init-agent-plan",
                        "--output",
                        str(output_root),
                        "--source-id",
                        "users-api",
                        "--project",
                        "code/demo",
                        "--name",
                        "Users API",
                        "--goal",
                        "Cover user API behavior.",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            output_path = Path(payload["output_path"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["input_mode"], "agent_plan")
        self.assertEqual(output_path.name, "agent-plan.json")
        self.assertEqual(output_path.parent, Path(payload["bundle_dir"]))

    def test_validate_agent_plan_returns_pass_for_valid_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_plan_path = root / "agent-plan.json"
            agent_plan_path.write_text(
                json.dumps(
                    {
                        "source_id": "users-api",
                        "project": "code/demo",
                        "title": "Users API",
                        "planned_test_cases": [
                            {
                                "title": "Create user",
                                "objective": "Verify user creation.",
                                "actions": ["Call the create user API."],
                                "expected_outcomes": ["HTTP 201"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(["--validate-agent-plan", "--agent-plan-file", str(agent_plan_path)])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["case_count"], 1)

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
                                "expected_outcomes": ["HTTP 200"],
                                "route": {
                                    "http_method": "POST",
                                    "endpoint_path": "/api/internal/v1/user-sessions/authenticate",
                                },
                            },
                            {
                                "title": "List sessions",
                                "objective": "Verify sessions can be listed.",
                                "actions": ["Call the list sessions API."],
                                "expected_outcomes": ["HTTP 200"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(["--agent-plan-file", str(agent_plan_path), "--workspace-root", str(root)])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["input_mode"], "agent_plan")
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
        self.assertGreaterEqual(payload["test_case_count"], 2)
        self.assertIn("normalized_plan", payload["artifact_paths"])

    def test_agent_plan_with_route_can_render_parser_valid_draft_preview(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_plan_path = root / "agent-plan.json"
            agent_plan_path.write_text(
                json.dumps(
                    {
                        "source_id": "users",
                        "project": "code/demo",
                        "title": "Users API",
                        "planned_test_cases": [
                            {
                                "title": "Create user",
                                "objective": "Verify create user.",
                                "route": {
                                    "http_method": "POST",
                                    "endpoint_path": "/users",
                                },
                                "expected_outcomes": ["HTTP 201"],
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
                        "--render-drafts",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["scenario_rendering"], "rendered")
        self.assertEqual(payload["scenario_draft_count"], 1)
        self.assertEqual(payload["scenario_parse_valid_count"], 1)
        self.assertIn("scenario_render_result", payload["artifact_paths"])

    def test_render_drafts_summary_includes_typed_unresolved_intents(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_plan_path = root / "agent-plan.json"
            agent_plan_path.write_text(
                json.dumps(
                    {
                        "source_id": "users",
                        "project": "code/demo",
                        "title": "Users API",
                        "planned_test_cases": [
                            {
                                "title": "Create user",
                                "objective": "Verify create user.",
                                "gaps": [
                                    {"category": "environment", "message": "Use staging env before execution."},
                                    {"category": "data_setup", "message": "Create an active user fixture before execution."},
                                ],
                                "route": {
                                    "http_method": "POST",
                                    "endpoint_path": "/users",
                                },
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
                        "--render-drafts",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["scenario_unresolved_intent_count"], 2)
        self.assertEqual(payload["scenario_unresolved_intents"][0]["gap_categories"], ["environment", "data_setup"])

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
        self.assertTrue(any(diagnostic["code"] == "adapter_render_drafts_requires_persistence" for diagnostic in payload["diagnostics"]))


if __name__ == "__main__":
    unittest.main()
