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
            entity_inventory_path = Path(payload["entity_inventory_path"])
            operation_inventory_path = Path(payload["operation_inventory_path"])
            output_text = output_path.read_text(encoding="utf-8")
            entity_inventory_text = entity_inventory_path.read_text(encoding="utf-8")
            operation_inventory_text = operation_inventory_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["input_mode"], "authoring_plan")
        self.assertEqual(output_path.name, "authoring-plan.yaml")
        self.assertEqual(entity_inventory_path.name, "entity-inventory.yaml")
        self.assertEqual(operation_inventory_path.name, "operation-inventory.yaml")
        self.assertEqual(output_path.parent, Path(payload["bundle_dir"]))
        self.assertEqual(entity_inventory_path.parent, Path(payload["bundle_dir"]))
        self.assertEqual(operation_inventory_path.parent, Path(payload["bundle_dir"]))
        self.assertTrue(output_path.parent.name.startswith("gen-"))
        self.assertEqual(payload["stage_policy"]["mode"], "strict_sequential_authoring")
        self.assertEqual(
            [stage["required_gate"] for stage in payload["stage_policy"]["stages"]],
            [
                "validate-entity-inventory",
                "validate-operation-inventory",
                "sync-authoring-plan",
                "validate-authoring-plan",
                "validate-authoring-bundle",
            ],
        )
        self.assertIn("source_id: users-api", output_text)
        self.assertIn("project: code/demo", output_text)
        self.assertIn("scenario_variables:", output_text)
        self.assertIn("run_suffix = generated:run_suffix", output_text)
        self.assertIn("authoring_workflow: staged-v1", output_text)
        self.assertIn("stage: entity_inventory", entity_inventory_text)
        self.assertIn("allowed_transitions:", entity_inventory_text)
        self.assertIn("stage: operation_inventory", operation_inventory_text)
        self.assertIn("success_status: 201", operation_inventory_text)

    def test_init_entity_inventory_reuses_existing_bundle_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "artifacts" / "agent" / "generation"

            init_authoring_stdout = io.StringIO()
            with redirect_stdout(init_authoring_stdout):
                init_authoring_exit_code = cli.main(
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
            init_authoring_payload = json.loads(init_authoring_stdout.getvalue())
            bundle_dir = Path(init_authoring_payload["bundle_dir"])

            init_entity_stdout = io.StringIO()
            with redirect_stdout(init_entity_stdout):
                init_entity_exit_code = cli.main(
                    [
                        "--init-entity-inventory",
                        "--output",
                        str(bundle_dir),
                        "--source-id",
                        "users-api",
                        "--project",
                        "code/demo",
                        "--surface",
                        "users-controller",
                    ]
                )
            init_entity_payload = json.loads(init_entity_stdout.getvalue())

        self.assertEqual(init_authoring_exit_code, 0)
        self.assertEqual(init_entity_exit_code, 0)
        self.assertEqual(Path(init_entity_payload["bundle_dir"]), bundle_dir)
        self.assertEqual(Path(init_entity_payload["output_path"]), bundle_dir / "entity-inventory.yaml")

    def test_init_operation_inventory_reuses_bundle_selected_by_run_id(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "artifacts" / "agent" / "generation"

            init_authoring_stdout = io.StringIO()
            with redirect_stdout(init_authoring_stdout):
                init_authoring_exit_code = cli.main(
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
            init_authoring_payload = json.loads(init_authoring_stdout.getvalue())
            bundle_dir = Path(init_authoring_payload["bundle_dir"])

            init_operation_stdout = io.StringIO()
            with redirect_stdout(init_operation_stdout):
                init_operation_exit_code = cli.main(
                    [
                        "--init-operation-inventory",
                        "--output",
                        str(output_root),
                        "--run-id",
                        bundle_dir.name,
                        "--source-id",
                        "users-api",
                        "--project",
                        "code/demo",
                        "--surface",
                        "users-controller",
                    ]
                )
            init_operation_payload = json.loads(init_operation_stdout.getvalue())

        self.assertEqual(init_authoring_exit_code, 0)
        self.assertEqual(init_operation_exit_code, 0)
        self.assertEqual(Path(init_operation_payload["bundle_dir"]), bundle_dir)
        self.assertEqual(Path(init_operation_payload["output_path"]), bundle_dir / "operation-inventory.yaml")

    def test_init_operation_inventory_blocks_missing_run_id_bundle(self) -> None:
        with TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "artifacts" / "agent" / "generation"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--init-operation-inventory",
                        "--output",
                        str(output_root),
                        "--run-id",
                        "gen-20260429T000000Z-missing",
                        "--source-id",
                        "users-api",
                        "--project",
                        "code/demo",
                        "--surface",
                        "users-controller",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("adapter_scaffold_run_id_bundle_missing", codes)

    def test_init_authoring_plan_blocks_project_outside_code_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "artifacts" / "agent" / "generation"

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
                        "LeadFlow",
                        "--name",
                        "Users API",
                        "--goal",
                        "Cover user API behavior.",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("adapter_project_must_target_code_subdir", codes)

    def test_validate_entity_inventory_returns_pass_for_valid_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entity_inventory_path = root / "entity-inventory.yaml"
            entity_inventory_path.write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    normalized_fields: [email]
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(["--validate-entity-inventory", "--entity-inventory-file", str(entity_inventory_path)])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "PASS")

    def test_validate_entity_inventory_blocks_project_outside_code_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entity_inventory_path = root / "entity-inventory.yaml"
            entity_inventory_path.write_text(
                """version: 1
source_id: users-api
project: LeadFlow
surface: users-controller
entities:
  - name: user
    id_field: user_id
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(["--validate-entity-inventory", "--entity-inventory-file", str(entity_inventory_path)])
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("adapter_entity_inventory_project_must_target_code_subdir", codes)

    def test_validate_operation_inventory_blocks_unknown_entity_reference(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0004"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
""",
                encoding="utf-8",
            )
            operation_inventory_path = bundle_dir / "operation-inventory.yaml"
            operation_inventory_path.write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entity_operations:
  - entity: account
    operation: create
    effect_state: ACTIVE
routes:
  - method: POST
    path: /users
    success_status: 201
db_verifications: []
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(["--validate-operation-inventory", "--operation-inventory-file", str(operation_inventory_path)])
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("adapter_operation_inventory_unknown_entity", codes)

    def test_validate_operation_inventory_blocks_ambiguous_capture_rule(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
""",
                encoding="utf-8",
            )
            operation_inventory_path = root / "operation-inventory.yaml"
            operation_inventory_path.write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create_active
    effect_state: ACTIVE
    route:
      method: POST
      path: /users
    captures:
      - user_id
routes:
  - method: POST
    path: /users
    success_status: 201
db_verifications: []
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(["--validate-operation-inventory", "--operation-inventory-file", str(operation_inventory_path)])
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("adapter_operation_inventory_capture_rule_invalid", codes)

    def test_validate_operation_inventory_blocks_non_executable_templates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
""",
                encoding="utf-8",
            )
            operation_inventory_path = root / "operation-inventory.yaml"
            operation_inventory_path.write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create_active
    effect_state: ACTIVE
routes:
  - method: POST
    path: /users
    success_status: 201
db_verifications:
  - entity: user
    operation: verify_exists
    scoped_by: user_id
    column_types:
      id: uuid
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(["--validate-operation-inventory", "--operation-inventory-file", str(operation_inventory_path)])
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("adapter_operation_inventory_operation_template_missing", codes)
        self.assertIn("adapter_operation_inventory_db_verification_template_incomplete", codes)

    def test_validate_authoring_bundle_returns_pass_for_scaffolded_bundle(self) -> None:
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
            bundle_dir = Path(init_payload["bundle_dir"])

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit_code = cli.main(
                    [
                        "--validate-authoring-bundle",
                        "--path",
                        str(bundle_dir),
                    ]
                )
            validate_payload = json.loads(validate_stdout.getvalue())

        self.assertEqual(init_exit_code, 0)
        self.assertEqual(validate_exit_code, 0)
        self.assertEqual(validate_payload["status"], "PASS")
        self.assertEqual(validate_payload["stage_order"], ["entity_inventory", "operation_inventory", "authoring_plan"])
        self.assertEqual(validate_payload["stage_results"]["authoring_plan"]["status"], "PASS")
        self.assertEqual(validate_payload["stage_results"]["authoring_plan"]["case_count"], 1)
        self.assertEqual(validate_payload["stage_results"]["authoring_plan"]["compiled_case_count"], 1)
        self.assertFalse(validate_payload["handoff"]["scenario_drafts_rendered"])
        self.assertFalse(validate_payload["handoff"]["promoted_scenarios"])
        self.assertIn("--compile-authoring-plan", validate_payload["handoff"]["next_commands"][0]["command"])
        self.assertIn("--render-drafts", validate_payload["handoff"]["next_commands"][1]["command"])

    def test_validate_authoring_bundle_text_output_names_authoring_only_handoff(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "artifacts" / "agent" / "generation"

            init_stdout = io.StringIO()
            with redirect_stdout(init_stdout):
                cli.main(
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
            bundle_dir = Path(init_payload["bundle_dir"])

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit_code = cli.main(
                    [
                        "--validate-authoring-bundle",
                        "--path",
                        str(bundle_dir),
                        "--output-format",
                        "text",
                    ]
                )
            output_text = validate_stdout.getvalue()

        self.assertEqual(validate_exit_code, 0)
        self.assertIn("No runnable scenario drafts were rendered or promoted", output_text)
        self.assertIn("authoring_plan: PASS (1/1 cases compile)", output_text)
        self.assertIn("scenario_drafts_rendered: False", output_text)
        self.assertIn("--render-drafts", output_text)

    def test_init_authoring_plan_text_output_includes_stage_policy(self) -> None:
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
                        "--output-format",
                        "text",
                    ]
                )
            output_text = stdout.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertIn("Stage policy:", output_text)
        self.assertIn("strict_sequential_authoring", output_text)
        self.assertIn("entity_inventory: validate-entity-inventory", output_text)
        self.assertIn("operation_inventory: validate-operation-inventory after entity_inventory", output_text)
        self.assertIn("sync_authoring_plan: sync-authoring-plan after operation_inventory", output_text)
        self.assertIn("authoring_plan: validate-authoring-plan after sync_authoring_plan", output_text)

    def test_sync_authoring_plan_hydrates_entities_from_inventories(self) -> None:
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
            bundle_dir = Path(init_payload["bundle_dir"])
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    normalized_fields: [email]
auth_contract:
  actor: admin-api-client
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create_active
    effect_state: ACTIVE
    route:
      method: POST
      path: /users
    request_body:
      email: "{{submitted_email}}"
    request_constraints:
      - field: email
        format: lowercase
    captures:
      - response.json.id -> user_id
routes:
  - method: POST
    path: /users
    success_status: 201
    failure_statuses: [400]
db_verifications:
  - entity: user
    operation: verify_exists
    scoped_by: user_id
    sql: SELECT id FROM users WHERE id = :user_id
    params:
      user_id: "{{user_id}}"
    expected_outcomes:
      - one row exists
    column_types:
      id: uuid
""",
                encoding="utf-8",
            )

            sync_stdout = io.StringIO()
            with redirect_stdout(sync_stdout):
                sync_exit_code = cli.main(["--sync-authoring-plan", "--path", str(bundle_dir)])
            sync_payload = json.loads(sync_stdout.getvalue())

        self.assertEqual(init_exit_code, 0)
        self.assertEqual(sync_exit_code, 0)
        self.assertEqual(sync_payload["status"], "PASS")
        self.assertEqual(sync_payload["validation_status_after_sync"], "BLOCKED")
        self.assertEqual(sync_payload["next_status"], "BLOCKED")
        self.assertIn("follow-up validation is still blocked", sync_payload["message"])
        synced_user = sync_payload["authoring_plan"]["entities"]["user"]
        self.assertEqual(synced_user["id_field"], "user_id")
        create_operation = synced_user["operations"]["create_active"]
        self.assertEqual(create_operation["route"]["method"], "POST")
        self.assertEqual(create_operation["route"]["path"], "/users")
        self.assertEqual(create_operation["oracle"]["status_code"], 201)
        self.assertEqual(create_operation["request_constraints"], [{"field": "email", "format": "lowercase"}])
        self.assertEqual(create_operation["captures"], ["response.json.id -> user_id"])
        verify_operation = synced_user["operations"]["verify_exists"]
        self.assertEqual(verify_operation["sql"], "SELECT id FROM users WHERE id = :user_id")
        self.assertEqual(verify_operation["expected_outcomes"], ["one row exists"])
        self.assertEqual(verify_operation["column_types"], {"id": "uuid"})
        self.assertEqual(sync_payload["authoring_plan"]["cases"], [])

    def test_sync_authoring_plan_preserves_existing_str_enum_cases(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "artifacts" / "agent" / "generation"

            init_stdout = io.StringIO()
            with redirect_stdout(init_stdout):
                cli.main(
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
            bundle_dir = Path(json.loads(init_stdout.getvalue())["bundle_dir"])
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entity_operations: []
routes:
  - method: GET
    path: /users
    success_status: 200
    failure_statuses: [401]
""",
                encoding="utf-8",
            )
            (bundle_dir / "authoring-plan.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
cases:
  - id: list-users
    kind: api
    objective: List users.
    state_change: read_only
    execute:
      route:
        method: GET
        path: /users
    oracle:
      status_code: 200
      business_checks:
        - response JSON is an array
""",
                encoding="utf-8",
            )

            sync_stdout = io.StringIO()
            with redirect_stdout(sync_stdout):
                sync_exit_code = cli.main(["--sync-authoring-plan", "--path", str(bundle_dir)])
            sync_payload = json.loads(sync_stdout.getvalue())
            synced_text = (bundle_dir / "authoring-plan.yaml").read_text(encoding="utf-8")

        self.assertEqual(sync_exit_code, 0)
        self.assertEqual(sync_payload["status"], "PASS")
        self.assertEqual(sync_payload["case_count"], 1)
        self.assertEqual(sync_payload["authoring_plan"]["cases"][0]["state_change"], "read_only")
        self.assertIn("state_change: read_only", synced_text)

    def test_sync_authoring_plan_text_output_reports_followup_validation_status(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "artifacts" / "agent" / "generation"

            init_stdout = io.StringIO()
            with redirect_stdout(init_stdout):
                cli.main(
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
            bundle_dir = Path(json.loads(init_stdout.getvalue())["bundle_dir"])

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--sync-authoring-plan",
                        "--path",
                        str(bundle_dir),
                        "--output-format",
                        "text",
                    ]
                )
            output_text = stdout.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertIn("Authoring-plan synced from staged inventories", output_text)
        self.assertIn("Validation after sync:", output_text)
        self.assertIn("Next status:", output_text)

    def test_validate_authoring_bundle_returns_blocked_for_stage_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0005"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "context.json").write_text(
                json.dumps(
                    {
                        "run_id": "gen-20260428T000000Z-test0005",
                        "workspace_root": str(Path(tmp).resolve()),
                        "source_id": "users-api",
                        "project": "code/demo",
                        "artifacts_root_dir": str((Path(tmp) / "artifacts" / "agent" / "generation").resolve()),
                        "artifact_dir": str(bundle_dir.resolve()),
                        "started_at": "2026-04-28T00:00:00+00:00",
                        "variables": {},
                    }
                ),
                encoding="utf-8",
            )
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    states: [ACTIVE, SUSPENDED, ARCHIVED]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create
    effect_state: ACTIVE
  - entity: user
    operation: archive
    effect_state: ARCHIVED
routes:
  - method: POST
    path: /users/{{user_id}}/activate
    success_status: 200
    failure_statuses: [400, 404]
    precondition_state: SUSPENDED
db_verifications:
  - entity: user
    operation: verify_active
    scoped_by: user_id
""",
                encoding="utf-8",
            )
            (bundle_dir / "authoring-plan.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
title: Users API
goal: Cover users API behavior.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations:
      create:
        route:
          method: POST
          path: /users
      archive:
        route:
          method: POST
          path: /users/{{user_id}}/archive
      verify_active:
        sql: SELECT status FROM users WHERE id = :user_id
        params:
          user_id: "{{user_id}}"
        expected_outcomes:
          - one row exists
cases:
  - id: activate-user
    kind: workflow
    objective: Activate suspended user.
    state_change: none
    setup:
      - use_entity: user
        operation: create
      - use_entity: user
        operation: archive
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/activate
    oracle:
      status_code: 200
      persisted_state:
        entity: user
        operation: verify_active
""",
                encoding="utf-8",
            )

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit_code = cli.main(
                    [
                        "--validate-authoring-bundle",
                        "--path",
                        str(bundle_dir),
                    ]
                )
            validate_payload = json.loads(validate_stdout.getvalue())

        self.assertNotEqual(validate_exit_code, 0)
        self.assertEqual(validate_payload["status"], "BLOCKED")
        self.assertEqual(validate_payload["stage_results"]["authoring_plan"]["status"], "BLOCKED")
        authoring_codes = {
            diagnostic["code"]
            for diagnostic in validate_payload["stage_results"]["authoring_plan"]["diagnostics"]
        }
        self.assertIn("authoring_stage_inventory_state_mismatch", authoring_codes)

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

    def test_validate_authoring_plan_blocks_when_managed_bundle_is_missing_stage_inventory(self) -> None:
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
            (authoring_plan_path.parent / "entity-inventory.yaml").unlink()

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit_code = cli.main(
                    [
                        "--validate-authoring-plan",
                        "--authoring-plan-file",
                        str(authoring_plan_path),
                    ]
                )
            validate_payload = json.loads(validate_stdout.getvalue())

        self.assertEqual(init_exit_code, 0)
        self.assertNotEqual(validate_exit_code, 0)
        self.assertEqual(validate_payload["status"], "BLOCKED")
        codes = {diagnostic["code"] for diagnostic in validate_payload["diagnostics"]}
        self.assertIn("authoring_stage_inventory_missing", codes)

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

    def test_compile_authoring_plan_blocks_when_bundle_stage_gate_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0006"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "context.json").write_text(
                json.dumps(
                    {
                        "run_id": "gen-20260428T000000Z-test0006",
                        "workspace_root": str(Path(tmp).resolve()),
                        "source_id": "users-api",
                        "project": "code/demo",
                        "artifacts_root_dir": str((Path(tmp) / "artifacts" / "agent" / "generation").resolve()),
                        "artifact_dir": str(bundle_dir.resolve()),
                        "started_at": "2026-04-28T00:00:00+00:00",
                        "variables": {},
                    }
                ),
                encoding="utf-8",
            )
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entity_operations:
  - entity: account
    operation: create
    effect_state: ACTIVE
routes:
  - method: GET
    path: /users
    success_status: 200
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
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
    id_field: user_id
    operations: {}
cases:
  - id: list-users
    kind: api
    objective: List users.
    state_change: none
    execute:
      route:
        method: GET
        path: /users
    oracle:
      status_code: 200
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
                        str(bundle_dir.parent),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertIn("stage_results", payload)
        operation_codes = {
            diagnostic["code"]
            for diagnostic in payload["stage_results"]["operation_inventory"]["diagnostics"]
        }
        self.assertIn("adapter_operation_inventory_unknown_entity", operation_codes)

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

    def test_authoring_plan_generation_blocks_when_bundle_stage_gate_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0007"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "context.json").write_text(
                json.dumps(
                    {
                        "run_id": "gen-20260428T000000Z-test0007",
                        "workspace_root": str(Path(tmp).resolve()),
                        "source_id": "users-api",
                        "project": "code/demo",
                        "artifacts_root_dir": str((Path(tmp) / "artifacts" / "agent" / "generation").resolve()),
                        "artifact_dir": str(bundle_dir.resolve()),
                        "started_at": "2026-04-28T00:00:00+00:00",
                        "variables": {},
                    }
                ),
                encoding="utf-8",
            )
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entity_operations:
  - entity: account
    operation: create
    effect_state: ACTIVE
routes:
  - method: GET
    path: /users
    success_status: 200
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
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
    id_field: user_id
    operations: {}
cases:
  - id: list-users
    kind: api
    objective: List users.
    state_change: none
    execute:
      route:
        method: GET
        path: /users
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--authoring-plan-file",
                        str(authoring_plan_path),
                        "--workspace-root",
                        str(Path(tmp)),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("adapter_operation_inventory_unknown_entity", codes)

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

    def test_validate_operation_inventory_blocks_incomplete_same_state_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entity_inventory_path = root / "entity-inventory.yaml"
            entity_inventory_path.write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
""",
                encoding="utf-8",
            )
            operation_inventory_path = root / "operation-inventory.yaml"
            operation_inventory_path.write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: archive
    effect_state: ARCHIVED
routes:
  - method: POST
    path: /users/{{user_id}}/archive
    success_status: 200
    failure_statuses: [400, 404]
    same_state_behavior: idempotent_success
db_verifications: []
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--validate-operation-inventory",
                        "--operation-inventory-file",
                        str(operation_inventory_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("adapter_operation_inventory_same_state_contract_incomplete", codes)

    def test_validate_operation_inventory_blocks_same_state_contract_without_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entity_inventory_path = root / "entity-inventory.yaml"
            entity_inventory_path.write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
""",
                encoding="utf-8",
            )
            operation_inventory_path = root / "operation-inventory.yaml"
            operation_inventory_path.write_text(
                """version: 1
source_id: users-api
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: archive
    effect_state: ARCHIVED
routes:
  - method: POST
    path: /users/{{user_id}}/archive
    success_status: 200
    failure_statuses: [400, 404]
    target_state: ARCHIVED
    same_state_behavior: idempotent_success
    same_state_status: 200
db_verifications: []
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--validate-operation-inventory",
                        "--operation-inventory-file",
                        str(operation_inventory_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("adapter_operation_inventory_same_state_evidence_missing", codes)


if __name__ == "__main__":
    unittest.main()
