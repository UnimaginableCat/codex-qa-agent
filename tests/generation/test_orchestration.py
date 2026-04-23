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
                    content="Нужен тест-план на internal tenants API: create, get, list, patch, invalid status transition, missing entity",
                ),
                workspace_root=root,
            )

            source_payload = json.loads(
                result.artifact_paths["source_input"].read_text(encoding="utf-8")
            )
            normalized_source_payload = json.loads(
                result.artifact_paths["normalized_source"].read_text(encoding="utf-8")
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
        self.assertGreaterEqual(len(result.normalized_plan.test_cases), 6)
        self.assertEqual(result.normalized_plan.test_cases[0].case_id, "tc-001")
        self.assertEqual(result.normalized_plan.test_cases[0].title, "Create")
        self.assertTrue(result.normalized_plan.test_cases[0].steps)
        self.assertTrue(result.normalized_plan.test_cases[0].expected_results)
        self.assertTrue(result.normalized_plan.test_cases[-1].open_questions)
        self.assertEqual(source_payload["source_id"], "Checkout Flow")
        self.assertEqual(normalized_source_payload["metadata"]["normalizer"], "prose-rule-v1")
        self.assertEqual(plan_payload["source_id"], "Checkout Flow")
        self.assertEqual(traceability_payload["links"][0]["relation"], "source_to_plan")
        self.assertEqual(diagnostics_payload["diagnostics"][0]["code"], "source_input_captured")
        self.assertTrue(str(result.run_context.artifact_dir).endswith(result.run_context.run_id))

    def test_empty_source_input_blocks_plan_generation(self) -> None:
        with TemporaryDirectory() as tmp:
            result = GenerationPipelineService().run(
                GenerationSourceInput(
                    source_id="empty",
                    project="code/demo",
                ),
                workspace_root=Path(tmp),
            )

        self.assertEqual(result.final_status, StepStatus.BLOCKED)
        self.assertEqual(result.diagnostics[-1].severity, DiagnosticSeverity.ERROR)
        self.assertEqual(result.diagnostics[-1].code, "source_content_empty")
        self.assertEqual(result.normalized_plan.test_cases, [])
        self.assertEqual(len(result.traceability_map.links), 1)

    def test_file_source_input_is_read_and_normalized(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "request.md"
            source_path.write_text(
                "Проверить создание пользователя, валидацию email, получение пользователя по id и ошибку при несуществующем id",
                encoding="utf-8",
            )

            result = GenerationPipelineService().run(
                GenerationSourceInput(
                    source_id="users-flow",
                    project="code/demo",
                    source_path=source_path,
                ),
                workspace_root=root,
            )
            source_artifact = result.artifact_paths["source_input"].read_text(encoding="utf-8")

        self.assertEqual(result.final_status, StepStatus.PASS)
        self.assertEqual(len(result.normalized_plan.test_cases), 4)
        self.assertEqual(result.normalized_plan.test_cases[0].title, "Создание пользователя")
        self.assertIn("source_path", source_artifact)


if __name__ == "__main__":
    unittest.main()
