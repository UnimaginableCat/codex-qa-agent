from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.scenario_runner.context import initialize_run_context
from tools.scenario_runner.engine import ScenarioExecutionEngine
from tools.scenario_runner.executors import StepExecutionOutcome
from tools.scenario_runner.execution import ExecutionPhase
from tools.scenario_runner.models import (
    ApiStepDefinition,
    ScenarioDefinition,
    ScenarioStep,
    ScenarioStepType,
    StepExecutionResult,
)
from tools.scenario_runner.preflight import PreflightCheckResult, PreflightResult
from tools.scenario_runner.services import ScenarioRunnerService


class ScenarioExecutionEngineTests(unittest.TestCase):
    def test_engine_blocks_before_steps_when_preflight_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario = _scenario(root, include_second_step=False)
            executor = _CountingExecutorFactory([])
            engine = ScenarioExecutionEngine(
                step_executor_factory=executor,
                preflight_checker=_BlockedPreflightChecker(),
            )

            session = engine.create_session(initialize_run_context(scenario, workspace_root=root), scenario)
            session = engine.execute(session, scenario)

        self.assertEqual(executor.execute_count, 0)
        self.assertEqual(session.run_state.final_outcome.status, StepStatus.BLOCKED)
        self.assertEqual(session.run_context.step_results, [])
        self.assertEqual(session.preflight_checks[0].status, StepStatus.BLOCKED)
        self.assertEqual(session.execution_events[1].phase, ExecutionPhase.PREFLIGHT)

    def test_engine_stops_after_non_pass_step_and_adds_deferred_blocked_result(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario = _scenario(root, include_second_step=True)
            executor = _CountingExecutorFactory(
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
            engine = ScenarioExecutionEngine(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            session = engine.create_session(initialize_run_context(scenario, workspace_root=root), scenario)
            session = engine.execute(session, scenario)

        self.assertEqual(executor.execute_count, 1)
        self.assertEqual(session.run_context.step_results[0].status, StepStatus.FAIL)
        self.assertEqual(session.run_context.step_results[1].status, StepStatus.BLOCKED)
        self.assertEqual(session.run_context.step_results[1].details["phase"], "deferred_capture")
        self.assertEqual(session.run_state.final_outcome.status, StepStatus.BLOCKED)
        self.assertEqual(
            [event.event_type for event in session.execution_events],
            ["run_initialized", "preflight_completed", "initial_context_built", "step_completed"],
        )

    def test_service_uses_injected_engine(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario = _scenario(root, include_second_step=False)
            spy_engine = _SpyEngine(
                step_executor_factory=_CountingExecutorFactory(
                    [
                        StepExecutionOutcome(
                            step_result=StepExecutionResult(
                                step_id="step-1",
                                step_number=1,
                                step_type=ScenarioStepType.API,
                                status=StepStatus.PASS,
                                message="ok",
                            )
                        )
                    ]
                ),
                preflight_checker=_PassingPreflightChecker(),
            )
            service = ScenarioRunnerService(engine=spy_engine)

            summary = service.run(scenario, workspace_root=root)

        self.assertTrue(spy_engine.execute_called)
        self.assertEqual(summary.final_status, StepStatus.PASS)


def _scenario(root: Path, include_second_step: bool) -> ScenarioDefinition:
    scenario_path = root / "scenario.md"
    scenario_path.write_text("# Scenario: Demo\n", encoding="utf-8")
    steps = [
        ScenarioStep(
            step_id="step-1",
            step_number=1,
            title="create",
            step_type=ScenarioStepType.API,
            api=ApiStepDefinition(
                method="POST",
                path="/companies/demo/price-lists",
                capture=["response.body.id -> price_list_id"],
            ),
        )
    ]
    if include_second_step:
        steps.append(
            ScenarioStep(
                step_id="step-2",
                step_number=2,
                title="read",
                step_type=ScenarioStepType.API,
                api=ApiStepDefinition(method="GET", path="/price-lists/{{price_list_id}}"),
            )
        )
    return ScenarioDefinition(
        scenario_path=scenario_path,
        scenario_slug="engine-demo",
        scenario_name="Engine Demo",
        project="code/demo-project",
        environment="env/demo.env",
        steps=steps,
    )


class _CountingExecutorFactory:
    def __init__(self, outcomes: list[StepExecutionOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.execute_count = 0

    def create(self, step: ScenarioStep, workspace_root: Path) -> "_CountingExecutorFactory":
        return self

    def execute(self, run_context, scenario_definition, step: ScenarioStep) -> StepExecutionOutcome:
        self.execute_count += 1
        return self._outcomes.pop(0)


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


class _BlockedPreflightChecker:
    @staticmethod
    def run(scenario_definition, workspace_root):
        return PreflightResult(
            checks=[
                PreflightCheckResult(
                    name="environment_file_exists",
                    status=StepStatus.BLOCKED,
                    message="Environment file does not exist.",
                )
            ]
        )


class _SpyEngine(ScenarioExecutionEngine):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.execute_called = False

    def execute(self, session, scenario_definition):
        self.execute_called = True
        return super().execute(session, scenario_definition)


if __name__ == "__main__":
    unittest.main()
