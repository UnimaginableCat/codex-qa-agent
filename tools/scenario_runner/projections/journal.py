"""Journal projections for persisted execution event streams."""

from __future__ import annotations

from ..domain.execution import ExecutionEvent, ExecutionOutcome, ExecutionPhase
from ..domain.models import ScenarioExecutionSummary
from .models import ExecutionProjectionState, JournalProjection


def build_journal_projection(
    state: ExecutionProjectionState,
    summary: ScenarioExecutionSummary,
    *,
    include_run_finished: bool = True,
) -> JournalProjection:
    entries = list(state.execution_events)

    if include_run_finished:
        entries.append(
            ExecutionEvent.create(
                event_type="run_finished",
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
                },
            )
        )

    return JournalProjection(entries=tuple(entries))
