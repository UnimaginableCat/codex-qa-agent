from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.generation.domain.models import DiagnosticSeverity, GenerationSourceInput
from tools.generation.orchestration.services import GenerationPipelineService


class GenerationOrchestrationTests(unittest.TestCase):
    def test_minimal_generation_flow_persists_artifacts_and_returns_result(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = GenerationPipelineService().run(
                GenerationSourceInput(
                    source_id="Checkout Flow",
                    project="code/demo",
                    name="Checkout Flow",
                    content="Verify that a customer can complete checkout.",
                ),
                workspace_root=root,
            )

            source_payload = json.loads(
                result.artifact_paths["source_input"].read_text(encoding="utf-8")
            )
            plan_payload = json.loads(
                result.artifact_paths["normalized_plan"].read_text(encoding="utf-8")
            )
            traceability_payload = json.loads(
                result.artifact_paths["traceability_map"].read_text(encoding="utf-8")
            )
            diagnostics_payload = json.loads(
                result.artifact_paths["diagnostics"].read_text(encoding="utf-8")
            )

            self.assertEqual(result.final_status, StepStatus.PASS)
            self.assertEqual(result.normalized_plan.test_cases[0].case_id, "tc-001")
            self.assertEqual(source_payload["source_id"], "Checkout Flow")
            self.assertEqual(plan_payload["source_id"], "Checkout Flow")
            self.assertEqual(traceability_payload["links"][0]["relation"], "source_to_plan")
            self.assertEqual(diagnostics_payload["diagnostics"][0]["code"], "source_input_captured")
            self.assertTrue(str(result.run_context.artifact_dir).endswith(result.run_context.run_id))

    def test_empty_source_input_emits_warning_but_keeps_foundation_run_terminal(self) -> None:
        with TemporaryDirectory() as tmp:
            result = GenerationPipelineService().run(
                GenerationSourceInput(
                    source_id="empty",
                    project="code/demo",
                ),
                workspace_root=Path(tmp),
            )

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertEqual(result.diagnostics[-1].severity, DiagnosticSeverity.WARNING)
        self.assertEqual(result.diagnostics[-1].code, "source_content_empty")
        self.assertEqual(result.normalized_plan.test_cases, [])
        self.assertEqual(len(result.traceability_map.links), 1)


if __name__ == "__main__":
    unittest.main()

