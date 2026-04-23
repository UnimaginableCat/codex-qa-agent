from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.generation.application.models import GenerateTestPlanOptions, GenerateTestPlanRequest
from tools.generation.application.use_cases import GenerateTestPlanUseCase
from tools.generation.domain.models import GenerationSourceInput, NormalizedTestPlan, SourceInputFormat
from tools.generation.evidence.models import CodeFactsScope


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
        self.assertEqual(plan_payload["metadata"]["generation_phase"], "prose_plan_generation")

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


if __name__ == "__main__":
    unittest.main()
