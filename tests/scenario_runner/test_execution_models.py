from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.scenario_runner.domain.execution import (
    CompletionDisposition,
    ExecutionEvent,
    ExecutionIssue,
    ExecutionIssueKind,
    ExecutionOutcome,
    ExecutionPhase,
    RunTermination,
    RunTerminationKind,
    ScenarioRunLifecycleState,
    ScenarioRunState,
    StepExecutionLifecycleState,
    StepExecutionState,
    StepReference,
    StepTermination,
    StepTerminationKind,
    TerminationReason,
    TerminationReasonSource,
)
from tools.scenario_runner.domain.models import (
    ApiStepDefinition,
    ScenarioDefinition,
    ScenarioStep,
    ScenarioStepType,
    StepExecutionResult,
)
from tools.scenario_runner.orchestration.preflight import PreflightCheckResult, PreflightResult
from tools.scenario_runner.orchestration.services import ScenarioRunnerService
from tools.scenario_runner.runtime.executors import StepExecutionOutcome


class ExecutionModelTests(unittest.TestCase):
    def test_issue_serialization_and_tooling_message_preserve_phase_and_step(self) -> None:
        issue = ExecutionIssue(
            code="step_execution_failed",
            message="network timeout",
            phase=ExecutionPhase.STEP_EXECUTION,
            issue_type=ExecutionIssueKind.EXECUTION,
            outcome=StepStatus.BLOCKED,
            step=StepReference(step_id="step-1", step_number=1, step_type=ScenarioStepType.API),
            details={"retryable": True},
        )

        self.assertEqual(issue.to_dict()["phase"], ExecutionPhase.STEP_EXECUTION.value)
        self.assertEqual(issue.to_dict()["step"]["step_id"], "step-1")
        self.assertIn("BLOCKED", issue.to_tooling_message())
        self.assertIn("step_execution_failed", issue.to_tooling_message())

    def test_execution_event_includes_lifecycle_and_outcome_payload(self) -> None:
        run_state = ScenarioRunState(
            run_id="run-1",
            scenario_name="Demo",
            scenario_path=Path("scenario.md"),
            lifecycle_state=ScenarioRunLifecycleState.STEP_RUNNING,
            termination=RunTermination(
                kind=RunTerminationKind.COMPLETED,
                reason=TerminationReason(
                    code="run_completed",
                    message="done",
                    source=TerminationReasonSource.EXECUTION,
                    phase=ExecutionPhase.STEP_EXECUTION,
                ),
                completion_disposition=CompletionDisposition.COMPLETE,
                outcome_status=StepStatus.PASS,
                completed_step_count=1,
                total_step_count=1,
            ),
        )
        step_state = StepExecutionState(
            step=StepReference(step_id="step-1", step_number=1, step_type=ScenarioStepType.API),
            lifecycle_state=StepExecutionLifecycleState.FINISHED,
            outcome=ExecutionOutcome.from_status(
                StepStatus.PASS,
                "ok",
                phase=ExecutionPhase.STEP_EXECUTION,
            ),
            termination=StepTermination(
                kind=StepTerminationKind.COMPLETED,
                reason=TerminationReason(
                    code="step_completed",
                    message="ok",
                    source=TerminationReasonSource.EXECUTION,
                    phase=ExecutionPhase.STEP_EXECUTION,
                ),
                outcome_status=StepStatus.PASS,
            ),
        )

        event = ExecutionEvent.create(
            event_type="step_completed",
            run_state=run_state,
            phase=ExecutionPhase.STEP_EXECUTION,
            step_state=step_state,
            outcome=step_state.outcome,
            payload={"captures": ["id"]},
        )
        payload = event.to_dict()

        self.assertEqual(payload["run_lifecycle_state"], ScenarioRunLifecycleState.STEP_RUNNING.value)
        self.assertEqual(payload["step_lifecycle_state"], StepExecutionLifecycleState.FINISHED.value)
        self.assertEqual(payload["outcome"]["status"], StepStatus.PASS.value)
        self.assertEqual(payload["run_termination"]["kind"], RunTerminationKind.COMPLETED.value)
        self.assertEqual(payload["step_termination"]["kind"], StepTerminationKind.COMPLETED.value)
        self.assertEqual(payload["payload"]["captures"], ["id"])

    def test_step_finish_derives_termination_without_changing_legacy_outcome(self) -> None:
        step_state = StepExecutionState(
            step=StepReference(step_id="step-1", step_number=1, step_type=ScenarioStepType.API)
        ).finish(
            ExecutionOutcome.from_status(
                StepStatus.BLOCKED,
                "missing variable",
                phase=ExecutionPhase.STEP_VARIABLE_RESOLUTION,
            )
        )

        self.assertEqual(step_state.outcome.status, StepStatus.BLOCKED)
        self.assertEqual(step_state.termination.kind, StepTerminationKind.BLOCKED)
        self.assertEqual(step_state.termination.reason.source, TerminationReasonSource.EXECUTION)
        self.assertEqual(step_state.to_dict()["termination"]["outcome_status"], StepStatus.BLOCKED.value)

    def test_service_journal_uses_typed_event_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_path = root / "scenario.md"
            scenario_path.write_text("# Scenario: Demo\n", encoding="utf-8")
            (root / "env").mkdir()
            (root / "env" / "demo.env").write_text("API_BASE_URL=http://localhost\n", encoding="utf-8")
            service = ScenarioRunnerService(
                step_executor_factory=_PassingExecutorFactory(),
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(
                ScenarioDefinition(
                    scenario_path=scenario_path,
                    scenario_slug="demo",
                    scenario_name="Demo",
                    project="code/demo-project",
                    environment="env/demo.env",
                    steps=[
                        ScenarioStep(
                            step_id="step-1",
                            step_number=1,
                            title="Step 1",
                            step_type=ScenarioStepType.API,
                            api=ApiStepDefinition(method="GET", path="/demo"),
                        )
                    ],
                ),
                workspace_root=root,
            )

            journal_lines = (summary.run_state_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertTrue(journal_lines)
        first_event = json.loads(journal_lines[0])
        self.assertEqual(first_event["event_type"], "run_initialized")
        self.assertEqual(first_event["phase"], ExecutionPhase.RUN_INITIALIZATION.value)
        self.assertEqual(first_event["run_lifecycle_state"], ScenarioRunLifecycleState.INITIALIZING.value)
        self.assertIn("payload", first_event)


class _PassingExecutorFactory:
    def create(self, step: ScenarioStep, workspace_root: Path) -> "_PassingExecutorFactory":
        return self

    def execute(self, run_context, scenario_definition, step: ScenarioStep) -> StepExecutionOutcome:
        return StepExecutionOutcome(
            step_result=StepExecutionResult(
                step_id=step.step_id,
                step_number=step.step_number,
                step_type=step.step_type,
                status=StepStatus.PASS,
                message="ok",
            )
        )


class _PassingPreflightChecker:
    @staticmethod
    def run(scenario_definition, workspace_root):
        return PreflightResult(
            checks=[
                PreflightCheckResult(
                    name="test_preflight",
                    status=StepStatus.PASS,
                    message="Test preflight passed.",
                )
            ]
        )


if __name__ == "__main__":
    unittest.main()
