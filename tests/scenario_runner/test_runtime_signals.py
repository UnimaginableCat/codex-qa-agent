from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.runtime_signals import (
    ContinuationHint,
    NormalizedRuntimeSignal,
    RetryHint,
    RuntimeFailureCategory,
    RuntimeSignalSource,
    RuntimeSignalTag,
    ToolFailureCode,
)
from tools.common.statuses import StepStatus
from tools.scenario_runner.domain.execution import ExecutionIssue, ExecutionIssueKind, ExecutionPhase
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
from tools.scenario_runner.runtime.normalization import (
    normalize_issue_runtime_signal,
    normalize_step_runtime_signal,
    normalize_tool_runtime_signal,
)


class RuntimeSignalNormalizationTests(unittest.TestCase):
    def test_raw_tool_payload_normalizes_connectivity_signal(self) -> None:
        signal = normalize_tool_runtime_signal(
            step_type=ScenarioStepType.API,
            status=StepStatus.BLOCKED,
            message="Request failed",
            payload={"classification": "connectivity"},
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.code, ToolFailureCode.API_CONNECTIVITY_BLOCKED)
        self.assertEqual(signal.continuation_hint, ContinuationHint.RETRY_MANUALLY)
        self.assertEqual(signal.retry_hint, RetryHint.MANUAL_RETRY)
        self.assertTrue(signal.resumable)

    def test_issue_normalization_for_unsupported_expectation_is_typed(self) -> None:
        signal = normalize_issue_runtime_signal(
            ExecutionIssue(
                code="compile_unsupported_expectation",
                message="Unsupported expectation rule.",
                phase=ExecutionPhase.COMPILATION,
                issue_type=ExecutionIssueKind.VALIDATION,
                outcome=StepStatus.BLOCKED,
            )
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.code, ToolFailureCode.UNSUPPORTED_EXPECTATION)
        self.assertEqual(signal.category, RuntimeFailureCategory.UNSUPPORTED)
        self.assertEqual(signal.continuation_hint, ContinuationHint.STOP_UNSUPPORTED)
        self.assertTrue(signal.runner_unsupported)

    def test_guided_projection_uses_explicit_runtime_signal_without_message_pattern(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ScenarioRunnerService(
                step_executor_factory=_StaticExecutorFactory(
                    [
                        StepExecutionOutcome(
                            step_result=StepExecutionResult(
                                step_id="step-1",
                                step_number=1,
                                step_type=ScenarioStepType.API,
                                status=StepStatus.BLOCKED,
                                message="blocked by normalized signal",
                                details={
                                    "runtime_signal": NormalizedRuntimeSignal(
                                        source=RuntimeSignalSource.TOOL,
                                        code=ToolFailureCode.API_AUTH_CONFIGURATION_BLOCKED,
                                        category=RuntimeFailureCategory.CONFIGURATION,
                                        retry_hint=RetryHint.AFTER_OPERATOR_FIX,
                                        continuation_hint=ContinuationHint.STOP_AND_FIX,
                                        tags=(
                                            RuntimeSignalTag.ENVIRONMENT_BLOCKED,
                                            RuntimeSignalTag.USER_FIXABLE,
                                        ),
                                        operator_fixable=True,
                                    ).to_dict()
                                },
                            )
                        )
                    ]
                ),
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(_scenario(root), workspace_root=root)

        diagnostic = next(
            diagnostic
            for diagnostic in summary.guided_diagnostics
            if diagnostic.step is not None and diagnostic.step.step_id == "step-1"
        )
        self.assertEqual(diagnostic.title, "API auth or base URL configuration blocked the step")
        self.assertEqual(diagnostic.summary, "blocked by normalized signal")

    def test_service_unavailable_signal_creates_decision_point(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ScenarioRunnerService(
                step_executor_factory=_StaticExecutorFactory(
                    [
                        StepExecutionOutcome(
                            step_result=StepExecutionResult(
                                step_id="step-1",
                                step_number=1,
                                step_type=ScenarioStepType.API,
                                status=StepStatus.BLOCKED,
                                message="remote unavailable",
                                details={
                                    "runtime_signal": NormalizedRuntimeSignal(
                                        source=RuntimeSignalSource.TOOL,
                                        code=ToolFailureCode.API_SERVICE_UNAVAILABLE,
                                        category=RuntimeFailureCategory.SERVICE_AVAILABILITY,
                                        retry_hint=RetryHint.AFTER_SERVICE_RECOVERY,
                                        continuation_hint=ContinuationHint.WAIT_FOR_DECISION,
                                        tags=(
                                            RuntimeSignalTag.RETRYABLE,
                                            RuntimeSignalTag.REQUIRES_DECISION,
                                        ),
                                        resumable=True,
                                        requires_decision=True,
                                    ).to_dict()
                                },
                            )
                        )
                    ]
                ),
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(_scenario(root), workspace_root=root)

        self.assertEqual(summary.guided_stop_reason.continuation_policy.value, "wait_for_decision")
        self.assertIsNotNone(summary.guided_stop_reason.decision_point)

    def test_message_fallback_remains_when_runtime_signal_absent(self) -> None:
        signal = normalize_step_runtime_signal(
            StepExecutionResult(
                step_id="step-1",
                step_number=1,
                step_type=ScenarioStepType.API,
                status=StepStatus.BLOCKED,
                message="API_AUTH_TYPE=basic but API_PASSWORD is missing",
                details={},
            )
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.code, ToolFailureCode.API_AUTH_CONFIGURATION_BLOCKED)


def _scenario(root: Path) -> ScenarioDefinition:
    scenario_path = root / "scenario.md"
    scenario_path.write_text("# Scenario: Runtime Signals\n", encoding="utf-8")
    return ScenarioDefinition(
        scenario_path=scenario_path,
        scenario_slug="runtime-signals",
        scenario_name="Runtime Signals",
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
    )


class _StaticExecutorFactory:
    def __init__(self, outcomes: list[StepExecutionOutcome]) -> None:
        self._outcomes = list(outcomes)

    def create(self, step: ScenarioStep, workspace_root: Path) -> "_StaticExecutorFactory":
        return self

    def execute(self, run_context, scenario_definition, step: ScenarioStep) -> StepExecutionOutcome:
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


if __name__ == "__main__":
    unittest.main()
