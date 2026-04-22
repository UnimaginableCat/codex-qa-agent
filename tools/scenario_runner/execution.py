"""Typed execution contracts for scenario runner lifecycle and diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus

from .models import ScenarioStepType

if TYPE_CHECKING:
    from .models import ScenarioStep, StepExecutionResult


class ExecutionPhase(StrEnum):
    RUN_INITIALIZATION = "run_initialization"
    PREFLIGHT = "preflight"
    INITIAL_CONTEXT = "initial_context"
    STEP_VARIABLE_RESOLUTION = "step_variable_resolution"
    INTERPOLATION = "interpolation"
    STEP_EXECUTION = "step_execution"
    CAPTURE = "capture"
    EXPECTATION_VALIDATION = "expectation_validation"
    FINALIZATION = "finalization"
    PERSISTENCE = "persistence"
    REPORTING = "reporting"


class ScenarioRunLifecycleState(StrEnum):
    CREATED = "created"
    INITIALIZING = "initializing"
    PREFLIGHT_RUNNING = "preflight_running"
    READY = "ready"
    STEP_RUNNING = "step_running"
    FINALIZING = "finalizing"
    FINISHED = "finished"


class StepExecutionLifecycleState(StrEnum):
    PENDING = "pending"
    PREPARING = "preparing"
    EXECUTING = "executing"
    CAPTURING = "capturing"
    VALIDATING = "validating"
    FINISHED = "finished"


class ExecutionIssueKind(StrEnum):
    WARNING = "warning"
    PREFLIGHT = "preflight"
    VALIDATION = "validation"
    EXECUTION = "execution"
    TOOLING = "tooling"
    FINALIZATION = "finalization"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class StepReference:
    step_id: str
    step_number: int
    step_type: ScenarioStepType

    @classmethod
    def from_step(cls, step: ScenarioStep) -> "StepReference":
        return cls(
            step_id=step.step_id,
            step_number=step.step_number,
            step_type=step.step_type,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["step_type"] = self.step_type.value
        return to_json_safe(payload)


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    status: StepStatus
    message: str
    phase: ExecutionPhase | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_status(
        cls,
        status: StepStatus,
        message: str,
        *,
        phase: ExecutionPhase | None = None,
        details: dict[str, Any] | None = None,
    ) -> "ExecutionOutcome":
        return cls(status=status, message=message, phase=phase, details=details or {})

    @classmethod
    def from_step_result(
        cls,
        step_result: StepExecutionResult,
        *,
        phase: ExecutionPhase | None = None,
    ) -> "ExecutionOutcome":
        return cls(
            status=step_result.status,
            message=step_result.message,
            phase=phase,
            details=dict(step_result.details),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status.value,
            "message": self.message,
            "phase": None if self.phase is None else self.phase.value,
            "details": self.details,
        }
        return to_json_safe(payload)


@dataclass(frozen=True, slots=True)
class ExecutionIssue:
    code: str
    message: str
    phase: ExecutionPhase
    issue_type: ExecutionIssueKind = ExecutionIssueKind.EXECUTION
    outcome: StepStatus | None = None
    step: StepReference | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "code": self.code,
            "message": self.message,
            "phase": self.phase.value,
            "issue_type": self.issue_type.value,
            "outcome": None if self.outcome is None else self.outcome.value,
            "step": None if self.step is None else self.step.to_dict(),
            "details": self.details,
        }
        return to_json_safe(payload)

    def to_tooling_message(self) -> str:
        prefix_parts = [self.phase.value, self.code]
        if self.step is not None:
            prefix_parts.append(self.step.step_id)
        prefix = ": ".join(prefix_parts)
        if self.outcome is None:
            return f"{prefix}: {self.message}"
        return f"{self.outcome.value} {prefix}: {self.message}"


@dataclass(slots=True)
class StepExecutionState:
    step: StepReference
    lifecycle_state: StepExecutionLifecycleState = StepExecutionLifecycleState.PENDING
    outcome: ExecutionOutcome | None = None
    issues: list[ExecutionIssue] = field(default_factory=list)

    @classmethod
    def from_step(
        cls,
        step: ScenarioStep,
        *,
        lifecycle_state: StepExecutionLifecycleState = StepExecutionLifecycleState.PENDING,
    ) -> "StepExecutionState":
        return cls(step=StepReference.from_step(step), lifecycle_state=lifecycle_state)

    def with_lifecycle(self, lifecycle_state: StepExecutionLifecycleState) -> "StepExecutionState":
        return StepExecutionState(
            step=self.step,
            lifecycle_state=lifecycle_state,
            outcome=self.outcome,
            issues=list(self.issues),
        )

    def finish(
        self,
        outcome: ExecutionOutcome,
        *,
        issues: list[ExecutionIssue] | None = None,
    ) -> "StepExecutionState":
        merged_issues = list(self.issues)
        if issues:
            merged_issues.extend(issues)
        return StepExecutionState(
            step=self.step,
            lifecycle_state=StepExecutionLifecycleState.FINISHED,
            outcome=outcome,
            issues=merged_issues,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step.to_dict(),
            "lifecycle_state": self.lifecycle_state.value,
            "outcome": None if self.outcome is None else self.outcome.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(slots=True)
class ScenarioRunState:
    run_id: str
    scenario_name: str
    scenario_path: Path
    lifecycle_state: ScenarioRunLifecycleState = ScenarioRunLifecycleState.CREATED
    final_outcome: ExecutionOutcome | None = None
    current_step: StepReference | None = None
    issues: list[ExecutionIssue] = field(default_factory=list)
    step_states: list[StepExecutionState] = field(default_factory=list)

    def transition_to(
        self,
        lifecycle_state: ScenarioRunLifecycleState,
        *,
        current_step: StepReference | None = None,
    ) -> None:
        self.lifecycle_state = lifecycle_state
        self.current_step = current_step

    def add_issue(self, issue: ExecutionIssue) -> None:
        self.issues.append(issue)

    def add_step_state(self, step_state: StepExecutionState) -> None:
        self.step_states.append(step_state)

    def set_final_outcome(self, outcome: ExecutionOutcome) -> None:
        self.final_outcome = outcome

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_name": self.scenario_name,
            "scenario_path": str(self.scenario_path),
            "lifecycle_state": self.lifecycle_state.value,
            "final_outcome": None if self.final_outcome is None else self.final_outcome.to_dict(),
            "current_step": None if self.current_step is None else self.current_step.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
            "step_states": [step_state.to_dict() for step_state in self.step_states],
        }


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    event_type: str
    timestamp: str
    run_id: str
    scenario_name: str
    phase: ExecutionPhase
    run_lifecycle_state: ScenarioRunLifecycleState
    step: StepReference | None = None
    step_lifecycle_state: StepExecutionLifecycleState | None = None
    outcome: ExecutionOutcome | None = None
    issue: ExecutionIssue | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        run_state: ScenarioRunState,
        phase: ExecutionPhase,
        step_state: StepExecutionState | None = None,
        outcome: ExecutionOutcome | None = None,
        issue: ExecutionIssue | None = None,
        payload: dict[str, Any] | None = None,
    ) -> "ExecutionEvent":
        return cls(
            event_type=event_type,
            timestamp=utc_now_iso(),
            run_id=run_state.run_id,
            scenario_name=run_state.scenario_name,
            phase=phase,
            run_lifecycle_state=run_state.lifecycle_state,
            step=None if step_state is None else step_state.step,
            step_lifecycle_state=None if step_state is None else step_state.lifecycle_state,
            outcome=outcome,
            issue=issue,
            payload=payload or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event_type,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "scenario_name": self.scenario_name,
            "phase": self.phase.value,
            "run_lifecycle_state": self.run_lifecycle_state.value,
            "step": None if self.step is None else self.step.to_dict(),
            "step_lifecycle_state": None if self.step_lifecycle_state is None else self.step_lifecycle_state.value,
            "outcome": None if self.outcome is None else self.outcome.to_dict(),
            "issue": None if self.issue is None else self.issue.to_dict(),
            "payload": to_json_safe(self.payload),
        }


def coerce_terminal_status(value: StepStatus | ExecutionOutcome) -> StepStatus:
    if isinstance(value, ExecutionOutcome):
        return value.status
    return value


def issue_messages(issues: list[ExecutionIssue]) -> list[str]:
    return [issue.to_tooling_message() for issue in issues]
