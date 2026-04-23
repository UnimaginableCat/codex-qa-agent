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
    PlannedCaseSupport,
    PlannedCaseGap,
    PlannedRouteIntent,
    PlannedTestCase,
    RouteSupportHint,
)
from tools.generation.persistence.artifacts import (
    GENERATION_ARTIFACTS_DIRNAME,
    GENERATION_RUNS_DIRNAME,
    FileGenerationArtifactStore,
)
from tools.generation.rendering import (
    DraftScenarioRenderer,
    ScenarioDraftPreviewService,
    ScenarioRenderResult,
)
from tools.scenario_runner.parser import MarkdownScenarioParser


class ScenarioRenderingTests(unittest.TestCase):
    def test_renderer_creates_parser_valid_draft_for_evidence_supported_case(self) -> None:
        plan = _plan([_supported_case()])

        render_result = DraftScenarioRenderer().render(plan)

        self.assertEqual(len(render_result.draft_set.drafts), 1)
        draft = render_result.draft_set.drafts[0]
        self.assertIn("Type: api", draft.markdown)
        self.assertIn("Method: POST", draft.markdown)
        self.assertIn("Path: /users", draft.markdown)
        self.assertIn("Route resolved for preview rendering.", draft.markdown)
        self.assertTrue(any(item.code == "route_used_for_rendering" for item in render_result.diagnostics))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "draft.md"
            path.write_text(draft.markdown, encoding="utf-8")
            parse_result = MarkdownScenarioParser().parse_result(path)

        self.assertFalse(parse_result.has_errors)

    def test_renderer_defers_case_without_endpoint_evidence(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Create user",
                    objective="Verify create user.",
                )
            ]
        )

        render_result = DraftScenarioRenderer().render(plan)

        self.assertEqual(render_result.draft_set.drafts, [])
        self.assertEqual(render_result.draft_set.deferred_items[0].reason_code, "unsupported_for_preview")
        self.assertEqual(render_result.unsupported_checks[0].reason_code, "missing_endpoint_evidence")
        self.assertTrue(any(diagnostic.code == "scenario_draft_deferred" for diagnostic in render_result.diagnostics))

    def test_renderer_uses_route_hints_for_route_resolved_case(self) -> None:
        plan = _plan([_route_supported_case("Authenticate session", "/api/sessions/authenticate", "POST")])

        render_result = DraftScenarioRenderer().render(plan)

        self.assertEqual(len(render_result.draft_set.drafts), 1)
        draft = render_result.draft_set.drafts[0]
        self.assertIn("Method: POST", draft.markdown)
        self.assertIn("Path: /api/sessions/authenticate", draft.markdown)
        self.assertIn("Route source: route_hints.", draft.markdown)
        self.assertTrue(any(item.code == "rendering_based_on_route_hints" for item in render_result.diagnostics))

    def test_renderer_renders_case_from_explicit_planned_route_without_evidence(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Revoke all sessions",
                    objective="Verify revoke all sessions.",
                    planned_route=PlannedRouteIntent(
                        http_method="POST",
                        endpoint_path="/api/sessions/revoke-all",
                        path_kind="collection",
                    ),
                )
            ]
        )

        render_result = DraftScenarioRenderer().render(plan)

        self.assertEqual(len(render_result.draft_set.drafts), 1)
        draft = render_result.draft_set.drafts[0]
        self.assertIn("Method: POST", draft.markdown)
        self.assertIn("Path: /api/sessions/revoke-all", draft.markdown)
        self.assertIn("Route source: planned_route.", draft.markdown)
        self.assertTrue(any(item.code == "rendering_based_on_planned_route" for item in render_result.diagnostics))

    def test_renderer_uses_typed_support_route_hints_without_legacy_metadata(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Create user",
                    objective="Verify create user.",
                    support=PlannedCaseSupport(
                        readiness="evidence_supported",
                        route_hints=[
                            RouteSupportHint(
                                fact_id="fact-create-user",
                                endpoint_path="/users",
                                http_method="POST",
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
        self.assertEqual(
            render_result.draft_set.drafts[0].metadata["case_support"]["route_hints"][0]["endpoint_path"],
            "/users",
        )

    def test_renderer_projects_case_gaps_into_draft_metadata(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Create user",
                    objective="Verify create user.",
                    planned_route=PlannedRouteIntent(http_method="POST", endpoint_path="/users"),
                    gaps=[
                        PlannedCaseGap(
                            category=GapCategory.AUTH_STRATEGY,
                            message="Auth strategy is not selected.",
                        )
                    ],
                )
            ]
        )

        render_result = DraftScenarioRenderer().render(plan)

        self.assertEqual(
            render_result.draft_set.drafts[0].metadata["case_gaps"][0]["category"],
            "auth_strategy",
        )
        self.assertIn(
            "Typed gap [auth_strategy]: Auth strategy is not selected.",
            render_result.draft_set.drafts[0].markdown,
        )
        self.assertIn(
            "- Typed unresolved intent count: 1",
            render_result.draft_set.drafts[0].markdown,
        )

    def test_renderer_renders_java_spring_list_case_from_route_hints(self) -> None:
        render_result = DraftScenarioRenderer().render(
            _plan([_route_supported_case("List sessions", "/api/sessions", "GET")])
        )

        self.assertEqual(len(render_result.draft_set.drafts), 1)
        self.assertIn("Path: /api/sessions", render_result.draft_set.drafts[0].markdown)
        self.assertIn("Route shape: collection.", render_result.draft_set.drafts[0].markdown)

    def test_renderer_renders_java_spring_get_by_id_case_from_route_hints(self) -> None:
        render_result = DraftScenarioRenderer().render(
            _plan([_route_supported_case("Get session by id", "/api/sessions/{id}", "GET")])
        )

        self.assertEqual(len(render_result.draft_set.drafts), 1)
        self.assertIn("Path: /api/sessions/{id}", render_result.draft_set.drafts[0].markdown)
        self.assertIn("Route shape: item.", render_result.draft_set.drafts[0].markdown)

    def test_renderer_renders_java_spring_revoke_one_case_from_route_hints(self) -> None:
        render_result = DraftScenarioRenderer().render(
            _plan([_route_supported_case("Revoke one session", "/api/sessions/{id}/revoke", "POST")])
        )

        self.assertEqual(len(render_result.draft_set.drafts), 1)
        self.assertIn("Path: /api/sessions/{id}/revoke", render_result.draft_set.drafts[0].markdown)

    def test_renderer_renders_java_spring_revoke_all_case_from_route_hints(self) -> None:
        render_result = DraftScenarioRenderer().render(
            _plan([_route_supported_case("Revoke all sessions", "/api/sessions/revoke-all", "POST")])
        )

        self.assertEqual(len(render_result.draft_set.drafts), 1)
        self.assertIn("Path: /api/sessions/revoke-all", render_result.draft_set.drafts[0].markdown)

    def test_renderer_allows_evidence_supported_route_hints(self) -> None:
        render_result = DraftScenarioRenderer().render(
            _plan([_route_supported_case("List sessions", "/api/sessions", "GET", readiness="evidence_supported")])
        )

        self.assertEqual(len(render_result.draft_set.drafts), 1)

    def test_renderer_defers_ambiguous_route_hints(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Session API",
                    objective="Verify session routes.",
                    metadata={
                        "readiness": "route_resolved",
                        "route_hints": [
                            _route_hint("/api/sessions", "GET"),
                            _route_hint("/api/sessions", "POST"),
                        ],
                    },
                )
            ]
        )

        render_result = DraftScenarioRenderer().render(plan)

        self.assertEqual(render_result.draft_set.drafts, [])
        self.assertEqual(render_result.unsupported_checks[0].reason_code, "ambiguous_route_mapping")

    def test_renderer_does_not_render_route_hint_when_not_ready(self) -> None:
        render_result = DraftScenarioRenderer().render(
            _plan([_route_supported_case("Get session by id", "/api/sessions/{id}", "GET", readiness="prose_only")])
        )

        self.assertEqual(render_result.draft_set.drafts, [])
        self.assertEqual(render_result.unsupported_checks[0].reason_code, "route_not_ready_for_rendering")

    def test_renderer_allows_planned_route_even_when_readiness_is_not_set(self) -> None:
        render_result = DraftScenarioRenderer().render(
            _plan(
                [
                    PlannedTestCase(
                        case_id="tc-001",
                        title="Authenticate session",
                        objective="Verify authenticate session.",
                        planned_route=PlannedRouteIntent(
                            http_method="POST",
                            endpoint_path="/api/sessions/authenticate",
                            path_kind="collection",
                        ),
                    )
                ]
            )
        )

        self.assertEqual(len(render_result.draft_set.drafts), 1)

    def test_preview_service_persists_route_hint_based_drafts_and_parse_results(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _context(root)
            context.run_state_dir.mkdir(parents=True)
            context.artifact_dir.mkdir(parents=True)
            store = FileGenerationArtifactStore()

            render_result, artifact_paths = ScenarioDraftPreviewService().render_and_persist(
                _plan([_route_supported_case("Get session by id", "/api/sessions/{id}", "GET")]),
                context,
                store,
            )

            self.assertEqual(len(render_result.validation_results), 1)
            self.assertTrue(render_result.validation_results[0].parse_valid)
            self.assertTrue((context.artifact_dir / "scenario-drafts").exists())
            self.assertEqual(artifact_paths["scenario_render_result"].name, "scenario-render-result.json")

    def test_preview_service_persists_drafts_and_parse_results(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _context(root)
            context.run_state_dir.mkdir(parents=True)
            context.artifact_dir.mkdir(parents=True)
            store = FileGenerationArtifactStore()

            render_result, artifact_paths = ScenarioDraftPreviewService().render_and_persist(
                _plan([_supported_case()]),
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
            self.assertTrue((context.artifact_dir / "unsupported-checks.json").exists())
            self.assertEqual(artifact_paths["scenario_render_result"].name, "scenario-render-result.json")
            self.assertEqual(result_payload.validation_results[0].parse_valid, True)


def _plan(cases: list[PlannedTestCase]) -> NormalizedTestPlan:
    return NormalizedTestPlan(
        plan_id="plan-users",
        source_id="users",
        project="code/demo",
        title="Users API",
        test_cases=cases,
    )


def _supported_case() -> PlannedTestCase:
    return PlannedTestCase(
        case_id="tc-001",
        title="Create user",
        objective="Verify create user.",
        expected_results=["HTTP 201 or documented successful creation response is returned."],
        metadata={
            "readiness": "evidence_supported",
            "evidence_hints": [
                {
                    "case_id": "tc-001",
                    "fact_id": "fact-create-user",
                    "relation": "evidence_supports_case",
                    "confidence": "explicit",
                    "summary": "POST /users handled by create_user",
                    "applied_fields": {
                        "endpoint_path": "/users",
                        "http_method": "POST",
                        "handler_name": "create_user",
                    },
                }
            ]
        },
    )


def _route_supported_case(
    title: str,
    endpoint_path: str,
    method: str,
    *,
    readiness: str = "route_resolved",
) -> PlannedTestCase:
    return PlannedTestCase(
        case_id="tc-001",
        title=title,
        objective=f"Verify {title.lower()}.",
        metadata={
            "readiness": readiness,
            "route_hints": [
                _route_hint(endpoint_path, method),
            ],
        },
    )


def _route_hint(endpoint_path: str, method: str) -> dict[str, object]:
    return {
        "fact_id": f"fact-{method.lower()}-{endpoint_path.strip('/').replace('/', '-') or 'root'}",
        "confidence": "explicit",
        "match_reasons": ["route_resolved_from_code_facts"],
        "endpoint_path": endpoint_path,
        "http_method": method,
        "handler_name": "handlerMethod",
        "controller_name": "SessionController",
        "framework_hint": "spring_mapping",
    }


def _context(root: Path) -> GenerationRunContext:
    return GenerationRunContext(
        run_id="gen-1",
        workspace_root=root,
        source_id="src-1",
        project="code/demo",
        runs_root_dir=root / GENERATION_RUNS_DIRNAME,
        run_state_dir=root / GENERATION_RUNS_DIRNAME / "gen-1",
        artifacts_root_dir=root / GENERATION_ARTIFACTS_DIRNAME,
        artifact_dir=root / GENERATION_ARTIFACTS_DIRNAME / "src-1-gen-1",
        started_at="2026-04-23T08:00:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
