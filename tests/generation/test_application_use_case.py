from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.generation.application.models import (
    GenerateTestPlanOptions,
    GenerateTestPlanRequest,
    GenerationInputMode,
)
from tools.generation.application.use_cases import GenerateTestPlanUseCase
from tools.generation.domain.models import (
    AgentPlannedTestCaseInput,
    AgentTestPlanInput,
    GapCategory,
    GenerationSourceInput,
    NormalizedTestPlan,
    PlannedRouteIntent,
    SourceInputFormat,
)


class GenerateTestPlanUseCaseTests(unittest.TestCase):
    def test_use_case_is_stable_entrypoint_for_prose_to_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id="tenant-api",
                        project="code/demo",
                        content="Verify create tenant, get tenant by id, and list tenants",
                    ),
                    workspace_root=root,
                )
            )
            plan_payload = json.loads(result.artifact_paths["normalized_plan"].read_text(encoding="utf-8"))

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertIsInstance(result.normalized_plan, NormalizedTestPlan)
        self.assertGreaterEqual(len(result.normalized_plan.test_cases), 3)
        self.assertEqual(result.details["application_use_case"], "GenerateTestPlanUseCase")
        self.assertEqual(result.details["input_mode"], "prose")
        self.assertEqual(plan_payload["metadata"]["generation_phase"], "prose_plan_generation")

    def test_use_case_accepts_agent_plan_input_as_primary_path(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_plan = AgentTestPlanInput(
                source_id="internal-user-sessions",
                project="code/demo",
                title="Internal user session API",
                goal="Cover session authentication and revoke-all behavior.",
                planned_test_cases=[
                    AgentPlannedTestCaseInput(
                        title="Authenticate internal user session",
                        objective="Verify successful session authentication.",
                        actions=["Call the authenticate endpoint with valid credentials."],
                        expected_outcomes=["HTTP 200"],
                        priority="high",
                        tags=["api", "happy-path"],
                        route=PlannedRouteIntent(
                            http_method="POST",
                            endpoint_path="/api/internal/v1/user-sessions/authenticate",
                            path_kind="collection",
                        ),
                    ),
                    AgentPlannedTestCaseInput(
                        title="Revoke all sessions",
                        objective="Verify all active sessions can be revoked.",
                        actions=["Call the revoke all sessions endpoint."],
                        expected_outcomes=["HTTP 200"],
                        unresolved_items=["Exact auth strategy is not specified."],
                    ),
                ],
                assumptions=["Agent decomposition was authored from operator intent."],
                open_questions=["Which credentials fixture should be used?"],
            )

            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id=agent_plan.source_id,
                        project=agent_plan.project,
                        input_format=SourceInputFormat.STRUCTURED,
                        name=agent_plan.title,
                    ),
                    input_mode=GenerationInputMode.AGENT_PLAN,
                    agent_plan=agent_plan,
                    workspace_root=root,
                )
            )
            plan_payload = json.loads(result.artifact_paths["normalized_plan"].read_text(encoding="utf-8"))

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertEqual(result.details["input_mode"], "agent_plan")
        self.assertEqual(result.normalized_plan.test_cases[0].planned_route.endpoint_path, "/api/internal/v1/user-sessions/authenticate")
        self.assertEqual(result.normalized_plan.test_cases[1].gaps[0].category, GapCategory.AUTH_STRATEGY)
        self.assertEqual(plan_payload["metadata"]["generation_phase"], "agent_plan_generation")

    def test_agent_plan_validation_reports_invalid_input_without_prose_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            agent_plan = AgentTestPlanInput(
                source_id="broken",
                project="code/demo",
                title="",
                planned_test_cases=[AgentPlannedTestCaseInput(title="", objective="")],
            )
            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id="broken",
                        project="code/demo",
                        input_format=SourceInputFormat.STRUCTURED,
                    ),
                    input_mode=GenerationInputMode.AGENT_PLAN,
                    agent_plan=agent_plan,
                    workspace_root=Path(tmp),
                )
            )

        diagnostic_codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertEqual(result.final_status, StepStatus.BLOCKED)
        self.assertIn("agent_plan_missing_title", diagnostic_codes)
        self.assertIn("agent_plan_case_missing_title", diagnostic_codes)
        self.assertIn("agent_plan_case_missing_objective", diagnostic_codes)

    def test_use_case_can_run_without_persisting_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id="users",
                        project="code/demo",
                        content="Verify create user and get user by id",
                    ),
                    workspace_root=Path(tmp),
                    options=GenerateTestPlanOptions(persist_artifacts=False),
                )
            )

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertEqual(result.artifact_paths, {})
        self.assertEqual(len(result.normalized_plan.test_cases), 2)

    def test_agent_plan_with_explicit_route_can_render_drafts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_plan = AgentTestPlanInput(
                source_id="users-agent-plan",
                project="code/demo",
                title="Users API",
                planned_test_cases=[
                    AgentPlannedTestCaseInput(
                        title="Create user",
                        objective="Verify user creation.",
                        actions=["POST the user create endpoint."],
                        expected_outcomes=["HTTP 201"],
                        route=PlannedRouteIntent(http_method="POST", endpoint_path="/users", path_kind="collection"),
                    )
                ],
            )

            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id=agent_plan.source_id,
                        project=agent_plan.project,
                        input_format=SourceInputFormat.STRUCTURED,
                        name=agent_plan.title,
                    ),
                    input_mode=GenerationInputMode.AGENT_PLAN,
                    agent_plan=agent_plan,
                    workspace_root=root,
                    options=GenerateTestPlanOptions(render_scenario_drafts=True),
                )
            )

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertEqual(result.details["scenario_rendering"], "rendered")
        self.assertIsNotNone(result.scenario_render_result)
        self.assertEqual(len(result.scenario_render_result.draft_set.drafts), 1)
        self.assertIn("scenario_render_result", result.artifact_paths)


if __name__ == "__main__":
    unittest.main()
