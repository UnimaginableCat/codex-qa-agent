from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.scenario_runner.executors import ApiStepExecutor
from tools.scenario_runner.interpolator import PlaceholderInterpolator
from tools.scenario_runner.models import (
    ApiStepDefinition,
    ScenarioDefinition,
    ScenarioStep,
    ScenarioStepType,
)
from tools.scenario_runner.preflight import PreflightCheckResult, PreflightResult
from tools.scenario_runner.services import ScenarioRunnerService


class ScenarioRunnerApiErrorMappingTests(unittest.TestCase):
    def test_malformed_tool_output_is_error(self) -> None:
        executor = _InspectableApiStepExecutor(Path.cwd())

        payload = executor.parse_tool_payload_for_test("not-json\n", "", 1)

        self.assertEqual(payload["status"], StepStatus.ERROR.value)
        self.assertIn("invalid JSON", payload["message"])

    def test_internal_executor_exception_is_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ScenarioRunnerService(
                step_executor_factory=_ExplodingExecutorFactory(),
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._scenario(root), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.ERROR)
        self.assertEqual(summary.steps[0].status, StepStatus.ERROR)
        self.assertIn("executor wrapper broke", summary.steps[0].message)

    @staticmethod
    def _scenario(root: Path) -> ScenarioDefinition:
        return ScenarioDefinition(
            scenario_path=root / "scenario.md",
            scenario_slug="api-error-mapping",
            scenario_name="API Error Mapping",
            project="code/demo",
            environment="env/demo.env",
            steps=[
                ScenarioStep(
                    step_id="step-1",
                    step_number=1,
                    title="smoke",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(method="GET", path="/smoke"),
                )
            ],
        )


class _InspectableApiStepExecutor(ApiStepExecutor):
    def __init__(self, workspace_root: Path) -> None:
        super().__init__(workspace_root=workspace_root, interpolator=PlaceholderInterpolator())

    def parse_tool_payload_for_test(self, stdout: str, stderr: str, returncode: int) -> dict:
        return self._parse_tool_payload(stdout, stderr, returncode)


class _ExplodingExecutorFactory:
    def create(self, step: ScenarioStep, workspace_root: Path) -> "_ExplodingExecutorFactory":
        return self

    def execute(self, run_context, scenario_definition, step: ScenarioStep):
        raise RuntimeError("executor wrapper broke")


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
