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
    def test_parser_help_prefers_authoring_dsl_over_low_level_agent_plan(self) -> None:
        parser = cli.build_parser()
        help_by_option = {
            option_string: action.help
            for action in parser._actions
            for option_string in action.option_strings
            if action.help
        }

        self.assertEqual(
            parser.description,
            "Compile authoring DSL into a NormalizedTestPlan and optionally render markdown draft scenarios.",
        )
        self.assertIn("low-level AgentTestPlanInput template", help_by_option["--init-agent-plan"])
        self.assertIn("Prefer --authoring-plan-file", help_by_option["--agent-plan-file"])
        self.assertIn("preferred DSL input", help_by_option["--authoring-plan-file"])

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
        self.assertTrue(output_path.parent.name.startswith("gen-"))
        self.assertNotIn("users-api", output_path.parent.name)

    def test_init_authoring_plan_scaffolds_template_bundle(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "artifacts" / "agent" / "generation"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--init-authoring-plan",
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
            output_text = output_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["input_mode"], "authoring_plan")
        self.assertEqual(output_path.name, "authoring-plan.yaml")
        self.assertEqual(output_path.parent, Path(payload["bundle_dir"]))
        self.assertTrue(output_path.parent.name.startswith("gen-"))
        self.assertIn("source_id: users-api", output_text)
        self.assertIn("project: code/demo", output_text)

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

    def test_validate_authoring_plan_returns_pass_for_valid_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            authoring_plan_path = root / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-api
project: code/demo
title: Users API
goal: Cover user API behavior.
scope:
  surface: users-controller
entities:
  user:
    operations:
      verify_exists:
        sql: SELECT id FROM users WHERE id = :user_id
        params:
          user_id: "{{user_id}}"
        expected_outcomes:
          - one row exists
cases:
  - id: create-user
    kind: api
    objective: Verify user creation.
    state_change: create
    execute:
      route:
        method: POST
        path: /users
      body:
        email: "{{generated_email}}"
    oracle:
      status_code: 201
      captures:
        - response.json.id -> user_id
      persisted_state:
        entity: user
        operation: verify_exists
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(["--validate-authoring-plan", "--authoring-plan-file", str(authoring_plan_path)])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["input_mode"], "authoring_plan")
        self.assertEqual(payload["case_count"], 1)

    def test_compile_authoring_plan_writes_managed_agent_plan_bundle(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "artifacts" / "agent" / "generation"
            authoring_plan_path = root / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-api
project: code/demo
title: Users API
goal: Cover user API behavior.
scope:
  surface: users-controller
entities:
  user:
    operations:
      verify_exists:
        sql: SELECT id FROM users WHERE id = :user_id
        params:
          user_id: "{{user_id}}"
        expected_outcomes:
          - one row exists
cases:
  - id: create-user
    kind: api
    objective: Verify user creation.
    state_change: create
    execute:
      route:
        method: POST
        path: /users
      body:
        email: "{{generated_email}}"
    oracle:
      status_code: 201
      captures:
        - response.json.id -> user_id
      persisted_state:
        entity: user
        operation: verify_exists
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--compile-authoring-plan",
                        "--authoring-plan-file",
                        str(authoring_plan_path),
                        "--output",
                        str(output_root),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            output_path = Path(payload["output_path"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["input_mode"], "authoring_plan")
        self.assertEqual(output_path.name, "agent-plan.json")
        self.assertEqual(output_path.parent, Path(payload["bundle_dir"]))

    def test_compile_authoring_plan_reuses_existing_bundle_when_source_file_is_inside_it(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "artifacts" / "agent" / "generation"

            init_stdout = io.StringIO()
            with redirect_stdout(init_stdout):
                init_exit_code = cli.main(
                    [
                        "--init-authoring-plan",
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
            init_payload = json.loads(init_stdout.getvalue())
            authoring_plan_path = Path(init_payload["output_path"])

            compile_stdout = io.StringIO()
            with redirect_stdout(compile_stdout):
                compile_exit_code = cli.main(
                    [
                        "--compile-authoring-plan",
                        "--authoring-plan-file",
                        str(authoring_plan_path),
                        "--output",
                        str(output_root),
                    ]
                )
            compile_payload = json.loads(compile_stdout.getvalue())

        self.assertEqual(init_exit_code, 0)
        self.assertEqual(compile_exit_code, 0)
        self.assertEqual(Path(compile_payload["bundle_dir"]), authoring_plan_path.parent)
        self.assertEqual(compile_payload["output_path"], str(authoring_plan_path.parent / "agent-plan.json"))

    def test_authoring_plan_file_generates_plan_via_compiler(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            authoring_plan_path = root / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-api
project: code/demo
title: Users API
goal: Cover user API behavior.
scope:
  surface: users-controller
entities:
  user:
    operations:
      verify_exists:
        sql: SELECT id FROM users WHERE id = :user_id
        params:
          user_id: "{{user_id}}"
        expected_outcomes:
          - one row exists
cases:
  - id: create-user
    kind: api
    objective: Verify user creation.
    state_change: create
    execute:
      route:
        method: POST
        path: /users
      body:
        email: "{{generated_email}}"
    oracle:
      status_code: 201
      captures:
        - response.json.id -> user_id
      persisted_state:
        entity: user
        operation: verify_exists
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(["--authoring-plan-file", str(authoring_plan_path), "--workspace-root", str(root)])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["input_mode"], "authoring_plan")
        self.assertEqual(payload["test_case_count"], 1)

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
