from __future__ import annotations

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
    ScenarioVariableDefinition,
    ScenarioVariableSource,
)
from tools.scenario_runner.orchestration.compiler import ScenarioCompiler
from tools.scenario_runner.orchestration.services import ScenarioRunnerService


class ScenarioCompilerTests(unittest.TestCase):
    def test_compiler_marks_unsupported_expectation_as_compile_blocker(self) -> None:
        compiler = ScenarioCompiler()
        scenario = _scenario(
            steps=[
                ScenarioStep(
                    step_id="step-1",
                    step_number=1,
                    title="create",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(
                        method="POST",
                        path="/items",
                        expected=["response magically works"],
                    ),
                )
            ]
        )

        compiled = compiler.compile(scenario)

        self.assertEqual(compiled.compile_result.status, StepStatus.BLOCKED)
        self.assertTrue(any(check.name == "expectations_supported" for check in compiled.compile_result.failed_checks()))
        self.assertTrue(any(issue.code == "compile_unsupported_expectation" for issue in compiled.compile_result.issues))

    def test_compiler_blocks_when_step_depends_on_future_capture(self) -> None:
        compiler = ScenarioCompiler()
        scenario = _scenario(
            steps=[
                ScenarioStep(
                    step_id="step-1",
                    step_number=1,
                    title="create",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(method="GET", path="/items/{{captured_later}}"),
                ),
                ScenarioStep(
                    step_id="step-2",
                    step_number=2,
                    title="read",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(
                        method="POST",
                        path="/items",
                        capture=["response.body.id -> captured_later"],
                    ),
                ),
            ]
        )

        compiled = compiler.compile(scenario)

        self.assertEqual(compiled.compile_result.status, StepStatus.BLOCKED)
        self.assertTrue(any(issue.code == "compile_future_capture_dependency" for issue in compiled.compile_result.issues))

    def test_service_blocks_unsupported_expectation_before_executor_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "env").mkdir(parents=True, exist_ok=True)
            (root / "env" / "demo.env").write_text("API_BASE_URL=http://localhost\n", encoding="utf-8")
            (root / "code" / "demo").mkdir(parents=True, exist_ok=True)
            (root / "tools" / "api").mkdir(parents=True, exist_ok=True)
            (root / "tools" / "api" / "run_request.py").write_text("# placeholder\n", encoding="utf-8")
            executor = _CountingExecutorFactory()
            service = ScenarioRunnerService(step_executor_factory=executor)

            summary = service.run(
                _scenario(
                    root=root,
                    steps=[
                        ScenarioStep(
                            step_id="step-1",
                            step_number=1,
                            title="create",
                            step_type=ScenarioStepType.API,
                            api=ApiStepDefinition(
                                method="POST",
                                path="/items",
                                expected=["response magically works"],
                            ),
                        )
                    ],
                ),
                workspace_root=root,
            )

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(summary.message, "Scenario compilation failed with status BLOCKED.")
        self.assertEqual(executor.execute_count, 0)
        self.assertTrue(any("compile_unsupported_expectation" in issue for issue in summary.tooling_issues))
        self.assertEqual(summary.details["compile_statuses"], [StepStatus.BLOCKED.value])

    def test_compiler_tracks_external_inputs_for_preflight_resolution(self) -> None:
        compiler = ScenarioCompiler()
        scenario = _scenario(
            variables=[
                ScenarioVariableDefinition(
                    name="company_guid",
                    raw_value="env:COMPANY_GUID",
                    source=ScenarioVariableSource.ENV,
                    env_name="COMPANY_GUID",
                )
            ],
            steps=[
                ScenarioStep(
                    step_id="step-1",
                    step_number=1,
                    title="create",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(method="GET", path="/companies/{{company_guid}}"),
                )
            ],
        )

        compiled = compiler.compile(scenario)

        self.assertEqual(compiled.compile_result.status, StepStatus.PASS)
        self.assertEqual(
            [item.variable_name for item in compiled.compile_result.required_external_inputs],
            ["company_guid"],
        )


def _scenario(
    root: Path | None = None,
    *,
    steps: list[ScenarioStep],
    variables: list[ScenarioVariableDefinition] | None = None,
) -> ScenarioDefinition:
    base_root = root or Path(".")
    scenario_path = base_root / "scenario.md"
    return ScenarioDefinition(
        scenario_path=scenario_path,
        scenario_slug="compiler-demo",
        scenario_name="Compiler Demo",
        project="code/demo",
        environment="env/demo.env",
        variables=variables or [],
        steps=steps,
    )


class _CountingExecutorFactory:
    def __init__(self) -> None:
        self.execute_count = 0

    def create(self, step: ScenarioStep, workspace_root: Path) -> "_CountingExecutorFactory":
        return self

    def execute(self, run_context, scenario_definition, step: ScenarioStep):
        self.execute_count += 1
        raise AssertionError("Executor should not run when compilation blocks execution.")


if __name__ == "__main__":
    unittest.main()
