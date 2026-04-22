"""Pause state projections for resumable guided runs."""

from __future__ import annotations

from tools.common.statuses import StepStatus

from ..domain.guided import ContinuationPolicy, GuidedDiagnostic
from ..domain.manual import AvailableOperatorAction, OperatorActionType, ResumeStrategy
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
    if _decision_already_resolved(state, candidate):
        return None

    resume_from_step_index = _resolve_resume_step_index(state, candidate)
    if resume_from_step_index is None:
        return None

    resume_step = state.scenario_definition.steps[resume_from_step_index]
    pause_id = f"pause-{state.run_context.run_id}"
    available_operator_actions = _build_available_operator_actions(
        state=state,
        diagnostic=candidate,
        resume_from_step_index=resume_from_step_index,
    )
    if not available_operator_actions:
        return None
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
        available_operator_actions=available_operator_actions,
        recommended_operator_action_id=_recommended_operator_action_id(available_operator_actions),
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


def _build_available_operator_actions(
    *,
    state: ExecutionProjectionState,
    diagnostic: GuidedDiagnostic,
    resume_from_step_index: int,
) -> tuple[AvailableOperatorAction, ...]:
    if diagnostic.issue_code == "deferred_capture_blocked":
        blocked_step_index = None if diagnostic.step is None else _step_index_by_id(state, diagnostic.step.step_id)
        if blocked_step_index is None or diagnostic.step is None:
            return ()
        return (
            AvailableOperatorAction(
                action_id="continue_if_fixed",
                action_type=OperatorActionType.CONTINUE_IF_FIXED,
                title="Continue after fixing producer",
                description="Retry the producer step and continue the run once the missing capture can be produced.",
                resume_strategy=ResumeStrategy.RETRY_FROM_STEP,
                target_step_id=state.scenario_definition.steps[resume_from_step_index].step_id,
                target_step_index=resume_from_step_index,
                recommended=True,
                details={"producer_step_id": state.scenario_definition.steps[resume_from_step_index].step_id},
            ),
            AvailableOperatorAction(
                action_id="skip_step",
                action_type=OperatorActionType.SKIP_STEP,
                title="Skip blocked step",
                description="Keep the blocked downstream step as evidence and continue from the next step.",
                resume_strategy=ResumeStrategy.CONTINUE_FROM_NEXT_STEP,
                target_step_id=diagnostic.step.step_id,
                target_step_index=blocked_step_index,
            ),
            AvailableOperatorAction(
                action_id="abort_run",
                action_type=OperatorActionType.ABORT_RUN,
                title="Abort run",
                description="Stop the paused run without attempting further execution.",
                resume_strategy=ResumeStrategy.ABORT,
                recommended=False,
            ),
        )

    if diagnostic.step is None:
        return ()

    decision_step_index = _step_index_by_id(state, diagnostic.step.step_id)
    if decision_step_index is None:
        return ()

    primary_action = (
        AvailableOperatorAction(
            action_id="continue_if_fixed",
            action_type=OperatorActionType.CONTINUE_IF_FIXED,
            title="Continue after external fix",
            description="Resume from the affected step after the external issue has been fixed.",
            resume_strategy=ResumeStrategy.RETRY_FROM_STEP,
            target_step_id=diagnostic.step.step_id,
            target_step_index=decision_step_index,
            recommended=True,
        )
        if diagnostic.continuation_policy == ContinuationPolicy.WAIT_FOR_DECISION
        else AvailableOperatorAction(
            action_id="retry_from_anchor",
            action_type=OperatorActionType.RETRY_FROM_ANCHOR,
            title="Retry affected step",
            description="Retry execution from the affected step and continue the scenario from there.",
            resume_strategy=ResumeStrategy.RETRY_FROM_STEP,
            target_step_id=diagnostic.step.step_id,
            target_step_index=decision_step_index,
            recommended=True,
        )
    )
    return (
        primary_action,
        AvailableOperatorAction(
            action_id="skip_step",
            action_type=OperatorActionType.SKIP_STEP,
            title="Skip current step",
            description="Keep the current step outcome as evidence and continue from the next scenario step.",
            resume_strategy=ResumeStrategy.CONTINUE_FROM_NEXT_STEP,
            target_step_id=diagnostic.step.step_id,
            target_step_index=decision_step_index,
        ),
        AvailableOperatorAction(
            action_id="abort_run",
            action_type=OperatorActionType.ABORT_RUN,
            title="Abort run",
            description="Stop the paused run without attempting further execution.",
            resume_strategy=ResumeStrategy.ABORT,
        ),
    )


def _recommended_operator_action_id(
    actions: tuple[AvailableOperatorAction, ...],
) -> str | None:
    for action in actions:
        if action.recommended:
            return action.action_id
    return None


def _decision_already_resolved(
    state: ExecutionProjectionState,
    diagnostic: GuidedDiagnostic,
) -> bool:
    if state.decision_resolution is None or diagnostic.decision_point is None:
        return False
    if state.decision_resolution.decision_point_id != diagnostic.decision_point.decision_id:
        return False
    return state.decision_resolution.selected_action.action_type in {
        OperatorActionType.SKIP_STEP,
        OperatorActionType.ABORT_RUN,
    }


def _build_session_snapshot(state: ExecutionProjectionState) -> dict:
    return {
        "scenario_definition": state.scenario_definition.to_dict(),
        "run_mode": state.run_mode.value,
        "run_context": state.run_context.to_dict(),
        "run_state": None if state.run_state is None else state.run_state.to_dict(),
        "tooling_issues": [issue.to_dict() for issue in state.tooling_issues],
        "compile_outcomes": [outcome.to_dict() for outcome in state.compile_outcomes],
        "compile_checks": list(state.compile_checks),
        "preflight_outcomes": [outcome.to_dict() for outcome in state.preflight_outcomes],
        "preflight_checks": list(state.preflight_checks),
        "execution_events": [event.to_dict() for event in state.execution_events],
    }
