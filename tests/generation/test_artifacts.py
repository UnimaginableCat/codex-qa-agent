from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation.domain.models import (
    DiagnosticSeverity,
    GenerationDiagnostic,
    GenerationRunContext,
    GenerationSourceInput,
    NormalizedProseSource,
    NormalizedTestPlan,
    TraceabilityLink,
    TraceabilityMap,
)
from tools.generation.persistence.artifacts import (
    APPLIED_EVIDENCE_FILENAME,
    CONTEXT_FILENAME,
    DEFERRED_ITEMS_FILENAME,
    DIAGNOSTICS_FILENAME,
    ENRICHED_PLAN_FILENAME,
    ENRICHMENT_RESULT_FILENAME,
    EVIDENCE_BUNDLE_FILENAME,
    FileGenerationArtifactStore,
    GENERATION_ARTIFACTS_DIRNAME,
    MANIFEST_FILENAME,
    NORMALIZED_SOURCE_FILENAME,
    NORMALIZED_PLAN_FILENAME,
    SCENARIO_DRAFTS_DIRNAME,
    SCENARIO_PARSE_RESULTS_FILENAME,
    SCENARIO_RENDER_RESULT_FILENAME,
    SOURCE_INPUT_FILENAME,
    SUMMARY_FILENAME,
    TRACEABILITY_MAP_FILENAME,
    UNAPPLIED_EVIDENCE_FILENAME,
    UNSUPPORTED_CHECKS_FILENAME,
    GenerationArtifactPolicyError,
    ensure_generation_artifact_output_path,
)
from tools.generation.enrichment.models import AppliedEvidenceLink, EnrichedTestPlanResult
from tools.generation.evidence.models import (
    EvidenceConfidence,
    EvidenceProvenance,
    GenerationEvidenceBundle,
    GenerationEvidenceFact,
)
from tools.generation.rendering.models import ScenarioDraft, ScenarioDraftSet, ScenarioRenderResult


class GenerationArtifactStoreTests(unittest.TestCase):
    def test_store_writes_generation_bundle_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _context(root)
            context.artifact_dir.mkdir(parents=True)
            store = FileGenerationArtifactStore()

            store.write_context(context)
            store.write_source_input(
                context,
                GenerationSourceInput(
                    source_id="src-1",
                    project="code/demo",
                    content="Verify demo flow",
                ),
            )
            store.write_normalized_plan(
                context,
                NormalizedTestPlan(
                    plan_id="plan-src-1",
                    source_id="src-1",
                    project="code/demo",
                    title="Demo",
                ),
            )
            store.write_normalized_source(
                context,
                NormalizedProseSource(
                    source_id="src-1",
                    project="code/demo",
                    title="Demo",
                    normalized_text="Verify demo flow",
                ),
            )
            store.write_traceability_map(
                context,
                TraceabilityMap(
                    source_id="src-1",
                    links=[
                        TraceabilityLink(
                            source_ref="src-1",
                            target_ref="plan-src-1",
                            relation="source_to_plan",
                        )
                    ],
                ),
            )
            store.write_diagnostics(
                context,
                [
                    GenerationDiagnostic(
                        code="source_input_captured",
                        message="ok",
                        severity=DiagnosticSeverity.INFO,
                    )
                ],
            )
            store.write_evidence_bundle(
                context,
                GenerationEvidenceBundle(
                    bundle_id="evidence-api",
                    target_project="code/demo",
                    scope="api",
                    facts=[
                        GenerationEvidenceFact(
                            fact_id="api-users-get",
                            fact_type="api_endpoint",
                            summary="GET /users",
                            payload={"endpoint_path": "/users", "http_method": "GET"},
                            provenance=EvidenceProvenance(
                                source_kind="python_ast",
                                file_path=Path("app/api.py"),
                                symbol="list_users",
                                line_range=(1, 2),
                            ),
                            confidence=EvidenceConfidence.EXPLICIT,
                        )
                    ],
                ),
            )
            enriched_plan = NormalizedTestPlan(
                plan_id="plan-src-1",
                source_id="src-1",
                project="code/demo",
                title="Demo",
                metadata={"enrichment": {"stage": "evidence-to-plan-v1"}},
            )
            store.write_enriched_plan(context, enriched_plan)
            store.write_enrichment_result(
                context,
                EnrichedTestPlanResult(
                    enriched_plan=enriched_plan,
                    applied_evidence=[
                        AppliedEvidenceLink(
                            case_id="tc-001",
                            fact_id="api-users-get",
                            relation="evidence_supports_case",
                            confidence=EvidenceConfidence.EXPLICIT,
                            summary="GET /users",
                        )
                    ],
                ),
            )
            store.write_scenario_drafts(
                context,
                ScenarioDraftSet(
                    plan_id="plan-src-1",
                    drafts=[
                        ScenarioDraft(
                            draft_id="draft-tc-001",
                            case_id="tc-001",
                            title="Demo draft",
                            markdown="# Scenario: Demo\n\n## Project\ncode/demo\n\n## Environment\nenv/demo.env\n",
                            relative_path=Path("scenario-drafts/demo.md"),
                        )
                    ],
                ),
            )
            store.write_scenario_render_result(
                context,
                ScenarioRenderResult(
                    draft_set=ScenarioDraftSet(plan_id="plan-src-1"),
                ),
            )
            store.write_summary(context, {"status": "PASS"})

            manifest = json.loads((context.artifact_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))

            self.assertTrue((context.artifact_dir / CONTEXT_FILENAME).exists())
            self.assertTrue((context.artifact_dir / SUMMARY_FILENAME).exists())
            self.assertTrue((context.artifact_dir / SOURCE_INPUT_FILENAME).exists())
            self.assertTrue((context.artifact_dir / NORMALIZED_SOURCE_FILENAME).exists())
            self.assertTrue((context.artifact_dir / NORMALIZED_PLAN_FILENAME).exists())
            self.assertTrue((context.artifact_dir / TRACEABILITY_MAP_FILENAME).exists())
            self.assertTrue((context.artifact_dir / DIAGNOSTICS_FILENAME).exists())
            self.assertTrue((context.artifact_dir / EVIDENCE_BUNDLE_FILENAME).exists())
            self.assertTrue((context.artifact_dir / ENRICHED_PLAN_FILENAME).exists())
            self.assertTrue((context.artifact_dir / ENRICHMENT_RESULT_FILENAME).exists())
            self.assertTrue((context.artifact_dir / APPLIED_EVIDENCE_FILENAME).exists())
            self.assertTrue((context.artifact_dir / UNAPPLIED_EVIDENCE_FILENAME).exists())
            self.assertTrue((context.artifact_dir / SCENARIO_DRAFTS_DIRNAME / "demo.md").exists())
            self.assertTrue((context.artifact_dir / SCENARIO_RENDER_RESULT_FILENAME).exists())
            self.assertTrue((context.artifact_dir / SCENARIO_PARSE_RESULTS_FILENAME).exists())
            self.assertTrue((context.artifact_dir / UNSUPPORTED_CHECKS_FILENAME).exists())
            self.assertTrue((context.artifact_dir / DEFERRED_ITEMS_FILENAME).exists())
            self.assertEqual(manifest["layout_version"], 6)
            self.assertEqual(
                manifest["bundle"]["source_input_path"],
                str(context.artifact_dir / SOURCE_INPUT_FILENAME),
            )
            self.assertEqual(
                manifest["bundle"]["normalized_source_path"],
                str(context.artifact_dir / NORMALIZED_SOURCE_FILENAME),
            )
            self.assertEqual(
                manifest["bundle"]["evidence_bundle_path"],
                str(context.artifact_dir / EVIDENCE_BUNDLE_FILENAME),
            )
            self.assertEqual(
                manifest["bundle"]["enrichment_result_path"],
                str(context.artifact_dir / ENRICHMENT_RESULT_FILENAME),
            )
            self.assertEqual(
                manifest["bundle"]["scenario_render_result_path"],
                str(context.artifact_dir / SCENARIO_RENDER_RESULT_FILENAME),
            )

    def test_artifact_policy_rejects_paths_outside_generation_artifact_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_root = root / GENERATION_ARTIFACTS_DIRNAME
            artifact_root.mkdir(parents=True)

            with self.assertRaises(GenerationArtifactPolicyError):
                ensure_generation_artifact_output_path(root / "outside.json", artifact_root)


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
