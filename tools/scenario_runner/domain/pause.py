"""Typed contracts for partial pause/resume workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus

if TYPE_CHECKING:
    from .guided import ContinuationPolicy


class RunContinuationState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    RESUMED = "resumed"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class ResumeToken:
    run_id: str
    pause_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "pause_id": self.pause_id}

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ResumeToken":
        return cls(
            run_id=str(payload.get("run_id", "")).strip(),
            pause_id=str(payload.get("pause_id", "")).strip(),
        )


@dataclass(frozen=True, slots=True)
class ResumeRequest:
    resume_token: ResumeToken
    selected_action_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resume_token": self.resume_token.to_dict(),
            "selected_action_id": self.selected_action_id,
        }


@dataclass(slots=True)
class PauseState:
    pause_id: str
    run_id: str
    scenario_path: Path
    scenario_slug: str
    scenario_name: str
    workspace_root: Path
    created_at: str
    continuation_policy: ContinuationPolicy
    resume_token: ResumeToken
    resume_from_step_index: int
    resume_from_step_id: str
    status: StepStatus
    decision_point_id: str | None = None
    diagnostic_id: str | None = None
    diagnostic_snapshot: dict[str, Any] = field(default_factory=dict)
    snapshot: dict[str, Any] = field(default_factory=dict)
    active: bool = True
    selected_action_id: str | None = None
    resumed_at: str | None = None
    pause_state_path: Path | None = None

    @property
    def resumable(self) -> bool:
        return self.active and bool(self.resume_from_step_id)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "pause_id": self.pause_id,
                "run_id": self.run_id,
                "scenario_path": self.scenario_path,
                "scenario_slug": self.scenario_slug,
                "scenario_name": self.scenario_name,
                "workspace_root": self.workspace_root,
                "created_at": self.created_at,
                "continuation_policy": self.continuation_policy.value,
                "resume_token": self.resume_token.to_dict(),
                "resume_from_step_index": self.resume_from_step_index,
                "resume_from_step_id": self.resume_from_step_id,
                "status": self.status.value,
                "decision_point_id": self.decision_point_id,
                "diagnostic_id": self.diagnostic_id,
                "diagnostic_snapshot": self.diagnostic_snapshot,
                "snapshot": self.snapshot,
                "active": self.active,
                "selected_action_id": self.selected_action_id,
                "resumed_at": self.resumed_at,
                "pause_state_path": self.pause_state_path,
                "resumable": self.resumable,
            }
        )

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "PauseState":
        from .guided import ContinuationPolicy

        continuation_policy_raw = str(payload.get("continuation_policy", "")).strip() or ContinuationPolicy.STOP_AND_FIX.value
        status_raw = str(payload.get("status", "")).strip() or StepStatus.BLOCKED.value
        pause_state_path_raw = payload.get("pause_state_path")
        return cls(
            pause_id=str(payload.get("pause_id", "")).strip(),
            run_id=str(payload.get("run_id", "")).strip(),
            scenario_path=Path(str(payload.get("scenario_path", ""))),
            scenario_slug=str(payload.get("scenario_slug", "")).strip(),
            scenario_name=str(payload.get("scenario_name", "")).strip(),
            workspace_root=Path(str(payload.get("workspace_root", ""))),
            created_at=str(payload.get("created_at", "")).strip(),
            continuation_policy=ContinuationPolicy(continuation_policy_raw),
            resume_token=ResumeToken.from_mapping(payload.get("resume_token") or {}),
            resume_from_step_index=int(payload.get("resume_from_step_index", 0)),
            resume_from_step_id=str(payload.get("resume_from_step_id", "")).strip(),
            status=StepStatus(status_raw),
            decision_point_id=(
                str(payload.get("decision_point_id", "")).strip() or None
            ),
            diagnostic_id=str(payload.get("diagnostic_id", "")).strip() or None,
            diagnostic_snapshot=dict(payload.get("diagnostic_snapshot") or {}),
            snapshot=dict(payload.get("snapshot") or {}),
            active=bool(payload.get("active", True)),
            selected_action_id=str(payload.get("selected_action_id", "")).strip() or None,
            resumed_at=str(payload.get("resumed_at", "")).strip() or None,
            pause_state_path=None if pause_state_path_raw in {None, ""} else Path(str(pause_state_path_raw)),
        )

    def mark_resumed(self, selected_action_id: str | None, resumed_at: str) -> None:
        self.active = False
        self.selected_action_id = selected_action_id
        self.resumed_at = resumed_at

    def set_path(self, path: Path) -> None:
        self.pause_state_path = path
