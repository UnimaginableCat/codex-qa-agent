from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.scenario_runner.cli import main as cli_main
from tools.scenario_runner.artifacts import write_context_json, write_summary_json
from tools.scenario_runner.executors import StepExecutionOutcome
from tools.scenario_runner.models import (
    ApiStepDefinition,
    RunContext,
    ScenarioDefinition,
    ScenarioExecutionSummary,
    ScenarioStep,
    ScenarioStepType,
    StepExecutionResult,
)
from tools.scenario_runner.preflight import PreflightCheckResult, PreflightResult
from tools.scenario_runner.services import ScenarioRunnerService


class ScenarioRunnerFinalizationTests(unittest.TestCase):
    def test_pass_only_final_status_is_pass(self) -> None:
        summary = self._run_service_with_status(StepStatus.PASS)

        self.assertEqual(summary.final_status, StepStatus.PASS)

    def test_fail_present_final_status_is_fail(self) -> None:
        summary = self._run_service_with_status(StepStatus.FAIL)

        self.assertEqual(summary.final_status, StepStatus.FAIL)

    def test_blocked_present_without_error_final_status_is_blocked(self) -> None:
        summary = self._run_service_with_status(StepStatus.BLOCKED)

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)

    def test_error_present_final_status_is_error(self) -> None:
        summary = self._run_service_with_status(StepStatus.ERROR)

        self.assertEqual(summary.final_status, StepStatus.ERROR)

    def test_report_generation_exception_upgrades_final_status_to_error(self) -> None:
        with TemporaryDirectory() as tmp:
            service = _ReportFailingScenarioRunnerService(
                step_executor_factory=_FakeStepExecutorFactory([self._step_outcome(StepStatus.PASS)]),
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._scenario(Path(tmp), with_step=True), workspace_root=Path(tmp))
            persisted_summary = json.loads((summary.run_state_dir / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(summary.final_status, StepStatus.ERROR)
        self.assertEqual(persisted_summary["final_status"], StepStatus.ERROR.value)
        self.assertTrue(any("report generation failed" in issue.lower() for issue in summary.tooling_issues))

    def test_artifact_persistence_exception_upgrades_final_status_to_error(self) -> None:
        with TemporaryDirectory() as tmp:
            service = ScenarioRunnerService(
                step_executor_factory=_FakeStepExecutorFactory(exception=OSError("artifact write failed")),
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._scenario(Path(tmp), with_step=True), workspace_root=Path(tmp))
            persisted_summary = json.loads((summary.run_state_dir / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(summary.final_status, StepStatus.ERROR)
        self.assertEqual(persisted_summary["final_status"], StepStatus.ERROR.value)
        self.assertIn("artifact write failed", summary.steps[0].message)

    def test_summary_persistence_exception_upgrades_final_status_to_error(self) -> None:
        with TemporaryDirectory() as tmp:
            service = ScenarioRunnerService(
                step_executor_factory=_FakeStepExecutorFactory([self._step_outcome(StepStatus.PASS)]),
                preflight_checker=_PassingPreflightChecker(),
            )

            with patch("tools.scenario_runner.services.write_summary_json", side_effect=OSError("summary denied")):
                summary = service.run(self._scenario(Path(tmp), with_step=True), workspace_root=Path(tmp))

        self.assertEqual(summary.final_status, StepStatus.ERROR)
        self.assertTrue(any("summary persistence failed" in issue.lower() for issue in summary.tooling_issues))

    def test_summary_report_and_cli_final_status_are_consistent(self) -> None:
        scenario_text = "\n".join(
            [
                "# Scenario: CLI Consistency",
                "",
                "## Project",
                "code/demo-project",
                "",
                "## Environment",
                "env/demo.env",
                "",
                "## Steps",
                "",
                "### Step 1",
                "Type: api",
                "Name: smoke",
                "Method: GET",
                "Path: /smoke",
            ]
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_cli_workspace(root)
            scenario_path = root / "scenario.md"
            scenario_path.write_text(scenario_text, encoding="utf-8")
            previous_cwd = Path.cwd()
            output = io.StringIO()
            try:
                os.chdir(root)
                with patch("tools.scenario_runner.preflight.importlib.util.find_spec", return_value=object()):
                    with redirect_stdout(output):
                        exit_code = cli_main(["--scenario", str(scenario_path)])
            finally:
                os.chdir(previous_cwd)

            cli_payload = json.loads(output.getvalue())
            summary_path = Path(cli_payload["run_state_dir"]) / "summary.json"
            report_path = Path(cli_payload["report_path"])
            persisted_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            report_content = report_path.read_text(encoding="utf-8")
            bundle_summary_path = Path(cli_payload["artifact_dir"]) / "summary.json"
            bundle_manifest_path = Path(cli_payload["artifact_dir"]) / "manifest.json"
            bundle_summary_exists = bundle_summary_path.exists()
            bundle_manifest_exists = bundle_manifest_path.exists()

        self.assertEqual(exit_code, 0)
        self.assertEqual(cli_payload["final_status"], StepStatus.PASS.value)
        self.assertEqual(persisted_summary["final_status"], cli_payload["final_status"])
        self.assertTrue(bundle_summary_exists)
        self.assertTrue(bundle_manifest_exists)
        self.assertIn(f"- Final status: `{cli_payload['final_status']}`", report_content)

    def test_run_bundle_contains_state_plan_journal_report_and_steps(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ScenarioRunnerService(
                step_executor_factory=_FakeStepExecutorFactory([self._step_outcome(StepStatus.PASS)]),
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._scenario(root, with_step=True), workspace_root=root)
            bundle_dir = summary.artifact_dir
            manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
            bundle_context_exists = (bundle_dir / "context.json").exists()
            bundle_summary_exists = (bundle_dir / "summary.json").exists()
            bundle_journal_exists = (bundle_dir / "journal.jsonl").exists()
            bundle_plan_exists = (bundle_dir / "compiled-plan.json").exists()
            bundle_report_exists = (bundle_dir / "report.md").exists()
            bundle_summary_content = (bundle_dir / "summary.json").read_text(encoding="utf-8")

        self.assertEqual(manifest["run_id"], summary.run_id)
        self.assertEqual(Path(manifest["artifact_dir"]), bundle_dir)
        self.assertTrue(bundle_context_exists)
        self.assertTrue(bundle_summary_exists)
        self.assertTrue(bundle_journal_exists)
        self.assertTrue(bundle_plan_exists)
        self.assertTrue(bundle_report_exists)
        self.assertTrue(bundle_summary_content)
        self.assertEqual(
            Path(manifest["bundle"]["summary_path"]),
            bundle_dir / "summary.json",
        )
        self.assertEqual(
            Path(manifest["legacy_run_state"]["summary_path"]),
            summary.run_state_dir / "summary.json",
        )

    def test_context_and_summary_omit_network_debug_details(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_context = self._run_context_with_network_debug(root)
            summary = ScenarioExecutionSummary(
                scenario="Demo Scenario",
                project="demo-project",
                environment="env/demo.env",
                run_id=run_context.run_id,
                scenario_path=run_context.scenario_path,
                final_status=StepStatus.PASS,
                message="ok",
                run_state_dir=run_context.run_state_dir,
                artifact_dir=run_context.artifact_dir,
                started_at=run_context.started_at,
                finished_at=run_context.started_at,
                steps=list(run_context.step_results),
            )

            context_path = write_context_json(run_context)
            summary_path = write_summary_json(run_context, summary)

            context_payload = json.loads(context_path.read_text(encoding="utf-8"))
            summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))

        for payload in (context_payload, summary_payload):
            serialized = json.dumps(payload)
            self.assertNotIn("api_request_debug", serialized)
            self.assertNotIn("request_debug", serialized)
            self.assertNotIn("dns_precheck", serialized)
            self.assertNotIn("resolver_debug", serialized)
            self.assertNotIn("HTTP_PROXY", serialized)
            self.assertNotIn("HTTPS_PROXY", serialized)
            self.assertNotIn("NO_PROXY", serialized)
            self.assertNotIn("REQUESTS_CA_BUNDLE", serialized)
            self.assertNotIn("SSL_CERT_FILE", serialized)
            self.assertIn("capture_keys", serialized)
            self.assertIn("interpreter_path", serialized)

    def _run_service_with_status(self, status: StepStatus):
        with TemporaryDirectory() as tmp:
            service = ScenarioRunnerService(
                step_executor_factory=_FakeStepExecutorFactory([self._step_outcome(status)]),
                preflight_checker=_PassingPreflightChecker(),
            )
            return service.run(self._scenario(Path(tmp), with_step=True), workspace_root=Path(tmp))

    @staticmethod
    def _scenario(root: Path, with_step: bool) -> ScenarioDefinition:
        steps = [
            ScenarioStep(
                step_id="step-1",
                step_number=1,
                title="Step 1",
                step_type=ScenarioStepType.API,
                api=ApiStepDefinition(method="GET", path="/demo"),
            )
        ] if with_step else []
        return ScenarioDefinition(
            scenario_path=root / "scenario.md",
            scenario_slug="demo-scenario",
            scenario_name="Demo Scenario",
            project="demo-project",
            environment="env/demo.env",
            steps=steps,
        )

    @staticmethod
    def _step_outcome(status: StepStatus) -> StepExecutionOutcome:
        return StepExecutionOutcome(
            step_result=StepExecutionResult(
                step_id="step-1",
                step_number=1,
                step_type=ScenarioStepType.API,
                status=status,
                message=f"Step ended with {status.value}",
            ),
            tool_payload=None,
        )

    @staticmethod
    def _prepare_cli_workspace(root: Path) -> None:
        (root / "code" / "demo-project").mkdir(parents=True)
        (root / "env").mkdir()
        (root / "env" / "demo.env").write_text("API_BASE_URL=http://localhost\n", encoding="utf-8")
        api_tool = root / "tools" / "api" / "run_request.py"
        api_tool.parent.mkdir(parents=True)
        api_tool.write_text(
            "import json\n"
            "print(json.dumps({'status': 'PASS', 'message': 'ok', "
            "'response': {'http_status': 200, 'body': {'ok': True}}}))\n",
            encoding="utf-8",
        )

    @staticmethod
    def _run_context_with_network_debug(root: Path) -> RunContext:
        run_state_dir = root / ".codex-qa" / "runs" / "test-run"
        artifact_dir = root / "artifacts" / "agent" / "test-run"
        run_state_dir.mkdir(parents=True)
        artifact_dir.mkdir(parents=True)
        return RunContext(
            run_id="test-run",
            workspace_root=root,
            scenario_path=root / "scenario.md",
            scenario_slug="demo-scenario",
            scenario_name="Demo Scenario",
            parsed_plans_dir=root / ".codex-qa" / "parsed-plans",
            compiled_plan_path=root / ".codex-qa" / "parsed-plans" / "demo-scenario.json",
            runs_root_dir=root / ".codex-qa" / "runs",
            run_state_dir=run_state_dir,
            artifacts_root_dir=root / "artifacts" / "agent",
            artifact_dir=artifact_dir,
            started_at="2026-04-21T00:00:00+00:00",
            step_results=[
                StepExecutionResult(
                    step_id="step-1",
                    step_number=1,
                    step_type=ScenarioStepType.API,
                    status=StepStatus.PASS,
                    message="ok",
                    details={
                        "capture_keys": ["id"],
                        "tool_debug": {
                            "interpreter_path": "python",
                            "HTTP_PROXY": "http://proxy.local:8080",
                            "HTTPS_PROXY": "https://proxy.local:8443",
                            "NO_PROXY": "localhost",
                            "REQUESTS_CA_BUNDLE": "/tmp/ca.pem",
                            "SSL_CERT_FILE": "/tmp/ssl.pem",
                        },
                        "api_request_debug": {
                            "final_url_value": "https://app2.101-group.ru/api/demo",
                            "hostname_value": "app2.101-group.ru",
                            "dns_precheck": {"getaddrinfo": {"status": "PASS"}},
                            "resolver_debug": {"getent_hosts": {"status": "PASS"}},
                        },
                    },
                )
            ],
        )


class _FakeStepExecutorFactory:
    def __init__(
        self,
        outcomes: list[StepExecutionOutcome] | None = None,
        exception: Exception | None = None,
    ) -> None:
        self._outcomes = list(outcomes or [])
        self._exception = exception

    def create(self, step: ScenarioStep, workspace_root: Path) -> "_FakeStepExecutorFactory":
        return self

    def execute(
        self,
        run_context,
        scenario_definition,
        step: ScenarioStep,
    ) -> StepExecutionOutcome:
        if self._exception is not None:
            raise self._exception
        return self._outcomes.pop(0)


class _ReportFailingScenarioRunnerService(ScenarioRunnerService):
    @staticmethod
    def _build_report(run_context, scenario_definition, report_path):
        raise RuntimeError("report renderer crashed")


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
