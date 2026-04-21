from __future__ import annotations

import json
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
    ScenarioVariableDefinition,
    ScenarioVariableSource,
)
from tools.scenario_runner.parser import MarkdownScenarioParser
from tools.scenario_runner.preflight import PreflightCheckResult, PreflightResult
from tools.scenario_runner.services import ScenarioRunnerService


class ScenarioVariableTests(unittest.TestCase):
    def test_variables_section_is_parsed_preserved_and_not_unknown(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Variables

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - company_guid = env:COMPANY_GUID
                - run_suffix = generated
                - literal_name = fixed value
                - generated_price_list_name = AUTOTEST Attributes Flow {{run_suffix}}

                ## Steps

                ### Step 1
                Type: api
                Name: create
                Method: POST
                Path: /companies/{{company_guid}}/price-lists
                """,
            )

            scenario = MarkdownScenarioParser().parse(scenario_path)

        self.assertEqual(
            [variable.name for variable in scenario.variables],
            ["company_guid", "run_suffix", "literal_name", "generated_price_list_name"],
        )
        self.assertEqual(scenario.variables[0].source, ScenarioVariableSource.ENV)
        self.assertEqual(scenario.variables[1].source, ScenarioVariableSource.RUNTIME)
        self.assertEqual(scenario.variables[2].source, ScenarioVariableSource.LITERAL)
        self.assertEqual(scenario.variables[3].source, ScenarioVariableSource.TEMPLATE)
        self.assertFalse(
            any("Unknown scenario section 'Variables'" in warning for warning in scenario.metadata["parse_warnings"])
        )
        self.assertIn("variables", scenario.to_dict())
        self.assertEqual(scenario.to_dict()["variables"][0]["env_name"], "COMPANY_GUID")

    def test_initial_context_resolves_run_suffix_env_and_template_variables(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-123\n")
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._scenario(root), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.run_variables["company_guid"], "company-123")
        self.assertIn("run_suffix", executor.run_variables)
        self.assertTrue(str(executor.run_variables["run_suffix"]).startswith("202"))
        self.assertEqual(
            executor.run_variables["generated_price_list_name"],
            f"AUTOTEST Attributes Flow {executor.run_variables['run_suffix']}",
        )

    def test_step_one_payload_interpolates_path_headers_body_and_params_from_initial_variables(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-456\n")
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._scenario(root), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.step_payload["path"], "/companies/company-456/price-lists")
        self.assertEqual(executor.step_payload["headers"]["X-Company-Guid"], "company-456")
        self.assertEqual(
            executor.step_payload["body"]["name"],
            executor.run_variables["generated_price_list_name"],
        )
        self.assertEqual(executor.step_payload["query_params"]["companyGuid"], "company-456")

    def test_unresolved_initial_variable_returns_blocked_without_step_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-789\n")
            executor = _CapturingExecutorFactory()
            scenario = self._scenario(
                root,
                variables=[
                    ScenarioVariableDefinition(
                        name="bad_name",
                        raw_value="prefix {{missing_variable}}",
                        source=ScenarioVariableSource.TEMPLATE,
                    )
                ],
            )
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(executor.execute_count, 0)
        self.assertEqual(summary.steps[0].status, StepStatus.BLOCKED)
        self.assertIn("missing_variable", summary.steps[0].message)
        self.assertEqual(summary.steps[0].details["phase"], "initial_context")
        self.assertIn("missing_variable", summary.steps[0].details["unresolved_variables"])

    @staticmethod
    def _scenario(
        root: Path,
        variables: list[ScenarioVariableDefinition] | None = None,
    ) -> ScenarioDefinition:
        return ScenarioDefinition(
            scenario_path=root / "scenario.md",
            scenario_slug="variables-demo",
            scenario_name="Variables Demo",
            project="code/demo",
            environment="env/demo.env",
            variables=variables
            or [
                ScenarioVariableDefinition(
                    name="company_guid",
                    raw_value="env:COMPANY_GUID",
                    source=ScenarioVariableSource.ENV,
                    env_name="COMPANY_GUID",
                ),
                ScenarioVariableDefinition(
                    name="run_suffix",
                    raw_value="generated:run_suffix",
                    source=ScenarioVariableSource.RUNTIME,
                ),
                ScenarioVariableDefinition(
                    name="generated_price_list_name",
                    raw_value="AUTOTEST Attributes Flow {{run_suffix}}",
                    source=ScenarioVariableSource.TEMPLATE,
                ),
            ],
            steps=[
                ScenarioStep(
                    step_id="step-1",
                    step_number=1,
                    title="create price list",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(
                        method="POST",
                        path="/companies/{{company_guid}}/price-lists",
                        headers={"X-Company-Guid": "{{company_guid}}"},
                        params={"companyGuid": "{{company_guid}}"},
                        body={"name": "{{generated_price_list_name}}"},
                    ),
                )
            ],
        )

    @staticmethod
    def _prepare_env(root: Path, content: str) -> None:
        (root / "env").mkdir(parents=True, exist_ok=True)
        (root / "env" / "demo.env").write_text(content, encoding="utf-8")

    @staticmethod
    def _write_scenario(root: Path, content: str) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        scenario_path = root / "scenario.md"
        scenario_path.write_text(_dedent(content), encoding="utf-8")
        return scenario_path


class _CapturingExecutorFactory:
    def __init__(self) -> None:
        self.execute_count = 0
        self.step_payload: dict | None = None
        self.run_variables: dict | None = None

    def create(self, step: ScenarioStep, workspace_root: Path) -> "_CapturingApiStepExecutor":
        return _CapturingApiStepExecutor(workspace_root, self)


class _CapturingApiStepExecutor(ApiStepExecutor):
    def __init__(self, workspace_root: Path, owner: _CapturingExecutorFactory) -> None:
        super().__init__(workspace_root=workspace_root, interpolator=PlaceholderInterpolator())
        self._owner = owner

    def execute(self, run_context, scenario_definition, step: ScenarioStep):
        self._owner.execute_count += 1
        self._owner.run_variables = dict(run_context.variables)
        return super().execute(run_context, scenario_definition, step)

    def _invoke_cli(self, env_path: Path, step_file: Path) -> dict:
        self._owner.step_payload = json.loads(step_file.read_text(encoding="utf-8"))
        return {
            "command": ["test-api"],
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "result": {
                "status": StepStatus.PASS.value,
                "message": "ok",
                "response": {"http_status": 200, "body": {"ok": True}},
            },
        }


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


def _dedent(value: str) -> str:
    lines = value.strip("\n").splitlines()
    non_empty_lines = [line for line in lines if line.strip()]
    indent = min((len(line) - len(line.lstrip())) for line in non_empty_lines) if non_empty_lines else 0
    return "\n".join(line[indent:] for line in lines) + "\n"


if __name__ == "__main__":
    unittest.main()
