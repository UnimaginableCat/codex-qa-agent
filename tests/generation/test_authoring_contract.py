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


if __name__ == "__main__":
    unittest.main()
