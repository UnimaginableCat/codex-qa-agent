from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation.domain.models import (
    AgentPlannedTestCaseInput,
    AgentTestPlanInput,
    DiagnosticSeverity,
    GenerationDiagnostic,
    GenerationRunContext,
    GenerationSourceInput,
    NormalizedProseSource,
    NormalizedTestPlan,
    PlannedTestCase,
    ProseTestCaseDraft,
    SourceInputFormat,
    TraceabilityLink,
    TraceabilityMap,
)


class GenerationContractTests(unittest.TestCase):
    def test_agent_test_plan_input_round_trips_through_json_payload(self) -> None:
        agent_plan = AgentTestPlanInput(
            source_id="sessions-agent-plan",
            project="code/demo",
            title="Internal sessions",
            goal="Cover session lifecycle.",
            planned_test_cases=[
                AgentPlannedTestCaseInput(
                    title="Authenticate session",
                    objective="Verify session authentication.",
                    kind="api",
                    case_id="auth-session",
                    preconditions=["Operator provides valid credentials."],
                    actions=["Call authenticate endpoint."],
                    expected_outcomes=["Session token is returned."],
                    priority="high",
                    tags=["session"],
                    unresolved_items=["Auth fixture name is not selected."],
                    assumptions=["Controller route evidence may resolve endpoint later."],
                    metadata={"owner": "agent"},
                )
            ],
            assumptions=["Agent decomposition is operator-reviewed."],
            open_questions=["Which environment should be used?"],
            evidence_scope={"paths": ["src/main/java/demo/UserController.java"]},
        )

        restored = AgentTestPlanInput.from_dict(json.loads(json.dumps(agent_plan.to_dict())))

        self.assertEqual(restored.source_id, "sessions-agent-plan")
        self.assertEqual(restored.planned_test_cases[0].case_id, "auth-session")
        self.assertEqual(restored.planned_test_cases[0].actions, ["Call authenticate endpoint."])
        self.assertEqual(restored.evidence_scope["paths"], ["src/main/java/demo/UserController.java"])

    def test_source_input_round_trips_through_json_payload(self) -> None:
        source = GenerationSourceInput(
            source_id="price-list-plan",
            project="code/beck-end-1.0",
            name="Price List Plan",
            content="# Test plan",
            source_path=Path("scenarios/source.md"),
            metadata={"owner": "qa"},
        )

        payload = json.loads(json.dumps(source.to_dict()))
        restored = GenerationSourceInput.from_dict(payload)

        self.assertEqual(restored.source_id, source.source_id)
        self.assertEqual(restored.project, source.project)
        self.assertEqual(restored.input_format, SourceInputFormat.PROSE)
        self.assertEqual(restored.source_path, Path("scenarios/source.md"))
        self.assertEqual(restored.metadata["owner"], "qa")

    def test_normalized_plan_preserves_planned_cases(self) -> None:
        plan = NormalizedTestPlan(
            plan_id="plan-1",
            source_id="src-1",
            project="code/demo",
            title="Demo",
            test_cases=[
                PlannedTestCase(
                    case_id="tc-001",
                    title="Create entity",
                    objective="Verify entity creation",
                    source_refs=["src-1"],
                    steps=["Send request"],
                    expected_results=["Entity exists"],
                    assumptions=["API is available"],
                    open_questions=["Which auth mode is required?"],
                )
            ],
        )

        restored = NormalizedTestPlan.from_dict(json.loads(json.dumps(plan.to_dict())))

        self.assertEqual(restored.test_cases[0].case_id, "tc-001")
        self.assertEqual(restored.test_cases[0].source_refs, ["src-1"])
        self.assertEqual(restored.test_cases[0].expected_results, ["Entity exists"])
        self.assertEqual(restored.test_cases[0].assumptions, ["API is available"])
        self.assertEqual(restored.test_cases[0].open_questions, ["Which auth mode is required?"])

    def test_normalized_prose_source_preserves_drafts(self) -> None:
        normalized = NormalizedProseSource(
            source_id="src-1",
            project="code/demo",
            title="Users",
            normalized_text="Verify user creation",
            test_case_drafts=[
                ProseTestCaseDraft(
                    draft_id="tc-001",
                    title="User creation",
                    objective="Verify user creation.",
                    source_ref="src-1#case-001",
                    steps=["Exercise behavior described as: user creation"],
                    expected_results=["User is created"],
                    assumptions=["Expected result provided by operator"],
                    open_questions=["Which endpoint should be used?"],
                )
            ],
        )

        restored = NormalizedProseSource.from_dict(json.loads(json.dumps(normalized.to_dict())))

        self.assertEqual(restored.test_case_drafts[0].draft_id, "tc-001")
        self.assertEqual(restored.test_case_drafts[0].open_questions, ["Which endpoint should be used?"])

    def test_diagnostics_and_traceability_round_trip(self) -> None:
        diagnostic = GenerationDiagnostic(
            code="source_empty",
            message="No content",
            severity=DiagnosticSeverity.WARNING,
            source_ref="src-1",
        )
        traceability = TraceabilityMap(
            source_id="src-1",
            links=[
                TraceabilityLink(
                    source_ref="src-1",
                    target_ref="plan-src-1",
                    relation="source_to_plan",
                )
            ],
        )

        restored_diagnostic = GenerationDiagnostic.from_dict(
            json.loads(json.dumps(diagnostic.to_dict()))
        )
        restored_traceability = TraceabilityMap.from_dict(
            json.loads(json.dumps(traceability.to_dict()))
        )

        self.assertEqual(restored_diagnostic.severity, DiagnosticSeverity.WARNING)
        self.assertEqual(restored_traceability.links[0].relation, "source_to_plan")

    def test_run_context_round_trips_paths(self) -> None:
        context = GenerationRunContext(
            run_id="gen-1",
            workspace_root=Path("D:/workspace"),
            source_id="src-1",
            project="code/demo",
            runs_root_dir=Path("D:/workspace/.codex-qa/generation/runs"),
            run_state_dir=Path("D:/workspace/.codex-qa/generation/runs/gen-1"),
            artifacts_root_dir=Path("D:/workspace/artifacts/agent/generation"),
            artifact_dir=Path("D:/workspace/artifacts/agent/generation/src-1-gen-1"),
            started_at="2026-04-23T08:00:00+00:00",
        )

        restored = GenerationRunContext.from_dict(json.loads(json.dumps(context.to_dict())))

        self.assertEqual(restored.run_state_dir, context.run_state_dir)
        self.assertEqual(restored.artifact_dir, context.artifact_dir)


if __name__ == "__main__":
    unittest.main()
