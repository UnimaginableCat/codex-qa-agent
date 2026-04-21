from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.scenario_runner.executors import ApiStepExecutor
from tools.scenario_runner.interpolator import PlaceholderInterpolator
from tools.scenario_runner.models import (
    ApiStepDefinition,
    RunContext,
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

    def test_local_tool_subprocess_uses_parent_interpreter_env_and_workspace_cwd(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = _InspectableApiStepExecutor(root)
            captured = {}

            def fake_run(command, **kwargs):
                captured["command"] = command
                captured["kwargs"] = kwargs
                return SimpleNamespace(
                    returncode=0,
                    stdout='{"status": "PASS", "message": "ok"}\n',
                    stderr="",
                )

            with patch.dict(
                os.environ,
                {
                    "VIRTUAL_ENV": str(root / ".venv"),
                    "PATH": f"{root / '.venv' / 'bin'}{os.pathsep}existing-path",
                    "HTTP_PROXY": "http://proxy.local:8080",
                    "HTTPS_PROXY": "https://proxy.local:8443",
                    "NO_PROXY": "localhost,127.0.0.1",
                    "REQUESTS_CA_BUNDLE": "/tmp/ca.pem",
                    "SSL_CERT_FILE": "/tmp/ssl.pem",
                },
            ):
                with patch("tools.scenario_runner.executors.subprocess.run", side_effect=fake_run):
                    result = executor.invoke_cli_for_test(root / "env" / "demo.env", root / "step.json")

        self.assertEqual(captured["command"][0], sys.executable)
        self.assertEqual(captured["kwargs"]["cwd"], root)
        self.assertEqual(captured["kwargs"]["env"]["VIRTUAL_ENV"], str(root / ".venv"))
        self.assertIn(str(root / ".venv" / "bin"), captured["kwargs"]["env"]["PATH"])
        self.assertEqual(captured["kwargs"]["env"]["HTTP_PROXY"], "http://proxy.local:8080")
        self.assertEqual(result["debug"]["interpreter_path"], sys.executable)
        self.assertEqual(result["debug"]["cwd"], str(root))
        self.assertEqual(result["debug"]["VIRTUAL_ENV"], str(root / ".venv"))
        self.assertEqual(result["debug"]["NO_PROXY"], "localhost,127.0.0.1")
        self.assertEqual(result["debug"]["REQUESTS_CA_BUNDLE"], "/tmp/ca.pem")
        self.assertEqual(result["debug"]["SSL_CERT_FILE"], "/tmp/ssl.pem")

    def test_local_tool_subprocess_debug_redacts_proxy_credentials(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = _InspectableApiStepExecutor(root)

            def fake_run(command, **kwargs):
                return SimpleNamespace(
                    returncode=0,
                    stdout='{"status": "PASS", "message": "ok"}\n',
                    stderr="",
                )

            with patch.dict(
                os.environ,
                {
                    "HTTP_PROXY": "http://user:secret@proxy.local:8080",
                    "HTTPS_PROXY": "https://user:secret@proxy.local:8443",
                },
            ):
                with patch("tools.scenario_runner.executors.subprocess.run", side_effect=fake_run):
                    result = executor.invoke_cli_for_test(root / "env" / "demo.env", root / "step.json")

        self.assertEqual(result["debug"]["HTTP_PROXY"], "http://<redacted>@proxy.local:8080")
        self.assertEqual(result["debug"]["HTTPS_PROXY"], "https://<redacted>@proxy.local:8443")

    def test_api_executor_copies_request_diagnostics_to_step_details(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_context = self._run_context(root)
            scenario = self._scenario(root)
            executor = _InspectableApiStepExecutor(root)
            api_request_debug = {
                "final_url_value": "https://app2.101-group.ru/api/price_list/",
                "hostname_value": "app2.101-group.ru",
                "dns_precheck": {"getaddrinfo": {"status": "PASS"}},
                "resolver_debug": {
                    "getent_hosts": {"available": False},
                    "nslookup": {"available": False},
                    "ping": {"available": False},
                    "comparison": {"system_getent_status": "NOT_AVAILABLE"},
                },
            }

            def fake_run(command, **kwargs):
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": "PASS",
                            "message": "ok",
                            "request_debug": api_request_debug,
                        }
                    )
                    + "\n",
                    stderr="",
                )

            with patch("tools.scenario_runner.executors.subprocess.run", side_effect=fake_run):
                outcome = executor.execute(run_context, scenario, scenario.steps[0])

        self.assertEqual(outcome.step_result.status, StepStatus.PASS)
        self.assertEqual(outcome.step_result.details["api_request_debug"], api_request_debug)
        self.assertEqual(outcome.journal_details["api_request_debug"], api_request_debug)

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

    @staticmethod
    def _run_context(root: Path) -> RunContext:
        run_state_dir = root / ".codex-qa" / "runs" / "test-run"
        artifact_dir = root / "artifacts" / "agent" / "api-error-mapping-test-run"
        return RunContext(
            run_id="test-run",
            workspace_root=root,
            scenario_path=root / "scenario.md",
            scenario_slug="api-error-mapping",
            scenario_name="API Error Mapping",
            parsed_plans_dir=root / ".codex-qa" / "parsed-plans",
            compiled_plan_path=root / ".codex-qa" / "parsed-plans" / "plan.json",
            runs_root_dir=root / ".codex-qa" / "runs",
            run_state_dir=run_state_dir,
            artifacts_root_dir=root / "artifacts" / "agent",
            artifact_dir=artifact_dir,
            started_at="2026-04-21T00:00:00+00:00",
        )


class _InspectableApiStepExecutor(ApiStepExecutor):
    def __init__(self, workspace_root: Path) -> None:
        super().__init__(workspace_root=workspace_root, interpolator=PlaceholderInterpolator())

    def parse_tool_payload_for_test(self, stdout: str, stderr: str, returncode: int) -> dict:
        return self._parse_tool_payload(stdout, stderr, returncode)

    def invoke_cli_for_test(self, env_path: Path, step_file: Path) -> dict:
        return self._invoke_cli(env_path, step_file)


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
