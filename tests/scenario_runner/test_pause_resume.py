from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.common.errors import ValidationError
from tools.scenario_runner.domain.manual import OperatorActionSelection
from tools.scenario_runner.domain.execution import RunTerminationKind, StepTerminationKind, TerminationReasonSource
from tools.scenario_runner.domain.models import (
    ApiStepDefinition,
    ScenarioDefinition,
    ScenarioStep,
    ScenarioStepType,
    StepExecutionResult,
)
from tools.scenario_runner.domain.pause import RunContinuationState
from tools.scenario_runner.orchestration.preflight import PreflightCheckResult, PreflightResult
from tools.scenario_runner.orchestration.services import ScenarioRunnerService
from tools.scenario_runner.runtime.executors import StepExecutionOutcome


class ScenarioPauseResumeTests(unittest.TestCase):
    def test_pause_state_is_created_persisted_and_resume_continues_from_meaningful_step(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root)
            executor = _SequencedExecutorFactory(
                [
                    StepExecutionOutcome(
                        step_result=StepExecutionResult(
                            step_id="step-1",
                            step_number=1,
                            step_type=ScenarioStepType.API,
                            status=StepStatus.FAIL,
                            message="create failed",
                        )
                    ),
                    StepExecutionOutcome(
                        step_result=StepExecutionResult(
                            step_id="step-1",
                            step_number=1,
                            step_type=ScenarioStepType.API,
                            status=StepStatus.PASS,
                            message="created",
                            details={"capture_keys": ["price_list_id"]},
                        ),
                        captured_values={"price_list_id": 123},
                    ),
                    StepExecutionOutcome(
                        step_result=StepExecutionResult(
                            step_id="step-2",
                            step_number=2,
                            step_type=ScenarioStepType.API,
                            status=StepStatus.PASS,
                            message="read ok",
                        )
                    ),
                ]
            )
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )
            scenario = self._scenario(root)

            paused_summary = service.run(scenario, workspace_root=root)
            pause_payload = json.loads(paused_summary.pause_state_path.read_text(encoding="utf-8"))
            report_content = paused_summary.report_path.read_text(encoding="utf-8")

            resumed_summary = service.resume(paused_summary.pause_state_path)
            journal_lines = (
                resumed_summary.run_state_dir / "journal.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            resumed_report = resumed_summary.report_path.read_text(encoding="utf-8")

            self.assertEqual(paused_summary.final_status, StepStatus.BLOCKED)
            self.assertEqual(paused_summary.continuation_state, RunContinuationState.PAUSED)
            self.assertEqual(paused_summary.details["run_termination"]["kind"], RunTerminationKind.PAUSED.value)
            self.assertFalse(paused_summary.details["run_termination"]["terminal"])
            self.assertEqual(paused_summary.details["run_termination"]["completed_step_count"], 0)
            self.assertTrue(paused_summary.resumable)
            self.assertIsNotNone(paused_summary.resume_token)
            self.assertTrue(paused_summary.pause_state_path.exists())
            self.assertEqual(pause_payload["resume_from_step_index"], 0)
            self.assertEqual(pause_payload["resume_from_step_id"], "step-1")
            self.assertEqual(pause_payload["continuation_policy"], "wait_for_decision")
            self.assertEqual(
                [item["action_type"] for item in pause_payload["available_operator_actions"]],
                ["continue_if_fixed", "skip_step", "abort_run"],
            )
            self.assertEqual(pause_payload["recommended_operator_action_id"], "continue_if_fixed")
            self.assertIn("- Continuation state: `paused`", report_content)
            self.assertIn("## Operator actions", report_content)
            self.assertIn("## Resume", report_content)

            self.assertEqual(resumed_summary.run_id, paused_summary.run_id)
            self.assertEqual(resumed_summary.final_status, StepStatus.PASS)
            self.assertEqual(resumed_summary.continuation_state, RunContinuationState.RESUMED)
            self.assertEqual(resumed_summary.details["run_termination"]["kind"], RunTerminationKind.COMPLETED.value)
            self.assertEqual(
                resumed_summary.details["run_termination"]["reason"]["source"],
                TerminationReasonSource.OPERATOR.value,
            )
            self.assertFalse(resumed_summary.details["partial_completion"])
            self.assertFalse(resumed_summary.resumable)
            self.assertTrue(resumed_summary.resumed_from_pause)
            self.assertIsNotNone(resumed_summary.decision_resolution)
            self.assertEqual(
                resumed_summary.decision_resolution.selected_action.action_type.value,
                "continue_if_fixed",
            )
            self.assertEqual([step.step_id for step in resumed_summary.steps], ["step-1", "step-2"])
            self.assertTrue(all(step.status == StepStatus.PASS for step in resumed_summary.steps))
            self.assertEqual(executor.execute_count, 3)
            self.assertTrue(any(json.loads(line)["event_type"] == "decision_resolved" for line in journal_lines))
            self.assertTrue(any(json.loads(line)["event_type"] == "run_paused" for line in journal_lines))
            self.assertTrue(any(json.loads(line)["event_type"] == "run_resumed" for line in journal_lines))
            self.assertIn("- Continuation state: `resumed`", resumed_report)
            self.assertIn("## Decision resolution", resumed_report)

    def test_invalid_operator_action_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root)
            executor = _SequencedExecutorFactory(
                [
                    StepExecutionOutcome(
                        step_result=StepExecutionResult(
                            step_id="step-1",
                            step_number=1,
                            step_type=ScenarioStepType.API,
                            status=StepStatus.FAIL,
                            message="create failed",
                        )
                    )
                ]
            )
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )
            paused_summary = service.run(self._scenario(root), workspace_root=root)

            with self.assertRaises(ValidationError):
                service.resume(
                    paused_summary.pause_state_path,
                    operator_action_selection=OperatorActionSelection(
                        decision_point_id="decision:wrong",
                        action_id="not_allowed",
                    ),
                )

    def test_skip_step_action_continues_from_next_step_and_keeps_skipped_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root)
            executor = _SequencedExecutorFactory(
                [
                    StepExecutionOutcome(
                        step_result=StepExecutionResult(
                            step_id="step-1",
                            step_number=1,
                            step_type=ScenarioStepType.API,
                            status=StepStatus.PASS,
                            message="first ok",
                        )
                    ),
                    RuntimeError("downstream boom"),
                    StepExecutionOutcome(
                        step_result=StepExecutionResult(
                            step_id="step-3",
                            step_number=3,
                            step_type=ScenarioStepType.API,
                            status=StepStatus.PASS,
                            message="third ok",
                        )
                    ),
                ]
            )
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )
            paused_summary = service.run(self._three_step_runtime_failure_scenario(root), workspace_root=root)
            resumed_summary = service.resume(
                paused_summary.pause_state_path,
                operator_action_selection=OperatorActionSelection(
                    decision_point_id=paused_summary.guided_stop_reason.decision_point.decision_id,
                    action_id="skip_step",
                ),
            )

        self.assertEqual(paused_summary.final_status, StepStatus.ERROR)
        self.assertEqual(
            [action.action_type.value for action in paused_summary.available_operator_actions],
            ["retry_from_anchor", "skip_step", "abort_run"],
        )
        self.assertEqual(resumed_summary.final_status, StepStatus.ERROR)
        self.assertEqual(resumed_summary.continuation_state, RunContinuationState.RESUMED)
        self.assertEqual([step.step_id for step in resumed_summary.steps], ["step-1", "step-2", "step-3"])
        self.assertEqual(resumed_summary.steps[1].status, StepStatus.ERROR)
        self.assertEqual(resumed_summary.steps[2].status, StepStatus.PASS)
        self.assertEqual(
            resumed_summary.details["step_terminations"][1]["termination"]["kind"],
            StepTerminationKind.SKIPPED.value,
        )
        self.assertEqual(
            resumed_summary.details["step_terminations"][1]["termination"]["outcome_status"],
            StepStatus.ERROR.value,
        )
        self.assertEqual(
            resumed_summary.details["legacy_status_projection"]["final_status"],
            StepStatus.ERROR.value,
        )
        self.assertEqual(resumed_summary.decision_resolution.selected_action.action_type.value, "skip_step")
        self.assertEqual(executor.execute_count, 3)

    def test_abort_run_action_finishes_without_executing_more_steps(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root)
            executor = _SequencedExecutorFactory(
                [
                    StepExecutionOutcome(
                        step_result=StepExecutionResult(
                            step_id="step-1",
                            step_number=1,
                            step_type=ScenarioStepType.API,
                            status=StepStatus.PASS,
                            message="first ok",
                        )
                    ),
                    RuntimeError("downstream boom"),
                ]
            )
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )
            paused_summary = service.run(self._three_step_runtime_failure_scenario(root), workspace_root=root)
            resumed_summary = service.resume(
                paused_summary.pause_state_path,
                operator_action_selection=OperatorActionSelection(
                    decision_point_id=paused_summary.guided_stop_reason.decision_point.decision_id,
                    action_id="abort_run",
                ),
            )
            report_content = resumed_summary.report_path.read_text(encoding="utf-8")
            journal_lines = (
                resumed_summary.run_state_dir / "journal.jsonl"
            ).read_text(encoding="utf-8").splitlines()

        self.assertEqual(resumed_summary.final_status, StepStatus.ERROR)
        self.assertEqual(resumed_summary.details["run_termination"]["kind"], RunTerminationKind.ABORTED.value)
        self.assertEqual(
            resumed_summary.details["run_termination"]["reason"]["source"],
            TerminationReasonSource.OPERATOR.value,
        )
        self.assertTrue(resumed_summary.details["partial_completion"])
        self.assertEqual([step.step_id for step in resumed_summary.steps], ["step-1", "step-2"])
        self.assertEqual(resumed_summary.decision_resolution.selected_action.action_type.value, "abort_run")
        self.assertEqual(executor.execute_count, 2)
        self.assertIn("operator aborted", resumed_summary.message.lower())
        self.assertIn("## Decision resolution", report_content)
        self.assertTrue(any(json.loads(line)["event_type"] == "run_aborted" for line in journal_lines))

    def test_non_resumable_compile_block_remains_terminal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root)
            service = ScenarioRunnerService(step_executor_factory=_UnusedExecutorFactory())
            scenario = ScenarioDefinition(
                scenario_path=root / "scenario.md",
                scenario_slug="compile-block",
                scenario_name="Compile Block",
                project="code/demo-project",
                environment="env/demo.env",
                steps=[
                    ScenarioStep(
                        step_id="step-1",
                        step_number=1,
                        title="Step 1",
                        step_type=ScenarioStepType.API,
                        api=ApiStepDefinition(
                            method="GET",
                            path="/demo",
                            expected=["response magically works"],
                        ),
                    )
                ],
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.continuation_state, RunContinuationState.TERMINAL)
        self.assertFalse(summary.resumable)
        self.assertIsNone(summary.resume_token)
        self.assertIsNone(summary.pause_state_path)

    def test_ordinary_auto_run_execution_remains_terminal_and_compatible(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root)
            service = ScenarioRunnerService(
                step_executor_factory=_SequencedExecutorFactory(
                    [
                        StepExecutionOutcome(
                            step_result=StepExecutionResult(
                                step_id="step-1",
                                step_number=1,
                                step_type=ScenarioStepType.API,
                                status=StepStatus.PASS,
                                message="created",
                            ),
                            captured_values={"price_list_id": 123},
                        ),
                        StepExecutionOutcome(
                            step_result=StepExecutionResult(
                                step_id="step-2",
                                step_number=2,
                                step_type=ScenarioStepType.API,
                                status=StepStatus.PASS,
                                message="read ok",
                            )
                        ),
                    ]
                ),
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._scenario(root), workspace_root=root)
            payload = summary.to_dict()

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(summary.continuation_state, RunContinuationState.TERMINAL)
        self.assertEqual(summary.details["run_termination"]["kind"], RunTerminationKind.COMPLETED.value)
        self.assertEqual(summary.details["legacy_status_projection"]["final_status"], StepStatus.PASS.value)
        self.assertFalse(summary.resumable)
        self.assertIn("notes", payload)
        self.assertIn("checks", payload)
        self.assertIsNone(payload["pause_state_path"])

    @staticmethod
    def _prepare_workspace(root: Path) -> None:
        (root / "code" / "demo-project").mkdir(parents=True, exist_ok=True)
        (root / "env").mkdir(parents=True, exist_ok=True)
        (root / "env" / "demo.env").write_text("API_BASE_URL=http://localhost\n", encoding="utf-8")
        api_tool = root / "tools" / "api" / "run_request.py"
        api_tool.parent.mkdir(parents=True, exist_ok=True)
        api_tool.write_text("# api tool placeholder\n", encoding="utf-8")

    @staticmethod
    def _scenario(root: Path) -> ScenarioDefinition:
        scenario_path = root / "scenario.md"
        scenario_path.write_text("# Scenario: Pause Resume\n", encoding="utf-8")
        return ScenarioDefinition(
            scenario_path=scenario_path,
            scenario_slug="pause-resume",
            scenario_name="Pause Resume",
            project="code/demo-project",
            environment="env/demo.env",
            steps=[
                ScenarioStep(
                    step_id="step-1",
                    step_number=1,
                    title="Create",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(
                        method="POST",
                        path="/price-lists",
                        capture=["response.body.id -> price_list_id"],
                    ),
                ),
                ScenarioStep(
                    step_id="step-2",
                    step_number=2,
                    title="Read",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(method="GET", path="/price-lists/{{price_list_id}}"),
                ),
            ],
        )

    @staticmethod
    def _three_step_runtime_failure_scenario(root: Path) -> ScenarioDefinition:
        scenario_path = root / "runtime-failure-scenario.md"
        scenario_path.write_text("# Scenario: Runtime Failure\n", encoding="utf-8")
        return ScenarioDefinition(
            scenario_path=scenario_path,
            scenario_slug="runtime-failure",
            scenario_name="Runtime Failure",
            project="code/demo-project",
            environment="env/demo.env",
            steps=[
                ScenarioStep(
                    step_id="step-1",
                    step_number=1,
                    title="First",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(method="GET", path="/first"),
                ),
                ScenarioStep(
                    step_id="step-2",
                    step_number=2,
                    title="Second",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(method="GET", path="/second"),
                ),
                ScenarioStep(
                    step_id="step-3",
                    step_number=3,
                    title="Third",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(method="GET", path="/third"),
                ),
            ],
        )


class _SequencedExecutorFactory:
    def __init__(self, outcomes: list[StepExecutionOutcome | Exception]) -> None:
        self._outcomes = list(outcomes)
        self.execute_count = 0

    def create(self, step: ScenarioStep, workspace_root: Path) -> "_SequencedExecutorFactory":
        return self

    def execute(self, run_context, scenario_definition, step: ScenarioStep) -> StepExecutionOutcome:
        self.execute_count += 1
        next_outcome = self._outcomes.pop(0)
        if isinstance(next_outcome, Exception):
            raise next_outcome
        return next_outcome


class _UnusedExecutorFactory:
    def create(self, step: ScenarioStep, workspace_root: Path) -> "_UnusedExecutorFactory":
        return self

    def execute(self, run_context, scenario_definition, step: ScenarioStep):
        raise AssertionError("Executor should not run.")


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
