from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.reports.renderers import MarkdownReportRenderer
from tools.scenario_runner.domain.guided import ContinuationPolicy, GuidedDiagnosticTag
from tools.scenario_runner.domain.models import (
    ApiStepDefinition,
    ScenarioDefinition,
    ScenarioStep,
    ScenarioStepType,
    StepExecutionResult,
)
from tools.scenario_runner.orchestration.preflight import PreflightCheckResult, PreflightResult
from tools.scenario_runner.orchestration.services import ScenarioRunnerService
from tools.scenario_runner.projections.reporting import build_report_context
from tools.scenario_runner.runtime.executors import StepExecutionOutcome


class GuidedDiagnosticsTests(unittest.TestCase):
    def test_compile_unsupported_expectation_projects_guided_runner_limitation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=True)
            service = ScenarioRunnerService(step_executor_factory=_UnusedExecutorFactory())

            summary = service.run(
                ScenarioDefinition(
                    scenario_path=root / "scenario.md",
                    scenario_slug="guided-compile",
                    scenario_name="Guided Compile",
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
                ),
                workspace_root=root,
            )

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        diagnostic = next(
            diagnostic
            for diagnostic in summary.guided_diagnostics
            if diagnostic.issue_code == "compile_unsupported_expectation"
        )
        self.assertIn(GuidedDiagnosticTag.UNSUPPORTED_BY_RUNNER, diagnostic.tags)
        self.assertEqual(diagnostic.continuation_policy, ContinuationPolicy.STOP_UNSUPPORTED)
        self.assertIs(summary.guided_stop_reason, diagnostic)
        summary_payload = summary.to_dict()
        self.assertIn("notes", summary_payload)
        self.assertIn("checks", summary_payload)
        self.assertIn("guided_diagnostics", summary_payload)

    def test_preflight_missing_env_projects_environment_blocked_guidance(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=False)
            service = ScenarioRunnerService(step_executor_factory=_UnusedExecutorFactory())

            with patch("tools.scenario_runner.orchestration.preflight.importlib.util.find_spec", return_value=object()):
                summary = service.run(self._scenario(root), workspace_root=root)

        diagnostic = next(
            diagnostic
            for diagnostic in summary.guided_diagnostics
            if diagnostic.issue_code == "preflight_environment_file_exists"
        )
        self.assertIn(GuidedDiagnosticTag.ENVIRONMENT_BLOCKED, diagnostic.tags)
        self.assertIn(GuidedDiagnosticTag.USER_FIXABLE, diagnostic.tags)
        self.assertEqual(diagnostic.continuation_policy, ContinuationPolicy.STOP_AND_FIX)

    def test_runtime_auth_block_projects_user_actionable_guidance(self) -> None:
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
                                message="API_AUTH_TYPE=basic but API_PASSWORD is missing",
                                details={"tool_classification": None},
                            )
                        )
                    ]
                ),
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._scenario(root), workspace_root=root)

        diagnostic = next(
            diagnostic
            for diagnostic in summary.guided_diagnostics
            if diagnostic.step is not None and diagnostic.step.step_id == "step-1"
        )
        self.assertEqual(diagnostic.title, "API auth or base URL configuration blocked the step")
        self.assertIn(GuidedDiagnosticTag.ENVIRONMENT_BLOCKED, diagnostic.tags)
        self.assertEqual(diagnostic.continuation_policy, ContinuationPolicy.STOP_AND_FIX)

    def test_deferred_capture_blocked_creates_decision_point(self) -> None:
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
                                status=StepStatus.FAIL,
                                message="create failed",
                            )
                        )
                    ]
                ),
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._captured_variable_scenario(root), workspace_root=root)

        diagnostic = next(
            diagnostic
            for diagnostic in summary.guided_diagnostics
            if diagnostic.issue_code == "deferred_capture_blocked"
        )
        self.assertIn(GuidedDiagnosticTag.REQUIRES_DECISION, diagnostic.tags)
        self.assertEqual(diagnostic.continuation_policy, ContinuationPolicy.WAIT_FOR_DECISION)
        self.assertIsNotNone(diagnostic.decision_point)
        self.assertTrue(summary.to_dict()["guided_decision_points"])

    def test_report_context_and_renderer_include_guided_diagnostics(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=True)
            service = ScenarioRunnerService(step_executor_factory=_UnusedExecutorFactory())

            summary = service.run(
                ScenarioDefinition(
                    scenario_path=root / "scenario.md",
                    scenario_slug="guided-report",
                    scenario_name="Guided Report",
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
                ),
                workspace_root=root,
            )

        report_context = build_report_context(summary)
        rendered = MarkdownReportRenderer().render(report_context)

        self.assertTrue(report_context.summary.guided_diagnostics)
        self.assertIn("## Guided diagnostics", rendered)
        self.assertIn("Scenario uses runner syntax that is not supported", rendered)

    @staticmethod
    def _scenario(root: Path) -> ScenarioDefinition:
        scenario_path = root / "scenario.md"
        scenario_path.write_text("# Scenario: Guided\n", encoding="utf-8")
        return ScenarioDefinition(
            scenario_path=scenario_path,
            scenario_slug="guided-runtime",
            scenario_name="Guided Runtime",
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

    @classmethod
    def _captured_variable_scenario(cls, root: Path) -> ScenarioDefinition:
        scenario = cls._scenario(root)
        scenario.steps[0].api.capture = ["response.body.id -> price_list_id"]
        scenario.steps.append(
            ScenarioStep(
                step_id="step-2",
                step_number=2,
                title="Step 2",
                step_type=ScenarioStepType.API,
                api=ApiStepDefinition(method="GET", path="/price-lists/{{price_list_id}}"),
            )
        )
        return scenario

    @staticmethod
    def _prepare_workspace(root: Path, *, create_env: bool) -> None:
        (root / "code" / "demo-project").mkdir(parents=True, exist_ok=True)
        api_tool = root / "tools" / "api" / "run_request.py"
        api_tool.parent.mkdir(parents=True, exist_ok=True)
        api_tool.write_text("# api tool placeholder\n", encoding="utf-8")
        if create_env:
            (root / "env").mkdir(parents=True, exist_ok=True)
            (root / "env" / "demo.env").write_text("API_BASE_URL=http://localhost\n", encoding="utf-8")


class _UnusedExecutorFactory:
    def create(self, step: ScenarioStep, workspace_root: Path) -> "_UnusedExecutorFactory":
        return self

    def execute(self, run_context, scenario_definition, step: ScenarioStep):
        raise AssertionError("Executor should not be used in this test.")


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
