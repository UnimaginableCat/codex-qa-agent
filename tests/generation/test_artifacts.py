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
    NormalizedTestPlan,
    TraceabilityLink,
    TraceabilityMap,
)
from tools.generation.persistence.artifacts import (
    CONTEXT_FILENAME,
    DIAGNOSTICS_FILENAME,
    FileGenerationArtifactStore,
    GENERATION_ARTIFACTS_DIRNAME,
    GENERATION_RUNS_DIRNAME,
    MANIFEST_FILENAME,
    NORMALIZED_PLAN_FILENAME,
    SOURCE_INPUT_FILENAME,
    SUMMARY_FILENAME,
    TRACEABILITY_MAP_FILENAME,
    GenerationArtifactPolicyError,
    ensure_generation_artifact_output_path,
)


class GenerationArtifactStoreTests(unittest.TestCase):
    def test_store_writes_generation_bundle_and_run_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _context(root)
            context.run_state_dir.mkdir(parents=True)
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
            store.write_summary(context, {"status": "PASS"})

            manifest = json.loads((context.artifact_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))

            self.assertTrue((context.run_state_dir / CONTEXT_FILENAME).exists())
            self.assertTrue((context.run_state_dir / SUMMARY_FILENAME).exists())
            self.assertTrue((context.artifact_dir / SOURCE_INPUT_FILENAME).exists())
            self.assertTrue((context.artifact_dir / NORMALIZED_PLAN_FILENAME).exists())
            self.assertTrue((context.artifact_dir / TRACEABILITY_MAP_FILENAME).exists())
            self.assertTrue((context.artifact_dir / DIAGNOSTICS_FILENAME).exists())
            self.assertEqual(manifest["layout_version"], 1)
            self.assertEqual(
                manifest["bundle"]["source_input_path"],
                str(context.artifact_dir / SOURCE_INPUT_FILENAME),
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
        runs_root_dir=root / GENERATION_RUNS_DIRNAME,
        run_state_dir=root / GENERATION_RUNS_DIRNAME / "gen-1",
        artifacts_root_dir=root / GENERATION_ARTIFACTS_DIRNAME,
        artifact_dir=root / GENERATION_ARTIFACTS_DIRNAME / "src-1-gen-1",
        started_at="2026-04-23T08:00:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()

