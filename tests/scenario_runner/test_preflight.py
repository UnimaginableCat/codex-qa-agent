from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.scenario_runner.domain.models import (
    ApiStepDefinition,
    DbStepDefinition,
    ScenarioDefinition,
    ScenarioStep,
    ScenarioStepType,
    StepExecutionResult,
)
from tools.scenario_runner.orchestration.services import ScenarioRunnerService
from tools.scenario_runner.runtime.executors import StepExecutionOutcome


class ScenarioRunnerPreflightTests(unittest.TestCase):
    def test_missing_env_file_blocks_before_step_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=False, create_project=True, create_api_tool=True)
            executor = _CountingStepExecutorFactory()
            service = ScenarioRunnerService(step_executor_factory=executor)

            with self._dependencies_available():
                summary = service.run(self._scenario(root, ScenarioStepType.API), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(executor.execute_count, 0)
        self.assertTrue(any("environment_file_exists" in issue for issue in summary.tooling_issues))

    def test_missing_project_path_blocks_before_step_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=True, create_project=False, create_api_tool=True)
            executor = _CountingStepExecutorFactory()
            service = ScenarioRunnerService(step_executor_factory=executor)

            with self._dependencies_available():
                summary = service.run(self._scenario(root, ScenarioStepType.API), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(executor.execute_count, 0)
        self.assertTrue(any("target_project_path_exists" in issue for issue in summary.tooling_issues))

    def test_api_scenario_without_requests_is_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=True, create_project=True, create_api_tool=True)
            executor = _CountingStepExecutorFactory()
            service = ScenarioRunnerService(step_executor_factory=executor)

            with self._missing_dependency("requests"):
                summary = service.run(self._scenario(root, ScenarioStepType.API), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.ERROR)
        self.assertEqual(executor.execute_count, 0)
        self.assertTrue(any("dependency_requests_available" in issue for issue in summary.tooling_issues))

    def test_db_scenario_without_psycopg_is_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=True, create_project=True, create_db_tool=True)
            executor = _CountingStepExecutorFactory()
            service = ScenarioRunnerService(step_executor_factory=executor)

            with self._missing_dependency("psycopg"):
                summary = service.run(self._scenario(root, ScenarioStepType.DB), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.ERROR)
        self.assertEqual(executor.execute_count, 0)
        self.assertTrue(any("dependency_psycopg_available" in issue for issue in summary.tooling_issues))

    def test_missing_tool_entrypoint_is_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=True, create_project=True, create_api_tool=False)
            executor = _CountingStepExecutorFactory()
            service = ScenarioRunnerService(step_executor_factory=executor)

            with self._dependencies_available():
                summary = service.run(self._scenario(root, ScenarioStepType.API), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.ERROR)
        self.assertEqual(executor.execute_count, 0)
        self.assertTrue(any("api_tool_entrypoint_exists" in issue for issue in summary.tooling_issues))

    def test_successful_preflight_allows_minimal_valid_scenario_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=True, create_project=True, create_api_tool=True)
            executor = _CountingStepExecutorFactory()
            service = ScenarioRunnerService(step_executor_factory=executor)

            with self._dependencies_available():
                summary = service.run(self._scenario(root, ScenarioStepType.API), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.execute_count, 1)
        self.assertTrue(summary.details["preflight_checks"])
        self.assertTrue(
            all(check["status"] == StepStatus.PASS.value for check in summary.details["preflight_checks"])
        )

    def test_failed_preflight_prevents_step_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=False, create_project=True, create_api_tool=True)
            executor = _CountingStepExecutorFactory()
            service = ScenarioRunnerService(step_executor_factory=executor)

            with self._dependencies_available():
                summary = service.run(self._scenario(root, ScenarioStepType.API), workspace_root=root)

        self.assertEqual(executor.execute_count, 0)
        self.assertEqual(summary.steps, [])
        self.assertEqual(summary.message, "Scenario preflight failed with status BLOCKED.")

    def test_step_actor_profile_is_checked_before_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=True, create_project=True, create_api_tool=True)
            (root / "env" / "demo.env").write_text(
                "\n".join(
                    [
                        "API_BASE_URL=http://localhost",
                        "API_AUTH_TYPE__PARTNER=none",
                    ]
                ),
                encoding="utf-8",
            )
            scenario = self._scenario(root, ScenarioStepType.API)
            scenario.steps[0].actor = "partner"
            executor = _CountingStepExecutorFactory()
            service = ScenarioRunnerService(step_executor_factory=executor)

            with self._dependencies_available():
                summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.execute_count, 1)
        self.assertTrue(
            any(check["name"] == "step_actor_profiles_resolvable" for check in summary.details["preflight_checks"])
        )

    def test_missing_role_actor_profile_blocks_before_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=True, create_project=True, create_api_tool=True)
            scenario = self._scenario(root, ScenarioStepType.API)
            scenario.steps[0].actor = "partner"
            executor = _CountingStepExecutorFactory()
            service = ScenarioRunnerService(step_executor_factory=executor)

            with self._dependencies_available():
                summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(executor.execute_count, 0)
        self.assertTrue(any("step_actor_profiles_resolvable" in issue for issue in summary.tooling_issues))

    def test_invalid_variables_section_blocks_before_step_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_workspace(root, create_env=True, create_project=True, create_api_tool=True)
            scenario = self._scenario(root, ScenarioStepType.API)
            scenario.metadata["variables_validation_errors"] = [
                "Variables section has invalid definition for 'email_suffix': ambiguous untyped value"
            ]
            executor = _CountingStepExecutorFactory()
            service = ScenarioRunnerService(step_executor_factory=executor)

            with self._dependencies_available():
                summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(executor.execute_count, 0)
        self.assertEqual(summary.message, "Scenario compilation failed with status BLOCKED.")
        self.assertTrue(any("compile_variables_section_invalid" in issue for issue in summary.tooling_issues))
        self.assertTrue(any("email_suffix" in issue for issue in summary.tooling_issues))
        self.assertEqual(summary.details["compile_statuses"], [StepStatus.BLOCKED.value])
        self.assertTrue(summary.details["compile_checks"])

    @staticmethod
    def _scenario(root: Path, step_type: ScenarioStepType) -> ScenarioDefinition:
        scenario_path = root / "scenario.md"
        scenario_path.write_text("# Scenario: Demo\n", encoding="utf-8")
        if step_type == ScenarioStepType.API:
            step = ScenarioStep(
                step_id="step-1",
                step_number=1,
                title="API step",
                step_type=ScenarioStepType.API,
                api=ApiStepDefinition(method="GET", path="/demo"),
            )
        else:
            step = ScenarioStep(
                step_id="step-1",
                step_number=1,
                title="DB step",
                step_type=ScenarioStepType.DB,
                db=DbStepDefinition(sql="SELECT 1"),
            )
        return ScenarioDefinition(
            scenario_path=scenario_path,
            scenario_slug="demo",
            scenario_name="Demo",
            project="code/demo-project",
            environment="env/demo.env",
            steps=[step],
        )

    @staticmethod
    def _prepare_workspace(
        root: Path,
        create_env: bool,
        create_project: bool,
        create_api_tool: bool = False,
        create_db_tool: bool = False,
    ) -> None:
        if create_env:
            (root / "env").mkdir(parents=True, exist_ok=True)
            (root / "env" / "demo.env").write_text("API_BASE_URL=http://localhost\n", encoding="utf-8")
        if create_project:
            (root / "code" / "demo-project").mkdir(parents=True, exist_ok=True)
        if create_api_tool:
            api_tool = root / "tools" / "api" / "run_request.py"
            api_tool.parent.mkdir(parents=True, exist_ok=True)
            api_tool.write_text("# api tool placeholder\n", encoding="utf-8")
        if create_db_tool:
            db_tool = root / "tools" / "db" / "query_check.py"
            db_tool.parent.mkdir(parents=True, exist_ok=True)
            db_tool.write_text("# db tool placeholder\n", encoding="utf-8")

    @staticmethod
    def _dependencies_available():
        return patch("tools.scenario_runner.orchestration.preflight.importlib.util.find_spec", return_value=object())

    @staticmethod
    def _missing_dependency(module_name: str):
        def fake_find_spec(candidate: str):
            return None if candidate == module_name else object()

        return patch("tools.scenario_runner.orchestration.preflight.importlib.util.find_spec", side_effect=fake_find_spec)


class _CountingStepExecutorFactory:
    def __init__(self) -> None:
        self.execute_count = 0

    def create(self, step: ScenarioStep, workspace_root: Path) -> "_CountingStepExecutorFactory":
        return self

    def execute(self, run_context, scenario_definition, step: ScenarioStep) -> StepExecutionOutcome:
        self.execute_count += 1
        return StepExecutionOutcome(
            step_result=StepExecutionResult(
                step_id=step.step_id,
                step_number=step.step_number,
                step_type=step.step_type,
                status=StepStatus.PASS,
                message="step executed",
            )
        )


if __name__ == "__main__":
    unittest.main()
