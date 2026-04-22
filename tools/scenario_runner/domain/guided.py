"""Typed guided-mode contracts for operator-facing diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus

from .execution import ExecutionPhase, StepReference
from .manual import AvailableOperatorAction


class GuidedDiagnosticTag(StrEnum):
    INFORMATIVE = "informative"
    RETRYABLE = "retryable"
    USER_FIXABLE = "user_fixable"
    ENVIRONMENT_BLOCKED = "environment_blocked"
    UNSUPPORTED_BY_RUNNER = "unsupported_by_runner"
    REQUIRES_DECISION = "requires_decision"


class ContinuationPolicy(StrEnum):
    CONTINUE = "continue"
    RETRY_AUTOMATICALLY = "retry_automatically"
    RETRY_MANUALLY = "retry_manually"
    STOP_AND_FIX = "stop_and_fix"
    WAIT_FOR_DECISION = "wait_for_decision"
    STOP_UNSUPPORTED = "stop_unsupported"


class GuidedActionType(StrEnum):
    REVIEW_CONFIGURATION = "review_configuration"
    UPDATE_SCENARIO = "update_scenario"
    RETRY_RUN = "retry_run"
    INSPECT_ARTIFACTS = "inspect_artifacts"
    INSTALL_DEPENDENCY = "install_dependency"
    REVIEW_RUNNER_LIMITATION = "review_runner_limitation"


@dataclass(frozen=True, slots=True)
class GuidedAction:
    action_id: str
    action_type: GuidedActionType
    title: str
    description: str
    recommended: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "action_id": self.action_id,
                "action_type": self.action_type.value,
                "title": self.title,
                "description": self.description,
                "recommended": self.recommended,
                "details": self.details,
            }
        )


@dataclass(frozen=True, slots=True)
class DecisionPoint:
    decision_id: str
    title: str
    prompt: str
    continuation_policy: ContinuationPolicy
    recommended_action_id: str | None = None
    actions: tuple[GuidedAction, ...] = ()
    available_operator_actions: tuple[AvailableOperatorAction, ...] = ()
    recommended_operator_action_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "decision_id": self.decision_id,
                "title": self.title,
                "prompt": self.prompt,
                "continuation_policy": self.continuation_policy.value,
                "recommended_action_id": self.recommended_action_id,
                "actions": [action.to_dict() for action in self.actions],
                "available_operator_actions": [
                    action.to_dict() for action in self.available_operator_actions
                ],
                "recommended_operator_action_id": self.recommended_operator_action_id,
                "details": self.details,
            }
        )


@dataclass(frozen=True, slots=True)
class GuidedDiagnostic:
    diagnostic_id: str
    title: str
    summary: str
    phase: ExecutionPhase | None = None
    status: StepStatus | None = None
    step: StepReference | None = None
    issue_code: str | None = None
    continuation_policy: ContinuationPolicy = ContinuationPolicy.CONTINUE
    tags: tuple[GuidedDiagnosticTag, ...] = ()
    actions: tuple[GuidedAction, ...] = ()
    decision_point: DecisionPoint | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def can_continue_automatically(self) -> bool:
        return self.continuation_policy in {
            ContinuationPolicy.CONTINUE,
            ContinuationPolicy.RETRY_AUTOMATICALLY,
        }

    @property
    def requires_user_decision(self) -> bool:
        return self.decision_point is not None or GuidedDiagnosticTag.REQUIRES_DECISION in self.tags

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "diagnostic_id": self.diagnostic_id,
                "title": self.title,
                "summary": self.summary,
                "phase": None if self.phase is None else self.phase.value,
                "status": None if self.status is None else self.status.value,
                "step": None if self.step is None else self.step.to_dict(),
                "issue_code": self.issue_code,
                "continuation_policy": self.continuation_policy.value,
                "tags": [tag.value for tag in self.tags],
                "can_continue_automatically": self.can_continue_automatically,
                "requires_user_decision": self.requires_user_decision,
                "actions": [action.to_dict() for action in self.actions],
                "decision_point": None if self.decision_point is None else self.decision_point.to_dict(),
                "details": self.details,
            }
        )
