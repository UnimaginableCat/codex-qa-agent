"""Typed contracts for operator-driven guided continuation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from tools.common.json_safe import to_json_safe


class OperatorActionType(StrEnum):
    RETRY_FROM_ANCHOR = "retry_from_anchor"
    SKIP_STEP = "skip_step"
    CONTINUE_IF_FIXED = "continue_if_fixed"
    ABORT_RUN = "abort_run"


class ResumeStrategy(StrEnum):
    RETRY_FROM_STEP = "retry_from_step"
    CONTINUE_FROM_NEXT_STEP = "continue_from_next_step"
    ABORT = "abort"


@dataclass(frozen=True, slots=True)
class AvailableOperatorAction:
    action_id: str
    action_type: OperatorActionType
    title: str
    description: str
    resume_strategy: ResumeStrategy
    target_step_id: str | None = None
    target_step_index: int | None = None
    recommended: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "action_id": self.action_id,
                "action_type": self.action_type.value,
                "title": self.title,
                "description": self.description,
                "resume_strategy": self.resume_strategy.value,
                "target_step_id": self.target_step_id,
                "target_step_index": self.target_step_index,
                "recommended": self.recommended,
                "details": self.details,
            }
        )

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "AvailableOperatorAction":
        target_step_index_raw = payload.get("target_step_index")
        return cls(
            action_id=str(payload.get("action_id", "")).strip(),
            action_type=OperatorActionType(str(payload.get("action_type", "")).strip()),
            title=str(payload.get("title", "")).strip(),
            description=str(payload.get("description", "")).strip(),
            resume_strategy=ResumeStrategy(str(payload.get("resume_strategy", "")).strip()),
            target_step_id=str(payload.get("target_step_id", "")).strip() or None,
            target_step_index=(
                None
                if target_step_index_raw in {None, ""}
                else int(target_step_index_raw)
            ),
            recommended=bool(payload.get("recommended", False)),
            details=dict(payload.get("details") or {}),
        )


@dataclass(frozen=True, slots=True)
class OperatorActionSelection:
    decision_point_id: str
    action_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_point_id": self.decision_point_id,
            "action_id": self.action_id,
        }


@dataclass(frozen=True, slots=True)
class DecisionResolution:
    decision_point_id: str
    selected_action: AvailableOperatorAction
    resume_strategy: ResumeStrategy
    resolved_at: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def selected_action_id(self) -> str:
        return self.selected_action.action_id

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "decision_point_id": self.decision_point_id,
                "selected_action": self.selected_action.to_dict(),
                "resume_strategy": self.resume_strategy.value,
                "resolved_at": self.resolved_at,
                "details": self.details,
            }
        )

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "DecisionResolution":
        selected_action_raw = payload.get("selected_action") or {}
        if not isinstance(selected_action_raw, dict):
            raise ValueError("Decision resolution selected_action must be an object")
        return cls(
            decision_point_id=str(payload.get("decision_point_id", "")).strip(),
            selected_action=AvailableOperatorAction.from_mapping(selected_action_raw),
            resume_strategy=ResumeStrategy(str(payload.get("resume_strategy", "")).strip()),
            resolved_at=str(payload.get("resolved_at", "")).strip(),
            details=dict(payload.get("details") or {}),
        )
