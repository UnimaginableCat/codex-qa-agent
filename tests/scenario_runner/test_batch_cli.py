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
from tools.scenario_runner.batch import ScenarioBatchRunnerService
from tools.scenario_runner.batch_cli import main as batch_cli_main
from tools.scenario_runner.domain.manual import AvailableOperatorAction, OperatorActionType, ResumeStrategy, RunMode
from tools.scenario_runner.domain.models import ScenarioDefinition, ScenarioExecutionSummary
from tools.scenario_runner.domain.pause import ResumeToken, RunContinuationState


class ScenarioBatchRunnerServiceTests(unittest.TestCase):
    def test_auto_batch_executes_all_scenarios_and_writes_aggregate_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_dir = _prepare_scenario_dir(root, ["a.md", "nested/b.md"])
            parser = _FakeParser()
            runner = _FakeRunner(
                [
                    _build_summary(root, scenario_dir / "a.md", "run-001", StepStatus.PASS),
                    _build_summary(root, scenario_dir / "nested" / "b.md", "run-002", StepStatus.PASS),
                ]
            )

            result = ScenarioBatchRunnerService(parser=parser, runner_service=runner).run_scenario_dir(
                scenario_dir,
                workspace_root=root,
                run_mode=RunMode.AUTO,
            )
            summary_payload = json.loads(result.batch_summary.summary_path.read_text(encoding="utf-8"))
            report_content = result.batch_summary.report_path.read_text(encoding="utf-8")

        self.assertEqual(result.batch_summary.final_status, StepStatus.PASS)
        self.assertEqual(result.batch_summary.continuation_state, RunContinuationState.TERMINAL)
        self.assertEqual(result.batch_summary.scenario_count_total, 2)
        self.assertEqual(result.batch_summary.scenario_count_executed, 2)
        self.assertEqual(result.batch_summary.status_counts[StepStatus.PASS.value], 2)
        self.assertEqual(summary_payload["final_status"], StepStatus.PASS.value)
        self.assertEqual(summary_payload["scenario_count_remaining"], 0)
        self.assertIn("Scenario batch execution completed for 2 scenario(s).", report_content)
        self.assertIn("`a.md`", report_content)
        self.assertIn("`b.md`", report_content)

    def test_guided_batch_stops_on_paused_run_and_keeps_remaining_scenarios(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_dir = _prepare_scenario_dir(root, ["a.md", "b.md"])
            parser = _FakeParser()
            paused_summary = _build_summary(
                root,
                scenario_dir / "a.md",
                "run-010",
                StepStatus.BLOCKED,
                continuation_state=RunContinuationState.PAUSED,
                resumable=True,
            )
            runner = _FakeRunner([paused_summary])

            result = ScenarioBatchRunnerService(parser=parser, runner_service=runner).run_scenario_dir(
                scenario_dir,
                workspace_root=root,
                run_mode=RunMode.GUIDED,
            )
            summary_payload = json.loads(result.batch_summary.summary_path.read_text(encoding="utf-8"))

        self.assertEqual(result.batch_summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(result.batch_summary.continuation_state, RunContinuationState.PAUSED)
        self.assertTrue(result.batch_summary.resumable)
        self.assertEqual(result.batch_summary.scenario_count_executed, 1)
        self.assertEqual(result.batch_summary.scenario_count_remaining, 1)
        self.assertEqual([path.name for path in result.batch_summary.remaining_scenarios], ["b.md"])
        self.assertIsNotNone(result.operator_state)
        self.assertEqual(summary_payload["paused_run_id"], "run-010")
        self.assertEqual(summary_payload["scenario_count_remaining"], 1)


class ScenarioBatchCliTests(unittest.TestCase):
    def test_cli_returns_zero_and_operator_state_for_guided_pause(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_dir = self._prepare_scenario_dir(root)
            batch_summary = _build_batch_summary_payload(root, scenario_dir)
            paused_summary = _build_summary(
                root,
                scenario_dir / "a.md",
                "run-020",
                StepStatus.BLOCKED,
                continuation_state=RunContinuationState.PAUSED,
                resumable=True,
            )
            service_result = type(
                "BatchResult",
                (),
                {
                    "batch_summary": batch_summary,
                    "paused_summary": paused_summary,
                    "operator_state": type("OperatorState", (), {"to_dict": lambda self: {"run_id": "run-020"}})(),
                },
            )()
            output = io.StringIO()
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch("tools.scenario_runner.batch_cli.ScenarioBatchRunnerService") as service_cls:
                    service_cls.return_value.run_scenario_dir.return_value = service_result
                    with redirect_stdout(output):
                        exit_code = batch_cli_main(["--scenario-dir", str(scenario_dir)])
            finally:
                os.chdir(previous_cwd)
            payload = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertIn("batch_summary", payload)
        self.assertIn("summary", payload)
        self.assertIn("operator_state", payload)
        self.assertEqual(payload["operator_state"]["run_id"], "run-020")

    @staticmethod
    def _prepare_scenario_dir(root: Path) -> Path:
        return _prepare_scenario_dir(root, ["a.md"])


class _FakeParser:
    def parse(self, scenario_path: Path) -> ScenarioDefinition:
        return ScenarioDefinition(
            scenario_path=scenario_path,
            scenario_slug=scenario_path.stem,
            scenario_name=scenario_path.stem,
            project="code/demo-project",
            environment="env/demo.env",
        )


class _FakeRunner:
    def __init__(self, summaries: list[ScenarioExecutionSummary]) -> None:
        self._summaries = list(summaries)

    def run(
        self,
        scenario_definition: ScenarioDefinition,
        workspace_root: Path | None = None,
        *,
        run_mode: RunMode = RunMode.AUTO,
    ) -> ScenarioExecutionSummary:
        del scenario_definition, workspace_root, run_mode
        return self._summaries.pop(0)


def _build_summary(
    root: Path,
    scenario_path: Path,
    run_id: str,
    final_status: StepStatus,
    *,
    continuation_state: RunContinuationState = RunContinuationState.TERMINAL,
    resumable: bool = False,
) -> ScenarioExecutionSummary:
    artifact_dir = root / "artifacts" / "agent" / "scenario-runs" / run_id
    run_state_dir = root / ".codex-qa" / "runs" / run_id
    pause_state_path = artifact_dir / "pause-state.json" if resumable else None
    return ScenarioExecutionSummary(
        scenario=scenario_path.stem,
        project="code/demo-project",
        environment="env/demo.env",
        run_id=run_id,
        scenario_path=scenario_path,
        final_status=final_status,
        message=f"{scenario_path.stem} -> {final_status.value}",
        run_state_dir=run_state_dir,
        artifact_dir=artifact_dir,
        started_at="2026-04-28T00:00:00+00:00",
        finished_at="2026-04-28T00:01:00+00:00",
        report_path=artifact_dir / "report.md",
        continuation_state=continuation_state,
        resumable=resumable,
        resume_token=ResumeToken(run_id=run_id, pause_id="pause-1") if resumable else None,
        pause_state_path=pause_state_path,
        available_operator_actions=(
            [
                AvailableOperatorAction(
                    action_id="continue_if_fixed",
                    action_type=OperatorActionType.CONTINUE_IF_FIXED,
                    title="Continue",
                    description="Continue after fixing the issue.",
                    resume_strategy=ResumeStrategy.RETRY_FROM_STEP,
                    recommended=True,
                )
            ]
            if resumable
            else []
        ),
        details={"run_termination": {"kind": "paused" if resumable else "completed"}},
    )


def _build_batch_summary_payload(root: Path, scenario_dir: Path):
    artifact_dir = root / "artifacts" / "agent" / "scenario-batches" / "batch-001"
    return type(
        "BatchSummary",
        (),
        {
            "final_status": StepStatus.BLOCKED,
            "resumable": True,
            "to_dict": lambda self: {
                "batch_id": "batch-001",
                "scenario_dir": str(scenario_dir),
                "artifact_dir": str(artifact_dir),
                "final_status": StepStatus.BLOCKED.value,
            },
        },
    )()


def _prepare_scenario_dir(root: Path, relative_paths: list[str]) -> Path:
    scenario_dir = root / "scenarios" / "generated" / "suite"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    for relative_path in relative_paths:
        path = scenario_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Scenario: demo\n", encoding="utf-8")
    return scenario_dir


if __name__ == "__main__":
    unittest.main()
