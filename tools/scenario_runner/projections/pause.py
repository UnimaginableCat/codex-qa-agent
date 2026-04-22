"""Pause state projections for resumable guided runs."""

from __future__ import annotations

from typing import Iterable

from tools.common.statuses import StepStatus

from ..domain.guided import ContinuationPolicy, GuidedDiagnostic
from ..domain.pause import PauseState, ResumeToken
from ..domain.execution import utc_now_iso
from .guided import build_guided_projection
from .models import ExecutionProjectionState


_RESUMABLE_POLICIES = {
    ContinuationPolicy.WAIT_FOR_DECISION,
    ContinuationPolicy.RETRY_MANUALLY,
}


def build_pause_state(state: ExecutionProjectionState) -> PauseState | None:
    guided_projection = build_guided_projection(state)
    candidate = next(
        (
            diagnostic
            for diagnostic in guided_projection.diagnostics
            if diagnostic.decision_point is not None and diagnostic.continuation_policy in _RESUMABLE_POLICIES
        ),
        None,
    )
    if candidate is None:
        return None

    resume_from_step_index = _resolve_resume_step_index(state, candidate)
    if resume_from_step_index is None:
        return None

    resume_step = state.scenario_definition.steps[resume_from_step_index]
    pause_id = f"pause-{state.run_context.run_id}"
    return PauseState(
        pause_id=pause_id,
        run_id=state.run_context.run_id,
        scenario_path=state.scenario_definition.scenario_path,
        scenario_slug=state.scenario_definition.scenario_slug,
        scenario_name=state.scenario_definition.scenario_name,
        workspace_root=state.run_context.workspace_root,
        created_at=utc_now_iso(),
        continuation_policy=candidate.continuation_policy,
        resume_token=ResumeToken(run_id=state.run_context.run_id, pause_id=pause_id),
        resume_from_step_index=resume_from_step_index,
        resume_from_step_id=resume_step.step_id,
        status=candidate.status or StepStatus.BLOCKED,
        decision_point_id=None if candidate.decision_point is None else candidate.decision_point.decision_id,
        diagnostic_id=candidate.diagnostic_id,
        diagnostic_snapshot=candidate.to_dict(),
        snapshot=_build_session_snapshot(state),
    )


def _resolve_resume_step_index(
    state: ExecutionProjectionState,
    diagnostic: GuidedDiagnostic,
) -> int | None:
    if diagnostic.issue_code == "deferred_capture_blocked":
        producer_step_id = str(diagnostic.details.get("producer_step_id", "")).strip()
        if not producer_step_id:
            return None
        return _step_index_by_id(state, producer_step_id)

    if diagnostic.step is not None:
        return _step_index_by_id(state, diagnostic.step.step_id)

    return None


def _step_index_by_id(state: ExecutionProjectionState, step_id: str) -> int | None:
    for index, step in enumerate(state.scenario_definition.steps):
        if step.step_id == step_id:
            return index
    return None


def _build_session_snapshot(state: ExecutionProjectionState) -> dict:
    return {
        "scenario_definition": state.scenario_definition.to_dict(),
        "run_context": state.run_context.to_dict(),
        "run_state": None if state.run_state is None else state.run_state.to_dict(),
        "tooling_issues": [issue.to_dict() for issue in state.tooling_issues],
        "compile_outcomes": [outcome.to_dict() for outcome in state.compile_outcomes],
        "compile_checks": list(state.compile_checks),
        "preflight_outcomes": [outcome.to_dict() for outcome in state.preflight_outcomes],
        "preflight_checks": list(state.preflight_checks),
        "execution_events": [event.to_dict() for event in state.execution_events],
    }
