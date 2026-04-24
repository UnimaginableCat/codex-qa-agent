from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.reports.renderers import MarkdownReportRenderer
from tools.reports.services import ReportBuildService, ReportWriter
from tools.scenario_runner.domain.execution import (
    ExecutionEvent,
    ExecutionIssue,
    ExecutionIssueKind,
    ExecutionOutcome,
    ExecutionPhase,
    ScenarioRunLifecycleState,
    ScenarioRunState,
)
from tools.scenario_runner.domain.models import (
    ApiStepDefinition,
    RunContext,
    ScenarioDefinition,
    ScenarioExecutionSummary,
    ScenarioStep,
    ScenarioStepType,
    StepExecutionResult,
)
from tools.scenario_runner.projections.journal import build_journal_projection
from tools.scenario_runner.projections.models import ExecutionProjectionState
from tools.scenario_runner.projections.reporting import build_report_context
from tools.scenario_runner.projections.summary import build_summary_projection


class ScenarioProjectionTests(unittest.TestCase):
    def test_summary_projection_builds_read_model_from_execution_state(self) -> None:
        root = Path("D:/workspace")
        scenario = _scenario(root)
        run_context = _run_context(root)
        run_state = ScenarioRunState(
            run_id=run_context.run_id,
            scenario_name=scenario.scenario_name,
            scenario_path=scenario.scenario_path,
            lifecycle_state=ScenarioRunLifecycleState.FINALIZING,
        )
        projection_state = ExecutionProjectionState(
            scenario_definition=scenario,
            run_context=run_context,
            run_state=run_state,
            tooling_issues=(
                ExecutionIssue(
                    code="report_generation_failed",
                    message="report generation failed: renderer crashed",
                    phase=ExecutionPhase.REPORTING,
                    issue_type=ExecutionIssueKind.FINALIZATION,
                    outcome=StepStatus.ERROR,
                ),
            ),
            compile_outcomes=(
                ExecutionOutcome.from_status(
                    StepStatus.PASS,
                    "compile ok",
                    phase=ExecutionPhase.COMPILATION,
                ),
            ),
            compile_checks=({"name": "variables", "status": "PASS"},),
            preflight_outcomes=(
                ExecutionOutcome.from_status(
                    StepStatus.PASS,
                    "preflight ok",
                    phase=ExecutionPhase.PREFLIGHT,
                ),
            ),
            preflight_checks=({"name": "env", "status": "PASS"},),
            finalization_outcomes=(
                ExecutionOutcome.from_status(
                    StepStatus.ERROR,
                    "report generation failed: renderer crashed",
                    phase=ExecutionPhase.REPORTING,
                ),
            ),
        )

        summary = build_summary_projection(projection_state)

        self.assertEqual(summary.final_status, StepStatus.ERROR)
        self.assertEqual(summary.message, "Scenario finalization failed with status ERROR.")
        self.assertEqual(summary.details["compile_statuses"], [StepStatus.PASS.value])
        self.assertEqual(summary.details["preflight_statuses"], [StepStatus.PASS.value])
        self.assertEqual(summary.details["finalization_statuses"], [StepStatus.ERROR.value])
        self.assertTrue(any("report_generation_failed" in issue for issue in summary.tooling_issues))

    def test_journal_projection_appends_run_finished_event(self) -> None:
        root = Path("D:/workspace")
        scenario = _scenario(root)
        run_context = _run_context(root)
        run_state = ScenarioRunState(
            run_id=run_context.run_id,
            scenario_name=scenario.scenario_name,
            scenario_path=scenario.scenario_path,
            lifecycle_state=ScenarioRunLifecycleState.FINALIZING,
        )
        run_initialized = ExecutionEvent.create(
            event_type="run_initialized",
            run_state=run_state,
            phase=ExecutionPhase.RUN_INITIALIZATION,
            payload={"started_at": run_context.started_at},
        )
        step_completed = ExecutionEvent.create(
            event_type="step_completed",
            run_state=run_state,
            phase=ExecutionPhase.STEP_EXECUTION,
            outcome=ExecutionOutcome.from_status(
                StepStatus.PASS,
                "ok",
                phase=ExecutionPhase.STEP_EXECUTION,
            ),
            payload={"message": "ok"},
        )
        projection_state = ExecutionProjectionState(
            scenario_definition=scenario,
            run_context=run_context,
            run_state=run_state,
            execution_events=(run_initialized, step_completed),
            report_path=run_context.artifact_dir / "report.md",
        )
        summary = ScenarioExecutionSummary(
            scenario=scenario.scenario_name,
            project=scenario.project,
            environment=scenario.environment,
            run_id=run_context.run_id,
            scenario_path=scenario.scenario_path,
            final_status=StepStatus.PASS,
            message="Scenario execution completed.",
            run_state_dir=run_context.run_state_dir,
            artifact_dir=run_context.artifact_dir,
            report_path=projection_state.report_path,
            started_at=run_context.started_at,
            finished_at=run_context.started_at,
            steps=list(run_context.step_results),
        )

        journal = build_journal_projection(projection_state, summary, include_run_finished=True)

        self.assertEqual([event.event_type for event in journal.entries], ["run_initialized", "step_completed", "run_finished"])
        self.assertEqual(journal.entries[-1].payload["executed_step_count"], 1)
        self.assertEqual(journal.entries[-1].payload["report_path"], str(run_context.artifact_dir / "report.md"))

    def test_report_context_projection_renders_without_summary_loader(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = _summary(root)
            context = build_report_context(summary)
            output_path = root / "report.md"
            service = ReportBuildService(
                summary_loader=_ExplodingSummaryLoader(),
                renderer=MarkdownReportRenderer(),
                writer=ReportWriter(),
            )

            written_path = service.build_from_context(context=context, output_path=output_path)
            report_content = output_path.read_text(encoding="utf-8")

        self.assertEqual(written_path, output_path)
        self.assertIn("# QA Report: Demo Scenario", report_content)
        self.assertIn("- Final status: `PASS`", report_content)
        self.assertIn("Scenario execution completed.", report_content)


class _ExplodingSummaryLoader:
    def load(self, summary_path: Path):
        raise AssertionError("summary loader should not be used when report context is projected directly")


def _scenario(root: Path) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_path=root / "scenario.md",
        scenario_slug="projection-demo",
        scenario_name="Demo Scenario",
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


def _run_context(root: Path) -> RunContext:
    return RunContext(
        run_id="run-123",
        workspace_root=root,
        scenario_path=root / "scenario.md",
        scenario_slug="projection-demo",
        scenario_name="Demo Scenario",
        parsed_plans_dir=root / ".codex-qa" / "parsed-plans",
        compiled_plan_path=root / ".codex-qa" / "parsed-plans" / "projection-demo.json",
        runs_root_dir=root / ".codex-qa" / "runs",
        run_state_dir=root / ".codex-qa" / "runs" / "run-123",
        artifacts_root_dir=root / "artifacts" / "agent" / "scenario-runs",
        artifact_dir=root / "artifacts" / "agent" / "scenario-runs" / "projection-demo-run-123",
        started_at="2026-04-22T10:00:00+00:00",
        variables={"run_id": "run-123", "project": "code/demo-project"},
        step_results=[
            StepExecutionResult(
                step_id="step-1",
                step_number=1,
                step_type=ScenarioStepType.API,
                status=StepStatus.PASS,
                message="ok",
            )
        ],
    )


def _summary(root: Path) -> ScenarioExecutionSummary:
    run_context = _run_context(root)
    return ScenarioExecutionSummary(
        scenario="Demo Scenario",
        project="code/demo-project",
        environment="env/demo.env",
        run_id=run_context.run_id,
        scenario_path=run_context.scenario_path,
        final_status=StepStatus.PASS,
        message="Scenario execution completed.",
        run_state_dir=run_context.run_state_dir,
        artifact_dir=run_context.artifact_dir,
        report_path=run_context.artifact_dir / "report.md",
        started_at=run_context.started_at,
        finished_at=run_context.started_at,
        steps=list(run_context.step_results),
        assumptions=["API is reachable."],
    )


if __name__ == "__main__":
    unittest.main()
