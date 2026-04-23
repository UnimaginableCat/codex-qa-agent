from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation.domain.models import GenerationRunContext, NormalizedTestPlan, PlannedTestCase
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
