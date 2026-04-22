"""Typed operator-action resolution for guided manual continuation."""

from __future__ import annotations

from tools.common.errors import ValidationError

from ..domain.execution import utc_now_iso
from ..domain.guided import ContinuationPolicy
from ..domain.manual import DecisionResolution, OperatorActionSelection, OperatorActionType
from ..domain.pause import PauseState


_POLICY_ACTIONS = {
    ContinuationPolicy.WAIT_FOR_DECISION: {
        OperatorActionType.CONTINUE_IF_FIXED,
        OperatorActionType.SKIP_STEP,
        OperatorActionType.ABORT_RUN,
    },
    ContinuationPolicy.RETRY_MANUALLY: {
        OperatorActionType.RETRY_FROM_ANCHOR,
        OperatorActionType.SKIP_STEP,
        OperatorActionType.ABORT_RUN,
    },
}


def resolve_operator_action_selection(
    pause_state: PauseState,
    selection: OperatorActionSelection | None = None,
) -> DecisionResolution:
    if not pause_state.available_operator_actions:
        raise ValidationError("Pause state does not expose operator actions for this decision point.")
    if not pause_state.decision_point_id:
        raise ValidationError("Pause state is missing decision point metadata.")

    selected_action = _find_selected_action(pause_state, selection)
    _validate_action_for_pause_state(pause_state, selection, selected_action)
    return DecisionResolution(
        decision_point_id=pause_state.decision_point_id,
        selected_action=selected_action,
        resume_strategy=selected_action.resume_strategy,
        resolved_at=utc_now_iso(),
        details={
            "continuation_policy": pause_state.continuation_policy.value,
            "pause_id": pause_state.pause_id,
            "run_id": pause_state.run_id,
        },
    )


def _find_selected_action(
    pause_state: PauseState,
    selection: OperatorActionSelection | None,
):
    if selection is None:
        recommended_action_id = pause_state.recommended_operator_action_id
        if recommended_action_id:
            for action in pause_state.available_operator_actions:
                if action.action_id == recommended_action_id:
                    return action
        recommended_action = next(
            (action for action in pause_state.available_operator_actions if action.recommended),
            None,
        )
        if recommended_action is not None:
            return recommended_action
        return pause_state.available_operator_actions[0]

    return next(
        (
            action
            for action in pause_state.available_operator_actions
            if action.action_id == selection.action_id
        ),
        None,
    )


def _validate_action_for_pause_state(
    pause_state: PauseState,
    selection: OperatorActionSelection | None,
    selected_action,
) -> None:
    if selection is not None and selection.decision_point_id != pause_state.decision_point_id:
        raise ValidationError("Selected operator action does not match the paused decision point.")
    if selected_action is None:
        raise ValidationError("Selected operator action is not allowed for this paused decision point.")

    allowed_action_types = _POLICY_ACTIONS.get(pause_state.continuation_policy)
    if allowed_action_types is None:
        raise ValidationError(
            f"Continuation policy '{pause_state.continuation_policy.value}' does not allow operator continuation."
        )
    if selected_action.action_type not in allowed_action_types:
        raise ValidationError(
            f"Operator action '{selected_action.action_type.value}' is not allowed for continuation policy "
            f"'{pause_state.continuation_policy.value}'."
        )
    if selected_action.action_type != OperatorActionType.ABORT_RUN and not selected_action.target_step_id:
        raise ValidationError("Selected operator action is missing a continuation step target.")
