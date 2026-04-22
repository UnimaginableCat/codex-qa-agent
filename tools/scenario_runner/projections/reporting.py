"""Report input projections derived from scenario execution summaries."""

from __future__ import annotations

from tools.common.statuses import StepStatus
from tools.reports.models import (
    CheckResult,
    DecisionPointData,
    GuidedActionData,
    GuidedDiagnosticData,
    ReportContext,
    SummaryData,
)

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
            guided_diagnostics=[
                GuidedDiagnosticData(
                    diagnostic_id=diagnostic.diagnostic_id,
                    title=diagnostic.title,
                    summary=diagnostic.summary,
                    phase=None if diagnostic.phase is None else diagnostic.phase.value,
                    status=None if diagnostic.status is None else diagnostic.status.value,
                    continuation_policy=diagnostic.continuation_policy.value,
                    tags=[tag.value for tag in diagnostic.tags],
                    actions=[
                        GuidedActionData(
                            title=action.title,
                            description=action.description,
                            action_type=action.action_type.value,
                            recommended=action.recommended,
                        )
                        for action in diagnostic.actions
                    ],
                    decision_point=(
                        None
                        if diagnostic.decision_point is None
                        else DecisionPointData(
                            title=diagnostic.decision_point.title,
                            prompt=diagnostic.decision_point.prompt,
                            continuation_policy=diagnostic.decision_point.continuation_policy.value,
                            recommended_action_id=diagnostic.decision_point.recommended_action_id,
                        )
                    ),
                )
                for diagnostic in summary.guided_diagnostics
            ],
            guided_stop_reason=(
                None
                if summary.guided_stop_reason is None
                else GuidedDiagnosticData(
                    diagnostic_id=summary.guided_stop_reason.diagnostic_id,
                    title=summary.guided_stop_reason.title,
                    summary=summary.guided_stop_reason.summary,
                    phase=(
                        None
                        if summary.guided_stop_reason.phase is None
                        else summary.guided_stop_reason.phase.value
                    ),
                    status=(
                        None
                        if summary.guided_stop_reason.status is None
                        else summary.guided_stop_reason.status.value
                    ),
                    continuation_policy=summary.guided_stop_reason.continuation_policy.value,
                    tags=[tag.value for tag in summary.guided_stop_reason.tags],
                    actions=[
                        GuidedActionData(
                            title=action.title,
                            description=action.description,
                            action_type=action.action_type.value,
                            recommended=action.recommended,
                        )
                        for action in summary.guided_stop_reason.actions
                    ],
                    decision_point=(
                        None
                        if summary.guided_stop_reason.decision_point is None
                        else DecisionPointData(
                            title=summary.guided_stop_reason.decision_point.title,
                            prompt=summary.guided_stop_reason.decision_point.prompt,
                            continuation_policy=summary.guided_stop_reason.decision_point.continuation_policy.value,
                            recommended_action_id=summary.guided_stop_reason.decision_point.recommended_action_id,
                        )
                    ),
                )
            ),
            continuation_state=summary.continuation_state.value,
            resumable=summary.resumable,
            resume_token=None if summary.resume_token is None else summary.resume_token.to_dict(),
            pause_state_path=None if summary.pause_state_path is None else str(summary.pause_state_path),
            resumed_from_pause=summary.resumed_from_pause,
        ),
    )
