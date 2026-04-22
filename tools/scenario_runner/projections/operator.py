"""Operator-facing read models for guided/manual scenario runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe

from ..domain.manual import RunMode
from ..domain.models import ScenarioExecutionSummary
from ..domain.pause import PauseState


@dataclass(frozen=True, slots=True)
class OperatorGuidanceProjection:
    run_id: str
    run_mode: RunMode
    continuation_state: str
    final_status: str
    message: str
    resumable: bool
    pause_state_path: Path | None = None
    resume_token: dict[str, Any] | None = None
    active_decision_point: dict[str, Any] | None = None
    active_diagnostic: dict[str, Any] | None = None
    available_actions: list[dict[str, Any]] = field(default_factory=list)
    recommended_action_id: str | None = None
    required_inputs: list[dict[str, Any]] = field(default_factory=list)
    resume_instructions: list[str] = field(default_factory=list)
    run_termination: dict[str, Any] | None = None
    report_path: Path | None = None
    summary_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "run_id": self.run_id,
                "run_mode": self.run_mode.value,
                "continuation_state": self.continuation_state,
                "final_status": self.final_status,
                "message": self.message,
                "resumable": self.resumable,
                "pause_state_path": self.pause_state_path,
                "resume_token": self.resume_token,
                "active_decision_point": self.active_decision_point,
                "active_diagnostic": self.active_diagnostic,
                "available_actions": self.available_actions,
                "recommended_action_id": self.recommended_action_id,
                "required_inputs": self.required_inputs,
                "resume_instructions": self.resume_instructions,
                "run_termination": self.run_termination,
                "report_path": self.report_path,
                "summary_path": self.summary_path,
            }
        )


def build_operator_guidance_from_summary(
    summary: ScenarioExecutionSummary,
    *,
    run_mode: RunMode,
) -> OperatorGuidanceProjection:
    pause_state_path = summary.pause_state_path
    active_diagnostic = None if summary.guided_stop_reason is None else summary.guided_stop_reason.to_dict()
    active_decision_point = (
        None
        if summary.guided_stop_reason is None or summary.guided_stop_reason.decision_point is None
        else summary.guided_stop_reason.decision_point.to_dict()
    )
    return OperatorGuidanceProjection(
        run_id=summary.run_id,
        run_mode=run_mode,
        continuation_state=summary.continuation_state.value,
        final_status=summary.final_status.value,
        message=summary.message,
        resumable=summary.resumable,
        pause_state_path=pause_state_path,
        resume_token=None if summary.resume_token is None else summary.resume_token.to_dict(),
        active_decision_point=active_decision_point,
        active_diagnostic=active_diagnostic,
        available_actions=[action.to_dict() for action in summary.available_operator_actions],
        recommended_action_id=_recommended_action_id([action.to_dict() for action in summary.available_operator_actions]),
        required_inputs=_required_inputs(summary.resumable),
        resume_instructions=_resume_instructions(pause_state_path, summary.resumable),
        run_termination=summary.details.get("run_termination"),
        report_path=summary.report_path,
        summary_path=summary.run_state_dir / "summary.json",
    )


def build_operator_guidance_from_pause_state(
    pause_state: PauseState,
    *,
    run_mode: RunMode,
) -> OperatorGuidanceProjection:
    diagnostic_snapshot = dict(pause_state.diagnostic_snapshot)
    active_decision_point = diagnostic_snapshot.get("decision_point")
    if not isinstance(active_decision_point, dict):
        active_decision_point = None
    actions = [action.to_dict() for action in pause_state.available_operator_actions]
    return OperatorGuidanceProjection(
        run_id=pause_state.run_id,
        run_mode=run_mode,
        continuation_state="paused" if pause_state.active else "terminal",
        final_status=pause_state.status.value,
        message=diagnostic_snapshot.get("summary", "Paused run is waiting for operator action."),
        resumable=pause_state.resumable,
        pause_state_path=pause_state.pause_state_path,
        resume_token=pause_state.resume_token.to_dict(),
        active_decision_point=active_decision_point,
        active_diagnostic=diagnostic_snapshot or None,
        available_actions=actions,
        recommended_action_id=pause_state.recommended_operator_action_id or _recommended_action_id(actions),
        required_inputs=_required_inputs(pause_state.resumable),
        resume_instructions=_resume_instructions(pause_state.pause_state_path, pause_state.resumable),
        run_termination={
            "kind": "paused" if pause_state.active else "resumed",
            "reason": {
                "code": "paused_waiting_for_decision",
                "message": "Scenario paused while waiting for an operator decision.",
                "source": "operator",
                "phase": "finalization",
                "details": {
                    "decision_point_id": pause_state.decision_point_id,
                    "diagnostic_id": pause_state.diagnostic_id,
                },
            },
            "outcome_status": pause_state.status.value,
            "terminal": not pause_state.active,
        },
        report_path=None,
        summary_path=pause_state.workspace_root / ".codex-qa" / "runs" / pause_state.run_id / "summary.json",
    )


def _recommended_action_id(actions: list[dict[str, Any]]) -> str | None:
    for action in actions:
        if action.get("recommended"):
            return str(action.get("action_id", "")).strip() or None
    return None


def _required_inputs(resumable: bool) -> list[dict[str, Any]]:
    if not resumable:
        return []
    return [
        {
            "name": "action_id",
            "source": "available_actions[].action_id",
            "description": "Select one available operator action and pass it to --action.",
        }
    ]


def _resume_instructions(pause_state_path: Path | None, resumable: bool) -> list[str]:
    if not resumable or pause_state_path is None:
        return []
    return [
        "Inspect available_actions and choose an action_id.",
        f"Run: python -m tools.scenario_runner.cli --resume {pause_state_path} --action <action_id>",
    ]
