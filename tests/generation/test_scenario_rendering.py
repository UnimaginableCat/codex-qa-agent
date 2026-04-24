from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation.domain.models import (
    GapCategory,
    GenerationRunContext,
    NormalizedTestPlan,
    PlannedCaseGap,
    PlannedCaseSupport,
    PlannedRouteIntent,
    PlannedTestCase,
    PlannedWorkflowStep,
    RouteSupportHint,
)
from tools.generation.persistence.artifacts import GENERATION_ARTIFACTS_DIRNAME, FileGenerationArtifactStore
from tools.generation.rendering import DraftScenarioRenderer, ScenarioDraftPreviewService, ScenarioRenderResult
from tools.scenario_runner.parser import MarkdownScenarioParser


class ScenarioRenderingTests(unittest.TestCase):
    def test_renderer_creates_parser_valid_draft_for_planned_route_case(self) -> None:
        plan = _plan([_planned_route_case()])

        render_result = DraftScenarioRenderer().render(plan)

        self.assertEqual(len(render_result.draft_set.drafts), 1)
        draft = render_result.draft_set.drafts[0]
        self.assertIn("Method: POST", draft.markdown)
        self.assertIn("Path: /users", draft.markdown)
        self.assertIn("Route source: planned_route.", draft.markdown)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "draft.md"
            path.write_text(draft.markdown, encoding="utf-8")
            parse_result = MarkdownScenarioParser().parse_result(path)

        self.assertFalse(parse_result.has_errors)

    def test_renderer_defers_case_without_authored_route(self) -> None:
        plan = _plan([PlannedTestCase(case_id="tc-001", title="Create user", objective="Verify create user.")])

        render_result = DraftScenarioRenderer().render(plan)

        self.assertEqual(render_result.draft_set.drafts, [])
        self.assertEqual(render_result.unsupported_checks[0].reason_code, "missing_planned_route")

    def test_renderer_defers_case_with_execution_blocking_gap(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Get existing user",
                    objective="Verify get user by seeded id.",
                    expected_results=["HTTP 200"],
                    planned_route=PlannedRouteIntent(http_method="GET", endpoint_path="/users/{{user_id}}"),
                    gaps=[
                        PlannedCaseGap(
                            category=GapCategory.DATA_SETUP,
                            message="A seeded or previously created user_id must be supplied.",
                        )
                    ],
                )
            ]
        )

        render_result = DraftScenarioRenderer().render(plan)

        self.assertEqual(render_result.draft_set.drafts, [])
        self.assertEqual(len(render_result.draft_set.deferred_items), 1)
        self.assertEqual(render_result.unsupported_checks[0].reason_code, "data_setup_unresolved")

    def test_renderer_can_still_use_route_hints_metadata(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="List users",
                    objective="Verify list users.",
                    support=PlannedCaseSupport(
                        readiness="route_resolved",
                        route_hints=[
                            RouteSupportHint(
                                endpoint_path="/users",
                                http_method="GET",
                                confidence="explicit",
                                route_source="route_hints",
                            )
                        ],
                    ),
                )
            ]
        )

        render_result = DraftScenarioRenderer().render(plan)

        self.assertEqual(len(render_result.draft_set.drafts), 1)
        self.assertIn("Route source: route_hints.", render_result.draft_set.drafts[0].markdown)

    def test_renderer_renders_db_only_workflow_case(self) -> None:
        render_result = DraftScenarioRenderer().render(
            _plan(
                [
                    PlannedTestCase(
                        case_id="tc-db-001",
                        title="Verify schema row shape",
                        objective="Verify users table schema metadata.",
                        workflow_steps=[
                            PlannedWorkflowStep(
                                step_type="db",
                                title="Check users schema",
                                sql="SELECT 1 AS expected_column_count",
                                expected_outcomes=["one row exists", "`expected_column_count` = `1`"],
                            )
                        ],
                    )
                ]
            )
        )

        self.assertEqual(len(render_result.draft_set.drafts), 1)
        draft = render_result.draft_set.drafts[0]
        self.assertIn("### Step 1", draft.markdown)
        self.assertEqual(draft.metadata["route_binding"]["route_source"], "workflow_db_only")
        self.assertEqual(render_result.draft_set.deferred_items, [])

    def test_renderer_renders_multi_step_workflow_case(self) -> None:
        render_result = DraftScenarioRenderer().render(
            _plan(
                [
                    PlannedTestCase(
                        case_id="tc-001",
                        title="Authenticate and revoke session",
                        objective="Verify the full session lifecycle.",
                        workflow_steps=[
                            PlannedWorkflowStep(
                                step_type="api",
                                title="Authenticate session",
                                route=PlannedRouteIntent(http_method="POST", endpoint_path="/api/sessions/authenticate"),
                                expected_outcomes=["HTTP 200"],
                            ),
                            PlannedWorkflowStep(
                                step_type="api",
                                title="Revoke session",
                                route=PlannedRouteIntent(http_method="POST", endpoint_path="/api/sessions/{{session_id}}/revoke"),
                                expected_outcomes=["HTTP 204"],
                            ),
                        ],
                    )
                ]
            )
        )

        self.assertEqual(len(render_result.draft_set.drafts), 1)
        draft = render_result.draft_set.drafts[0]
        self.assertIn("### Step 1", draft.markdown)
        self.assertIn("### Step 2", draft.markdown)
        self.assertIn("DB verification required: yes.", draft.markdown)

    def test_preview_service_persists_drafts_and_parse_results(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _context(root)
            context.artifact_dir.mkdir(parents=True)
            store = FileGenerationArtifactStore()

            render_result, artifact_paths = ScenarioDraftPreviewService().render_and_persist(
                _plan([_planned_route_case()]),
                context,
                store,
            )

            result_payload = ScenarioRenderResult.from_dict(
                json.loads((context.artifact_dir / "scenario-render-result.json").read_text(encoding="utf-8"))
            )
            self.assertEqual(len(render_result.validation_results), 1)
            self.assertTrue(render_result.validation_results[0].parse_valid)
            self.assertTrue((context.artifact_dir / "scenario-drafts").exists())
            self.assertTrue((context.artifact_dir / "scenario-parse-results.json").exists())
            self.assertEqual(artifact_paths["scenario_render_result"].name, "scenario-render-result.json")
            self.assertTrue(result_payload.validation_results[0].parse_valid)


def _plan(cases: list[PlannedTestCase]) -> NormalizedTestPlan:
    return NormalizedTestPlan(
        plan_id="plan-users",
        source_id="users",
        project="code/demo",
        title="Users API",
        test_cases=cases,
    )


def _planned_route_case() -> PlannedTestCase:
    return PlannedTestCase(
        case_id="tc-001",
        title="Create user",
        objective="Verify create user.",
        expected_results=["HTTP 201"],
        planned_route=PlannedRouteIntent(http_method="POST", endpoint_path="/users", path_kind="collection"),
    )


def _context(root: Path) -> GenerationRunContext:
    return GenerationRunContext(
        run_id="gen-1",
        workspace_root=root,
        source_id="src-1",
        project="code/demo",
        artifacts_root_dir=root / GENERATION_ARTIFACTS_DIRNAME,
        artifact_dir=root / GENERATION_ARTIFACTS_DIRNAME / "src-1-gen-1",
        started_at="2026-04-23T08:00:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
