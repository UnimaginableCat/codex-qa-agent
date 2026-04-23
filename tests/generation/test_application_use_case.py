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
    GenerationSourceInput,
    NormalizedTestPlan,
    PlannedRouteIntent,
    SourceInputFormat,
)
from tools.generation.evidence.models import CodeFactsScope, TargetStack


class GenerateTestPlanUseCaseTests(unittest.TestCase):
    def test_use_case_is_stable_entrypoint_for_prose_to_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id="tenant-api",
                        project="code/demo",
                        content="Нужен тест-план на internal tenants API: create, get, list, patch, invalid status transition, missing entity",
                    ),
                    workspace_root=root,
                )
            )
            plan_payload = json.loads(result.artifact_paths["normalized_plan"].read_text(encoding="utf-8"))

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertIsInstance(result.normalized_plan, NormalizedTestPlan)
        self.assertGreaterEqual(len(result.normalized_plan.test_cases), 6)
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
                goal="Cover session authentication, listing, lookup, and revocation.",
                planned_test_cases=[
                    AgentPlannedTestCaseInput(
                        title="Authenticate internal user session",
                        objective="Verify successful session authentication.",
                        actions=["Call the authenticate endpoint with valid credentials."],
                        expected_outcomes=["A session is created and returned."],
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
                        expected_outcomes=["All active sessions are invalidated."],
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
            source_input_payload = json.loads(result.artifact_paths["source_input"].read_text(encoding="utf-8"))
            source_payload = json.loads(result.artifact_paths["normalized_source"].read_text(encoding="utf-8"))

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertEqual(result.details["input_mode"], "agent_plan")
        self.assertEqual(result.details["phase"], "agent_plan_generation")
        self.assertEqual(result.normalized_plan.metadata["generation_phase"], "agent_plan_generation")
        self.assertEqual(result.normalized_plan.metadata["input_mode"], "agent_plan")
        self.assertEqual(result.normalized_plan.title, "Internal user session API")
        self.assertEqual(len(result.normalized_plan.test_cases), 2)
        self.assertEqual(result.normalized_plan.test_cases[0].case_id, "tc-001")
        self.assertEqual(result.normalized_plan.test_cases[0].steps[0], "Call the authenticate endpoint with valid credentials.")
        self.assertEqual(
            result.normalized_plan.test_cases[0].planned_route.endpoint_path,
            "/api/internal/v1/user-sessions/authenticate",
        )
        self.assertEqual(result.normalized_plan.test_cases[1].open_questions, ["Exact auth strategy is not specified."])
        self.assertEqual(plan_payload["metadata"]["generation_phase"], "agent_plan_generation")
        self.assertEqual(source_input_payload["input_format"], "structured")
        self.assertIn("planned_test_cases", json.loads(source_input_payload["content"]))
        self.assertEqual(source_payload["metadata"]["normalizer"], "agent-plan-adapter-v1")
        self.assertTrue(
            any(link.relation == "agent_plan_case_to_test_case" for link in result.traceability_map.links)
        )

    def test_use_case_propagates_blocking_diagnostics(self) -> None:
        with TemporaryDirectory() as tmp:
            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id="empty",
                        project="code/demo",
                    ),
                    workspace_root=Path(tmp),
                )
            )

        self.assertEqual(result.final_status, StepStatus.BLOCKED)
        self.assertTrue(any(diagnostic.code == "source_content_empty" for diagnostic in result.diagnostics))
        self.assertEqual(result.normalized_plan.test_cases, [])

    def test_use_case_keeps_structured_input_as_future_path_without_normalizer_coupling(self) -> None:
        with TemporaryDirectory() as tmp:
            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id="structured",
                        project="code/demo",
                        input_format=SourceInputFormat.STRUCTURED,
                        content='{"cases": []}',
                    ),
                    workspace_root=Path(tmp),
                )
            )

        self.assertEqual(result.final_status, StepStatus.BLOCKED)
        self.assertTrue(any(diagnostic.code == "unsupported_source_format" for diagnostic in result.diagnostics))

    def test_agent_plan_validation_reports_invalid_input_without_prose_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            agent_plan = AgentTestPlanInput(
                source_id="broken",
                project="code/demo",
                title="",
                planned_test_cases=[
                    AgentPlannedTestCaseInput(
                        title="",
                        objective="",
                    )
                ],
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
        self.assertNotIn("unsupported_source_format", diagnostic_codes)

    def test_use_case_can_run_without_persisting_artifacts_for_skill_or_tests(self) -> None:
        with TemporaryDirectory() as tmp:
            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id="users",
                        project="code/demo",
                        content="Проверить создание пользователя, получение пользователя по id",
                    ),
                    workspace_root=Path(tmp),
                    options=GenerateTestPlanOptions(persist_artifacts=False),
                )
            )

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertEqual(result.artifact_paths, {})
        self.assertEqual(len(result.normalized_plan.test_cases), 2)

    def test_use_case_returns_evidence_bundle_when_code_facts_are_enabled(self) -> None:
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

            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id="users",
                        project="code/demo",
                        content="Verify create user and get user by id",
                    ),
                    workspace_root=root,
                    project_path=project,
                    evidence_scope=CodeFactsScope(scope_id="api", paths=[Path("api.py")]),
                    options=GenerateTestPlanOptions(collect_code_facts=True),
                )
            )

            self.assertEqual(result.final_status, StepStatus.PASS)
            self.assertIsNotNone(result.evidence_bundle)
            self.assertEqual(result.details["code_facts"], "collected")
            self.assertEqual(result.evidence_bundle.facts[0].payload["endpoint_path"], "/users")
            self.assertEqual(result.evidence_bundle.facts[0].payload["http_method"], "POST")
            self.assertTrue(result.artifact_paths["evidence"].exists())
            self.assertTrue((result.run_context.artifact_dir / "evidence-bundle.json").exists())
            self.assertEqual(result.normalized_plan.project, "code/demo")

    def test_use_case_applies_enrichment_when_enabled_with_evidence(self) -> None:
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

            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id="users",
                        project="code/demo",
                        content="Verify create user",
                    ),
                    workspace_root=root,
                    project_path=project,
                    evidence_scope=CodeFactsScope(scope_id="api", paths=[Path("api.py")]),
                    options=GenerateTestPlanOptions(
                        collect_code_facts=True,
                        enrichment_enabled=True,
                    ),
                )
            )

            self.assertEqual(result.final_status, StepStatus.PASS)
            self.assertIsNotNone(result.enrichment_result)
            self.assertEqual(result.details["enrichment"], "applied")
            self.assertEqual(result.enrichment_result.applied_evidence[0].case_id, "tc-001")
            self.assertEqual(
                result.normalized_plan.test_cases[0].metadata["evidence_hints"][0]["applied_fields"][
                    "endpoint_path"
                ],
                "/users",
            )
            self.assertTrue(result.artifact_paths["enrichment_result"].exists())
            self.assertTrue(result.artifact_paths["enriched_plan"].exists())
            self.assertTrue((result.run_context.artifact_dir / "applied-evidence.json").exists())
            self.assertTrue(
                any(link.relation == "evidence_supports_case" for link in result.traceability_map.links)
            )

    def test_agent_plan_input_continues_through_evidence_enrichment(self) -> None:
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
            agent_plan = AgentTestPlanInput(
                source_id="users-agent-plan",
                project="code/demo",
                title="Users API",
                planned_test_cases=[
                    AgentPlannedTestCaseInput(
                        title="Create user",
                        objective="Verify user creation.",
                        actions=["Call the create user API."],
                        expected_outcomes=["User is created."],
                        unresolved_items=["API endpoint executable detail is not resolved."],
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
                    project_path=project,
                    evidence_scope=CodeFactsScope(scope_id="api", paths=[Path("api.py")]),
                    options=GenerateTestPlanOptions(
                        collect_code_facts=True,
                        enrichment_enabled=True,
                    ),
                )
            )

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertEqual(result.details["input_mode"], "agent_plan")
        self.assertIsNotNone(result.evidence_bundle)
        self.assertIsNotNone(result.enrichment_result)
        self.assertEqual(result.enrichment_result.applied_evidence[0].case_id, "tc-001")
        self.assertEqual(
            result.normalized_plan.test_cases[0].metadata["route_hints"][0]["endpoint_path"],
            "/users",
        )
        self.assertEqual(result.normalized_plan.test_cases[0].support.route_hints[0].endpoint_path, "/users")

    def test_use_case_uses_agent_plan_evidence_scope_when_request_scope_missing(self) -> None:
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
            agent_plan = AgentTestPlanInput(
                source_id="users-agent-plan",
                project="code/demo",
                title="Users API",
                evidence_scope={"paths": ["api.py"], "stack_hint": "python"},
                planned_test_cases=[
                    AgentPlannedTestCaseInput(title="Create user", objective="Verify create user.")
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
                    project_path=project,
                    options=GenerateTestPlanOptions(collect_code_facts=True),
                )
            )

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertIsNotNone(result.evidence_bundle)
        self.assertEqual(result.evidence_bundle.facts[0].payload["endpoint_path"], "/users")

    def test_request_evidence_scope_overrides_agent_plan_scope(self) -> None:
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
            (project / "unused.py").write_text("x = 1\n", encoding="utf-8")
            agent_plan = AgentTestPlanInput(
                source_id="users-agent-plan",
                project="code/demo",
                title="Users API",
                evidence_scope={"paths": ["unused.py"], "stack_hint": "python"},
                planned_test_cases=[
                    AgentPlannedTestCaseInput(title="Create user", objective="Verify create user.")
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
                    project_path=project,
                    evidence_scope=CodeFactsScope(scope_id="api", paths=[Path("api.py")]),
                    options=GenerateTestPlanOptions(collect_code_facts=True),
                )
            )

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertIsNotNone(result.evidence_bundle)
        self.assertEqual(result.evidence_bundle.facts[0].payload["endpoint_path"], "/users")

    def test_agent_plan_with_explicit_route_can_render_drafts_without_evidence(self) -> None:
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
                        actions=["Call the create user API."],
                        expected_outcomes=["User is created."],
                        route=PlannedRouteIntent(
                            http_method="POST",
                            endpoint_path="/users",
                            path_kind="collection",
                        ),
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
        self.assertIsNotNone(result.scenario_render_result)
        self.assertEqual(len(result.scenario_render_result.draft_set.drafts), 1)
        self.assertEqual(result.scenario_render_result.validation_results[0].parse_valid, True)

    def test_use_case_skips_enrichment_without_evidence_collection(self) -> None:
        with TemporaryDirectory() as tmp:
            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id="users",
                        project="code/demo",
                        content="Verify create user",
                    ),
                    workspace_root=Path(tmp),
                    options=GenerateTestPlanOptions(enrichment_enabled=True),
                )
            )

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertIsNone(result.enrichment_result)
        self.assertTrue(any(diagnostic.code == "enrichment_requires_evidence" for diagnostic in result.diagnostics))

    def test_use_case_collects_java_spring_evidence_for_controller_scope(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "code" / "demo"
            controller = project / "src" / "main" / "java" / "demo" / "UserController.java"
            controller.parent.mkdir(parents=True)
            controller.write_text(
                "\n".join(
                    [
                        "import org.springframework.web.bind.annotation.*;",
                        "@RestController",
                        '@RequestMapping("/api/users")',
                        "public class UserController {",
                        '  @GetMapping("/{id}")',
                        "  public UserDto getUser() { return null; }",
                        "}",
                    ]
                ),
                encoding="utf-8",
            )

            result = GenerateTestPlanUseCase().execute(
                GenerateTestPlanRequest(
                    source_input=GenerationSourceInput(
                        source_id="users-java",
                        project="code/demo",
                        content="Verify get user by id",
                    ),
                    workspace_root=root,
                    project_path=project,
                    evidence_scope=CodeFactsScope(
                        scope_id="api",
                        paths=[Path("src/main/java/demo/UserController.java")],
                        stack_hint=TargetStack.JAVA_SPRING,
                    ),
                    options=GenerateTestPlanOptions(collect_code_facts=True),
                )
            )

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertIsNotNone(result.evidence_bundle)
        self.assertEqual(result.evidence_bundle.facts[0].payload["endpoint_path"], "/api/users/{id}")
        self.assertEqual(result.evidence_bundle.facts[0].payload["http_method"], "GET")
        self.assertEqual(result.evidence_bundle.facts[0].payload["controller_name"], "UserController")


if __name__ == "__main__":
    unittest.main()
