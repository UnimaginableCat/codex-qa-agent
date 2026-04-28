from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.generation.authoring_contract import AuthoringPlanCompiler
from tools.generation.authoring_contract.models import (
    AuthoringCase,
    AuthoringDefaults,
    AuthoringEntityOperation,
    AuthoringEntitySpec,
    AuthoringExecute,
    AuthoringOracle,
    AuthoringPersistedStateRef,
    AuthoringPlan,
    AuthoringRoute,
    AuthoringScope,
    AuthoringStateChange,
    AuthoringSetupStep,
)


class AuthoringPlanCompilerTests(unittest.TestCase):
    def test_compile_propagates_defaults_environment_actor_and_setup_auth(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(environment="env/custom.env", auth="bearer", actor="api-client"),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "create": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users"),
                            request_body={"email": "{{generated_email}}"},
                            captures=["response.json.id -> user_id"],
                        ),
                        "verify_exists": AuthoringEntityOperation(
                            sql="SELECT id FROM users WHERE id = :user_id",
                            params={"user_id": "{{user_id}}"},
                            expected_outcomes=["one row exists"],
                        ),
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="get-user-success",
                    kind="workflow",
                    objective="Get created user",
                    state_change="none",
                    setup=[AuthoringSetupStep(use_entity="user", operation="create")],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users/{{user_id}}"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                ),
                AuthoringCase(
                    id="create-user-success",
                    kind="api",
                    objective="Create user successfully",
                    state_change="create",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users"),
                        body={"email": "{{generated_email}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> user_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_exists"),
                    ),
                ),
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        self.assertEqual(result.compiled_plan.metadata["default_environment"], "env/custom.env")
        self.assertEqual(result.compiled_plan.metadata["default_actor"], "api-client")
        workflow_case = result.compiled_plan.planned_test_cases[0]
        self.assertEqual(workflow_case.metadata["default_environment"], "env/custom.env")
        self.assertEqual(workflow_case.metadata["default_actor"], "api-client")
        self.assertEqual(workflow_case.workflow_steps[0].auth_strategy, ["bearer"])
        self.assertEqual(workflow_case.workflow_steps[0].metadata["default_actor"], "api-client")

    def test_compile_merges_default_headers_into_setup_and_case_requests(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "internal_api_token = env:INTERNAL_API_TOKEN",
                    "generated_email = template:autotest@example.com",
                ],
                headers={
                    "X-Leadflow-Internal-Token": "{{internal_api_token}}",
                    "Content-Type": "application/json",
                }
            ),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "create": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users"),
                            request_headers={"X-Request-Source": "setup"},
                            request_body={"email": "{{generated_email}}"},
                            captures=["response.json.id -> user_id"],
                        ),
                        "verify_exists": AuthoringEntityOperation(
                            sql="SELECT id FROM users WHERE id = :user_id",
                            params={"user_id": "{{user_id}}"},
                            expected_outcomes=["one row exists"],
                        ),
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="get-user-success",
                    kind="workflow",
                    objective="Get created user",
                    state_change="none",
                    setup=[AuthoringSetupStep(use_entity="user", operation="create")],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users/{{user_id}}"),
                        headers={"Content-Type": "application/custom+json"},
                    ),
                    oracle=AuthoringOracle(status_code=200),
                ),
                AuthoringCase(
                    id="create-user-success",
                    kind="api",
                    objective="Create user successfully",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users"),
                        headers={"X-Request-Source": "case"},
                        body={"email": "{{generated_email}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> user_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_exists"),
                    ),
                ),
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        workflow_case = result.compiled_plan.planned_test_cases[0]
        self.assertEqual(
            workflow_case.workflow_steps[0].request_headers,
            {
                "X-Leadflow-Internal-Token": "{{internal_api_token}}",
                "Content-Type": "application/json",
                "X-Request-Source": "setup",
            },
        )
        self.assertEqual(
            workflow_case.workflow_steps[1].request_headers,
            {
                "X-Leadflow-Internal-Token": "{{internal_api_token}}",
                "Content-Type": "application/custom+json",
            },
        )
        api_case = result.compiled_plan.planned_test_cases[1]
        self.assertEqual(
            api_case.request_headers,
            {
                "X-Leadflow-Internal-Token": "{{internal_api_token}}",
                "Content-Type": "application/json",
                "X-Request-Source": "case",
            },
        )

    def test_compile_valid_authoring_plan_to_agent_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
  style: api-first
  include:
    - create user
    - get user
defaults:
  auth: bearer
entities:
  user:
    operations:
      create:
        route:
          method: POST
          path: /users
        request_body:
          email: "{{generated_email}}"
        oracle:
          status_code: 201
        captures:
          - response.json.id -> user_id
      verify_exists:
        sql: SELECT id FROM users WHERE id = :user_id
        params:
          user_id: "{{user_id}}"
        expected_outcomes:
          - one row exists
cases:
  - id: create-user-success
    kind: api
    objective: Create user successfully
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
  - id: get-user-success
    kind: workflow
    objective: Get created user
    state_change: none
    setup:
      - use_entity: user
        operation: create
    execute:
      route:
        method: GET
        path: /users/{{user_id}}
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().compile_file(path)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertIsNotNone(result.compiled_plan)
        compiled_plan = result.compiled_plan
        assert compiled_plan is not None
        self.assertEqual(compiled_plan.metadata["input_mode"], "authoring_plan")
        self.assertEqual(compiled_plan.planned_test_cases[0].route.endpoint_path, "/users")
        self.assertEqual(compiled_plan.planned_test_cases[0].db_verification.sql, "SELECT id FROM users WHERE id = :user_id")
        self.assertEqual(compiled_plan.planned_test_cases[1].kind, "workflow")
        self.assertEqual(compiled_plan.planned_test_cases[1].workflow_steps[0].route.endpoint_path, "/users")
        self.assertEqual(compiled_plan.planned_test_cases[1].workflow_steps[1].route.endpoint_path, "/users/{{user_id}}")

    def test_compile_propagates_first_class_scenario_variables(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=["run_suffix = generated:run_suffix"],
            ),
            cases=[
                AuthoringCase(
                    id="create-user-success",
                    kind="api",
                    objective="Create user successfully",
                    state_change="none",
                    scenario_variables=["internal_api_token = env:INTERNAL_API_TOKEN"],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        self.assertEqual(result.compiled_plan.scenario_variables, ["run_suffix = generated:run_suffix"])
        self.assertEqual(
            result.compiled_plan.planned_test_cases[0].scenario_variables,
            ["internal_api_token = env:INTERNAL_API_TOKEN"],
        )

    def test_validate_file_blocks_yaml_map_defaults_scenario_variable_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
defaults:
  scenario_variables:
    - setup_display_name = template: Invalid Update {{run_suffix}}
cases:
  - id: get-users
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

            result = AuthoringPlanCompiler().validate_file(path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertIn(
            "authoring_scenario_variable_entry_invalid",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        diagnostic = next(
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_scenario_variable_entry_invalid"
        )
        self.assertEqual(diagnostic.details["field"], "defaults.scenario_variables[1]")
        self.assertEqual(diagnostic.details["entry_type"], "dict")

    def test_validate_file_blocks_yaml_map_case_scenario_variable_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
cases:
  - id: update-user
    kind: api
    objective: Update user.
    state_change: none
    scenario_variables:
      - submitted_display_name = template: Invalid Update {{run_suffix}}
    execute:
      route:
        method: PATCH
        path: /users/{{user_id}}
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostic = next(
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_scenario_variable_entry_invalid"
        )
        self.assertEqual(diagnostic.details["field"], "cases[1].scenario_variables[1]")
        self.assertEqual(diagnostic.details["owner"], "update-user")

    def test_validate_file_accepts_quoted_template_scenario_variable_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
defaults:
  scenario_variables:
    - "setup_display_name = template:Invalid Update {{run_suffix}}"
cases:
  - id: get-users
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

            result = AuthoringPlanCompiler().validate_file(path)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        self.assertEqual(
            result.compiled_plan.scenario_variables,
            ["setup_display_name = template:Invalid Update {{run_suffix}}"],
        )

    def test_compile_db_check_promotes_db_expected_outcomes_to_case_level(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-schema",
            project="code/demo",
            title="Users schema",
            goal="Verify persisted users schema.",
            scope=AuthoringScope(surface="users-table"),
            entities={
                "user_schema": AuthoringEntitySpec(
                    operations={
                        "verify_ready": AuthoringEntityOperation(
                            sql="SELECT COUNT(*) AS column_count FROM information_schema.columns WHERE table_name = 'users'",
                            expected_outcomes=["one row exists", "`column_count` = `5`"],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="users-schema-ready",
                    kind="db-check",
                    objective="Verify users schema is ready.",
                    state_change="none",
                    oracle=AuthoringOracle(
                        persisted_state=AuthoringPersistedStateRef(entity="user_schema", operation="verify_ready"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        compiled_case = result.compiled_plan.planned_test_cases[0]
        self.assertEqual(compiled_case.kind, "db")
        self.assertEqual(compiled_case.expected_outcomes, ["one row exists", "`column_count` = `5`"])
        self.assertIsNotNone(compiled_case.db_verification)
        assert compiled_case.db_verification is not None
        self.assertEqual(compiled_case.db_verification.expected_outcomes, compiled_case.expected_outcomes)

    def test_compile_reports_unknown_entity_operation(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities: {}
cases:
  - id: get-user-success
    kind: workflow
    objective: Get created user
    state_change: none
    setup:
      - use_entity: user
        operation: create
    execute:
      route:
        method: GET
        path: /users/{{user_id}}
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().compile_file(path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_unknown_entity", codes)
        self.assertIn("authoring_setup_reference_unresolved", codes)

    def test_compile_blocks_unknown_state_change(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="archive-user",
                    kind="api",
                    objective="Archive user",
                    state_change="archive",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/users/1/archive")),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_unknown_state_change", codes)

    def test_load_normalizes_known_state_change_to_enum(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """
version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
cases:
- id: create-user
  kind: api
  objective: Create user.
  state_change: CREATE
  execute:
    route:
      method: POST
      path: /users
  oracle:
    status_code: 201
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().load(path)

        self.assertFalse(result.diagnostics)
        self.assertIsNotNone(result.authoring_plan)
        assert result.authoring_plan is not None
        self.assertEqual(result.authoring_plan.cases[0].state_change, AuthoringStateChange.CREATE)

    def test_load_blocks_unknown_state_change_before_compile(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """
version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
cases:
- id: create-user
  kind: api
  objective: Create user.
  state_change: create active user
  execute:
    route:
      method: POST
      path: /users
  oracle:
    status_code: 201
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_unknown_state_change", codes)
        diagnostic = next(
            diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_unknown_state_change"
        )
        self.assertEqual(diagnostic.details["field"], "cases[1].state_change")
        self.assertIn("create", diagnostic.details["allowed_values"])

    def test_compile_blocks_duplicate_case_ids(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="duplicate-case",
                    kind="api",
                    objective="Create user",
                    state_change="none",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/users/1")),
                    oracle=AuthoringOracle(status_code=200),
                ),
                AuthoringCase(
                    id="duplicate-case",
                    kind="api",
                    objective="Read user again",
                    state_change="none",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/users/2")),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        duplicate_diagnostics = [
            diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_duplicate_case_id"
        ]
        self.assertEqual(len(duplicate_diagnostics), 1)
        self.assertEqual(duplicate_diagnostics[0].details["first_case_index"], 1)
        self.assertEqual(duplicate_diagnostics[0].details["duplicate_case_index"], 2)

    def test_compile_blocks_setup_operation_with_unresolved_entity_id_field(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            entities={
                "user": AuthoringEntitySpec(
                    id_field="user_id",
                    operations={
                        "suspend": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users/{{user_id}}/suspend"),
                            oracle=AuthoringOracle(status_code=200),
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="suspend-user",
                    kind="workflow",
                    objective="Suspend user",
                    state_change="none",
                    setup=[AuthoringSetupStep(use_entity="user", operation="suspend")],
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/users")),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_setup_entity_id_field_unresolved", codes)

    def test_compile_allows_setup_operation_with_entity_id_field_from_declared_variable(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=["missing_user_id = generated:uuid"],
            ),
            entities={
                "missing_user": AuthoringEntitySpec(
                    id_field="missing_user_id",
                    operations={
                        "bind_generated_id": AuthoringEntityOperation(
                            sql="SELECT :missing_user_id AS missing_user_id",
                            params={"missing_user_id": "{{missing_user_id}}"},
                            expected_outcomes=["one row exists"],
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="get-missing-user",
                    kind="workflow",
                    objective="Read missing user",
                    state_change="none",
                    setup=[AuthoringSetupStep(use_entity="missing_user", operation="bind_generated_id")],
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/users/{{missing_user_id}}")),
                    oracle=AuthoringOracle(status_code=404),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        compiled_case = result.compiled_plan.planned_test_cases[0]
        self.assertEqual(compiled_case.workflow_steps[0].params["missing_user_id"], "{{missing_user_id}}")
        self.assertEqual(compiled_case.workflow_steps[1].route.endpoint_path, "/users/{{missing_user_id}}")

    def test_compile_blocks_persisted_state_template_missing_entity_id_field(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            entities={
                "user": AuthoringEntitySpec(
                    id_field="user_id",
                    operations={
                        "verify_active": AuthoringEntityOperation(
                            sql="SELECT COUNT(*) AS row_count FROM users WHERE status = 'ACTIVE'",
                            expected_outcomes=["one row exists"],
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="create-user",
                    kind="api",
                    objective="Create user",
                    state_change="create",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/users")),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> user_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_active"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_persisted_state_id_field_missing", codes)

    def test_compile_blocks_persisted_state_template_mixing_id_and_entity_id_field(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="tenants-plan",
            project="code/demo",
            title="Tenants API",
            goal="Cover tenant API.",
            scope=AuthoringScope(surface="tenants-controller"),
            entities={
                "tenant": AuthoringEntitySpec(
                    id_field="tenant_id",
                    operations={
                        "verify_created": AuthoringEntityOperation(
                            sql="SELECT id, tenant_id FROM tenants WHERE id = :tenant_id",
                            params={"tenant_id": "{{tenant_id}}"},
                            expected_outcomes=[
                                "one row exists",
                                "`tenant_id` = `{{tenant_id}}`",
                            ],
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="create-tenant",
                    kind="api",
                    objective="Create tenant",
                    state_change="create",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/tenants")),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> tenant_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="tenant", operation="verify_created"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_persisted_state_id_field_semantic_mismatch", codes)

    def test_compile_allows_db_check_persisted_state_placeholders_from_declared_variables(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "run_suffix = generated:run_suffix",
                    "email_suffix = derived:run_suffix|lower",
                ],
            ),
            entities={
                "invalid_user": AuthoringEntitySpec(
                    operations={
                        "verify_invalid_creates_absent": AuthoringEntityOperation(
                            sql=(
                                "SELECT COUNT(*) AS invalid_user_count "
                                "FROM users "
                                "WHERE display_name LIKE 'AUTOTEST Invalid User ' || :run_suffix || '%' "
                                "OR email = 'autotest.invalid.' || :email_suffix || '@example.com'"
                            ),
                            params={
                                "run_suffix": "{{run_suffix}}",
                                "email_suffix": "{{email_suffix}}",
                            },
                            expected_outcomes=["one row exists", "`invalid_user_count` = `0`"],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="invalid-create-requests-do-not-persist",
                    kind="db-check",
                    objective="Invalid create requests do not persist users.",
                    state_change="none",
                    oracle=AuthoringOracle(
                        persisted_state=AuthoringPersistedStateRef(
                            entity="invalid_user",
                            operation="verify_invalid_creates_absent",
                        ),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        compiled_case = result.compiled_plan.planned_test_cases[0]
        assert compiled_case.db_verification is not None
        self.assertEqual(compiled_case.kind, "db")
        self.assertEqual(compiled_case.db_verification.params["run_suffix"], "{{run_suffix}}")
        self.assertEqual(compiled_case.db_verification.params["email_suffix"], "{{email_suffix}}")

    def test_compile_blocks_string_too_long_case_when_body_does_not_exceed_stated_boundary(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="update-user-name-too-long",
                    kind="api",
                    objective="Reject tenant names longer than 255 characters.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="PATCH", path="/users/1"),
                        body={"name": "A" * 255},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        mismatch_diagnostics = [
            diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_case_boundary_mismatch"
        ]
        self.assertEqual(len(mismatch_diagnostics), 1)
        self.assertEqual(mismatch_diagnostics[0].details["threshold"], 255)
        self.assertEqual(mismatch_diagnostics[0].details["actual_max_length"], 255)

    def test_compile_allows_string_too_long_case_when_body_exceeds_stated_boundary(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="update-user-name-too-long",
                    kind="api",
                    objective="Reject tenant names longer than 255 characters.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="PATCH", path="/users/1"),
                        body={"name": "A" * 256},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(any(diagnostic.code == "authoring_case_boundary_mismatch" for diagnostic in result.diagnostics))

    def test_compile_blocks_numeric_greater_than_case_when_param_does_not_exceed_threshold(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-limit-over-max",
                    kind="api",
                    objective="Reject list requests with limit greater than 100.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 100, "offset": 0},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        mismatch = next(diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_case_boundary_mismatch")
        self.assertEqual(mismatch.details["rule"], "greater_than")
        self.assertEqual(mismatch.details["field"], "limit")
        self.assertEqual(mismatch.details["threshold"], 100)
        self.assertEqual(mismatch.details["actual_values"], [100])

    def test_compile_allows_numeric_greater_than_case_when_param_exceeds_threshold(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-limit-over-max",
                    kind="api",
                    objective="Reject list requests with limit greater than 100.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 101, "offset": 0},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(any(diagnostic.code == "authoring_case_boundary_mismatch" for diagnostic in result.diagnostics))

    def test_compile_blocks_negative_offset_case_when_param_is_not_negative(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-negative-offset",
                    kind="api",
                    objective="Reject list request with negative offset.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 10, "offset": 0},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        mismatch = next(diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_case_boundary_mismatch")
        self.assertEqual(mismatch.details["rule"], "negative")
        self.assertEqual(mismatch.details["field"], "offset")
        self.assertEqual(mismatch.details["actual_values"], [0])

    def test_compile_allows_negative_offset_case_when_param_is_negative(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-negative-offset",
                    kind="api",
                    objective="Reject list request with negative offset.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 10, "offset": -1},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(any(diagnostic.code == "authoring_case_boundary_mismatch" for diagnostic in result.diagnostics))

    def test_compile_blocks_zero_limit_case_when_param_is_not_zero(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-zero-limit",
                    kind="api",
                    objective="Reject list request with zero limit.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 1, "offset": 0},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        mismatch = next(diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_case_boundary_mismatch")
        self.assertEqual(mismatch.details["rule"], "zero")
        self.assertEqual(mismatch.details["field"], "limit")
        self.assertEqual(mismatch.details["actual_values"], [1])

    def test_compile_allows_zero_limit_case_when_param_is_zero(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-zero-limit",
                    kind="api",
                    objective="Reject list request with zero limit.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 0, "offset": 0},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(any(diagnostic.code == "authoring_case_boundary_mismatch" for diagnostic in result.diagnostics))

    def test_compile_warns_when_email_expectation_reuses_non_lowercase_request_placeholder(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "run_suffix = generated:run_suffix",
                    "submitted_email = template:AUTOTEST.User.{{run_suffix}}@Example.COM",
                ]
            ),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "verify_exists": AuthoringEntityOperation(
                            sql="SELECT email FROM users WHERE id = :user_id",
                            params={"user_id": "{{user_id}}"},
                            expected_outcomes=["one row exists", "`email` = `{{submitted_email}}`"],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="create-user-success",
                    kind="api",
                    objective="Create user successfully.",
                    state_change="create",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users"),
                        body={"email": "{{submitted_email}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        business_checks=["response `email` = `{{submitted_email}}`"],
                        captures=["response.json.id -> user_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_exists"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        warnings = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_expected_value_case_ambiguous"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(str(warnings[0].severity).lower(), "warning")
        self.assertEqual(warnings[0].details["variables"], ["submitted_email"])

    def test_compile_skips_email_case_warning_when_expected_variable_is_lowercased(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "run_suffix = generated:run_suffix",
                    "email_suffix = derived:run_suffix|lower",
                    "submitted_email = template:AUTOTEST.User.{{email_suffix}}@Example.COM",
                    "expected_email = derived:submitted_email|lower",
                ]
            ),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "verify_exists": AuthoringEntityOperation(
                            sql="SELECT email FROM users WHERE id = :user_id",
                            params={"user_id": "{{user_id}}"},
                            expected_outcomes=["one row exists", "`email` = `{{expected_email}}`"],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="create-user-success",
                    kind="api",
                    objective="Create user successfully.",
                    state_change="create",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users"),
                        body={"email": "{{submitted_email}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        business_checks=["response `email` = `{{expected_email}}`"],
                        captures=["response.json.id -> user_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_exists"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(any(diagnostic.code == "authoring_expected_value_case_ambiguous" for diagnostic in result.diagnostics))

    def test_compile_warns_when_activate_success_setup_ends_archived(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            entities={
                "user": AuthoringEntitySpec(
                    id_field="user_id",
                    operations={
                        "create": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users"),
                            captures=["response.json.id -> user_id"],
                        ),
                        "archive": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users/{{user_id}}/archive"),
                        ),
                        "verify_active": AuthoringEntityOperation(
                            sql="SELECT status FROM users WHERE id = :user_id",
                            params={"user_id": "{{user_id}}"},
                            expected_outcomes=["one row exists", "`status` = `ACTIVE`"],
                        ),
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="activate-user-success",
                    kind="workflow",
                    title="Activate suspended user",
                    objective="Activate a suspended user successfully.",
                    state_change="none",
                    setup=[
                        AuthoringSetupStep(use_entity="user", operation="create"),
                        AuthoringSetupStep(use_entity="user", operation="archive"),
                    ],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users/{{user_id}}/activate"),
                    ),
                    oracle=AuthoringOracle(
                        status_code=200,
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_active"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        warnings = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_workflow_setup_state_mismatch"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].details["expected_state"], "suspended")
        self.assertEqual(warnings[0].details["actual_state"], "archived")

    def test_compile_warns_when_archived_user_case_setup_is_only_suspended(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "create": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users"),
                            captures=["response.json.id -> user_id"],
                        ),
                        "suspend": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users/{{user_id}}/suspend"),
                        ),
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="update-archived-user-bad-request",
                    kind="workflow",
                    title="Reject archived user update",
                    objective="Reject profile update for archived user.",
                    state_change="none",
                    setup=[
                        AuthoringSetupStep(use_entity="user", operation="create"),
                        AuthoringSetupStep(use_entity="user", operation="suspend"),
                    ],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="PATCH", path="/users/{{user_id}}"),
                        body={"displayName": "Updated"},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        warnings = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_workflow_setup_state_mismatch"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].details["expected_state"], "archived")
        self.assertEqual(warnings[0].details["actual_state"], "suspended")

    def test_compile_warns_when_same_state_lifecycle_behavior_is_only_inferred(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "create": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users"),
                            captures=["response.json.id -> user_id"],
                        ),
                        "archive": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users/{{user_id}}/archive"),
                        ),
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="archive-archived-user",
                    kind="workflow",
                    title="Reject archiving archived user",
                    objective="Verify archive for archived user is handled correctly.",
                    state_change="none",
                    setup=[
                        AuthoringSetupStep(use_entity="user", operation="create"),
                        AuthoringSetupStep(use_entity="user", operation="archive"),
                    ],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users/{{user_id}}/archive"),
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        warnings = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_same_state_lifecycle_contract_unconfirmed"
        ]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].details["actual_state"], "archived")
        self.assertEqual(warnings[0].details["target_state"], "archived")

    def test_compile_file_blocks_when_authored_entity_is_missing_from_entity_inventory(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0001"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: account
    id_field: user_id
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations: []
routes:
  - method: GET
    path: /users/{{user_id}}
    success_status: 200
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations: {}
cases:
  - id: get-user
    kind: api
    objective: Get user.
    state_change: none
    execute:
      route:
        method: GET
        path: /users/{{user_id}}
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().compile_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_stage_inventory_entity_mismatch", codes)

    def test_compile_file_blocks_when_route_status_disagrees_with_operation_inventory(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0002"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
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
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create
    effect_state: ACTIVE
routes:
  - method: POST
    path: /users
    success_status: 201
    failure_statuses: [400]
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
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
cases:
  - id: create-user
    kind: api
    objective: Create user.
    state_change: none
    execute:
      route:
        method: POST
        path: /users
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_stage_inventory_status_mismatch"]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["inventory_success_status"], 201)
        self.assertEqual(diagnostics[0].details["authored_status"], 200)

    def test_compile_file_blocks_when_workflow_setup_state_disagrees_with_inventory_precondition(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0003"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
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
source_id: users-plan
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
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
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
    title: Activate suspended user
    objective: Activate a suspended user successfully.
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

            result = AuthoringPlanCompiler().compile_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_stage_inventory_state_mismatch"]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["expected_state"], "suspended")
        self.assertEqual(diagnostics[0].details["actual_state"], "archived")

    def test_compile_file_blocks_when_same_state_lifecycle_contract_is_missing_from_inventory(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0004"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
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
source_id: users-plan
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
    path: /users/{{user_id}}/archive
    success_status: 200
    failure_statuses: [400, 404]
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
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
cases:
  - id: archive-archived-user
    kind: workflow
    title: Reject archiving archived user
    objective: Reject archiving archived user.
    state_change: none
    setup:
      - use_entity: user
        operation: create
      - use_entity: user
        operation: archive
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/archive
    oracle:
      status_code: 400
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_stage_inventory_same_state_behavior_missing"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("same_state_behavior", diagnostics[0].details["missing_fields"])
        self.assertIn("same_state_status", diagnostics[0].details["missing_fields"])

    def test_compile_file_blocks_when_same_state_lifecycle_status_conflicts_with_inventory(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0005"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
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
source_id: users-plan
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
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
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
cases:
  - id: archive-archived-user
    kind: workflow
    title: Reject archiving archived user
    objective: Reject archiving archived user.
    state_change: none
    setup:
      - use_entity: user
        operation: create
      - use_entity: user
        operation: archive
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/archive
    oracle:
      status_code: 400
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_stage_inventory_same_state_mismatch"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["inventory_same_state_status"], 200)
        self.assertEqual(diagnostics[0].details["authored_status"], 400)


if __name__ == "__main__":
    unittest.main()
