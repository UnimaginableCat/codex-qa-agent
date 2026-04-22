"""Journal projections for persisted execution event streams."""

from __future__ import annotations

from ..domain.execution import ExecutionEvent, ExecutionOutcome, ExecutionPhase
from ..domain.models import ScenarioExecutionSummary
from ..domain.pause import RunContinuationState
from .models import ExecutionProjectionState, JournalProjection


def build_journal_projection(
    state: ExecutionProjectionState,
    summary: ScenarioExecutionSummary,
    *,
    include_run_finished: bool = True,
) -> JournalProjection:
    entries = list(state.execution_events)

    if include_run_finished:
        event_type = (
            "run_paused"
            if summary.continuation_state == RunContinuationState.PAUSED
            else "run_finished"
        )
        entries.append(
            ExecutionEvent.create(
                event_type=event_type,
                run_state=state.run_state,
                phase=ExecutionPhase.FINALIZATION,
                outcome=ExecutionOutcome.from_status(
                    summary.final_status,
                    summary.message,
                    phase=ExecutionPhase.FINALIZATION,
                ),
                issue=state.tooling_issues[-1] if state.tooling_issues else None,
                payload={
                    "executed_step_count": state.executed_step_count,
                    "report_path": None if state.report_path is None else str(state.report_path),
                    "continuation_state": summary.continuation_state.value,
                    "resumable": summary.resumable,
                    "pause_state_path": None if summary.pause_state_path is None else str(summary.pause_state_path),
                    "resume_token": None if summary.resume_token is None else summary.resume_token.to_dict(),
                    "available_operator_actions": [
                        action.to_dict() for action in summary.available_operator_actions
                    ],
                    "decision_resolution": (
                        None
                        if summary.decision_resolution is None
                        else summary.decision_resolution.to_dict()
                    ),
                },
            )
        )

    return JournalProjection(entries=tuple(entries))
