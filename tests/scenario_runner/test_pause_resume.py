from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
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

            resumed_summary = service.resume(
                paused_summary.pause_state_path,
                selected_action_id="retry_after_fixing_producer",
            )
            journal_lines = (
                resumed_summary.run_state_dir / "journal.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            resumed_report = resumed_summary.report_path.read_text(encoding="utf-8")

            self.assertEqual(paused_summary.final_status, StepStatus.BLOCKED)
            self.assertEqual(paused_summary.continuation_state, RunContinuationState.PAUSED)
            self.assertTrue(paused_summary.resumable)
            self.assertIsNotNone(paused_summary.resume_token)
            self.assertTrue(paused_summary.pause_state_path.exists())
            self.assertEqual(pause_payload["resume_from_step_index"], 0)
            self.assertEqual(pause_payload["resume_from_step_id"], "step-1")
            self.assertEqual(pause_payload["continuation_policy"], "wait_for_decision")
            self.assertIn("- Continuation state: `paused`", report_content)
            self.assertIn("## Resume", report_content)

            self.assertEqual(resumed_summary.run_id, paused_summary.run_id)
            self.assertEqual(resumed_summary.final_status, StepStatus.PASS)
            self.assertEqual(resumed_summary.continuation_state, RunContinuationState.RESUMED)
            self.assertFalse(resumed_summary.resumable)
            self.assertTrue(resumed_summary.resumed_from_pause)
            self.assertEqual([step.step_id for step in resumed_summary.steps], ["step-1", "step-2"])
            self.assertTrue(all(step.status == StepStatus.PASS for step in resumed_summary.steps))
            self.assertEqual(executor.execute_count, 3)
            self.assertTrue(any(json.loads(line)["event_type"] == "run_paused" for line in journal_lines))
            self.assertTrue(any(json.loads(line)["event_type"] == "run_resumed" for line in journal_lines))
            self.assertIn("- Continuation state: `resumed`", resumed_report)

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


class _SequencedExecutorFactory:
    def __init__(self, outcomes: list[StepExecutionOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.execute_count = 0

    def create(self, step: ScenarioStep, workspace_root: Path) -> "_SequencedExecutorFactory":
        return self

    def execute(self, run_context, scenario_definition, step: ScenarioStep) -> StepExecutionOutcome:
        self.execute_count += 1
        return self._outcomes.pop(0)


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
