"""Report input projections derived from scenario execution summaries."""

from __future__ import annotations

from tools.common.statuses import StepStatus
from tools.reports.models import CheckResult, ReportContext, SummaryData

from ..domain.models import ScenarioExecutionSummary


def build_report_context(summary: ScenarioExecutionSummary) -> ReportContext:
    return ReportContext(
        project=summary.project,
        scenario=summary.scenario,
        summary=SummaryData(
            final_status=summary.final_status.value,
            notes=summary.build_notes(),
            checks=[
                CheckResult(
                    name=check["name"],
                    status=check["status"],
                    detail=check.get("detail"),
                )
                for check in summary.build_report_checks()
            ],
            executive_summary=summary.message,
            code_analysis_summary=(
                "Code analysis was used during this run." if summary.code_analysis_used else None
            ),
            blockers=[
                step.message for step in summary.steps if step.status in {StepStatus.BLOCKED, StepStatus.ERROR}
            ],
            assumptions=list(summary.assumptions),
            artifacts=summary.build_artifact_list(),
        ),
    )
