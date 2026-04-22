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
    COMPILATION = "compilation"
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
    COMPILING = "compiling"
    PREFLIGHT_RUNNING = "preflight_running"
    READY = "ready"
    RESUMING = "resuming"
    STEP_RUNNING = "step_running"
    FINALIZING = "finalizing"
    PAUSED = "paused"
    FINISHED = "finished"


class StepExecutionLifecycleState(StrEnum):
    PENDING = "pending"
    PREPARING = "preparing"
    EXECUTING = "executing"
    CAPTURING = "capturing"
    VALIDATING = "validating"
    FINISHED = "finished"


class RunTerminationKind(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    ERRORED = "errored"
    PAUSED = "paused"
    ABORTED = "aborted"


class StepTerminationKind(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    ERRORED = "errored"
    SKIPPED = "skipped"


class CompletionDisposition(StrEnum):
    NONE = "none"
    COMPLETE = "complete"
    PARTIAL = "partial"


class SkipDisposition(StrEnum):
    OPERATOR = "operator"
    POLICY = "policy"


class AbortDisposition(StrEnum):
    OPERATOR = "operator"
    RUNTIME_FAILURE = "runtime_failure"
    POLICY = "policy"


class TerminationReasonSource(StrEnum):
    EXECUTION = "execution"
    RUNTIME = "runtime"
    OPERATOR = "operator"
    POLICY = "policy"
    PREFLIGHT = "preflight"
    COMPILATION = "compilation"
    FINALIZATION = "finalization"


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
class TerminationReason:
    code: str
    message: str
    source: TerminationReasonSource
    phase: ExecutionPhase | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "code": self.code,
                "message": self.message,
                "source": self.source.value,
                "phase": None if self.phase is None else self.phase.value,
                "details": self.details,
            }
        )


@dataclass(frozen=True, slots=True)
class StepTermination:
    kind: StepTerminationKind
    reason: TerminationReason
    outcome_status: StepStatus | None = None
    skip_disposition: SkipDisposition | None = None
    operator_resolution: dict[str, Any] | None = None
    terminated_at: str = field(default_factory=utc_now_iso)

    @property
    def skipped(self) -> bool:
        return self.kind == StepTerminationKind.SKIPPED

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "kind": self.kind.value,
                "reason": self.reason.to_dict(),
                "outcome_status": None if self.outcome_status is None else self.outcome_status.value,
                "skip_disposition": None if self.skip_disposition is None else self.skip_disposition.value,
                "operator_resolution": self.operator_resolution,
                "terminated_at": self.terminated_at,
                "skipped": self.skipped,
            }
        )


@dataclass(frozen=True, slots=True)
class RunTermination:
    kind: RunTerminationKind
    reason: TerminationReason
    completion_disposition: CompletionDisposition
    outcome_status: StepStatus | None = None
    abort_disposition: AbortDisposition | None = None
    operator_resolution: dict[str, Any] | None = None
    completed_step_count: int = 0
    total_step_count: int = 0
    terminated_at: str = field(default_factory=utc_now_iso)

    @property
    def terminal(self) -> bool:
        return self.kind != RunTerminationKind.PAUSED

    @property
    def partial(self) -> bool:
        return self.completion_disposition == CompletionDisposition.PARTIAL

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "kind": self.kind.value,
                "reason": self.reason.to_dict(),
                "completion_disposition": self.completion_disposition.value,
                "outcome_status": None if self.outcome_status is None else self.outcome_status.value,
                "abort_disposition": None if self.abort_disposition is None else self.abort_disposition.value,
                "operator_resolution": self.operator_resolution,
                "completed_step_count": self.completed_step_count,
                "total_step_count": self.total_step_count,
                "terminated_at": self.terminated_at,
                "terminal": self.terminal,
                "partial": self.partial,
            }
        )


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
    termination: StepTermination | None = None
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
            termination=self.termination,
            issues=list(self.issues),
        )

    def finish(
        self,
        outcome: ExecutionOutcome,
        *,
        issues: list[ExecutionIssue] | None = None,
        termination: StepTermination | None = None,
    ) -> "StepExecutionState":
        merged_issues = list(self.issues)
        if issues:
            merged_issues.extend(issues)
        return StepExecutionState(
            step=self.step,
            lifecycle_state=StepExecutionLifecycleState.FINISHED,
            outcome=outcome,
            termination=termination or build_step_termination(self.step, outcome),
            issues=merged_issues,
        )

    def with_termination(self, termination: StepTermination) -> "StepExecutionState":
        return StepExecutionState(
            step=self.step,
            lifecycle_state=self.lifecycle_state,
            outcome=self.outcome,
            termination=termination,
            issues=list(self.issues),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step.to_dict(),
            "lifecycle_state": self.lifecycle_state.value,
            "outcome": None if self.outcome is None else self.outcome.to_dict(),
            "termination": None if self.termination is None else self.termination.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(slots=True)
class ScenarioRunState:
    run_id: str
    scenario_name: str
    scenario_path: Path
    lifecycle_state: ScenarioRunLifecycleState = ScenarioRunLifecycleState.CREATED
    final_outcome: ExecutionOutcome | None = None
    termination: RunTermination | None = None
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

    def set_termination(self, termination: RunTermination) -> None:
        self.termination = termination

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_name": self.scenario_name,
            "scenario_path": str(self.scenario_path),
            "lifecycle_state": self.lifecycle_state.value,
            "final_outcome": None if self.final_outcome is None else self.final_outcome.to_dict(),
            "termination": None if self.termination is None else self.termination.to_dict(),
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
    run_termination: RunTermination | None = None
    step_termination: StepTermination | None = None
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
            run_termination=run_state.termination,
            step_termination=None if step_state is None else step_state.termination,
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
            "run_termination": None if self.run_termination is None else self.run_termination.to_dict(),
            "step_termination": None if self.step_termination is None else self.step_termination.to_dict(),
            "outcome": None if self.outcome is None else self.outcome.to_dict(),
            "issue": None if self.issue is None else self.issue.to_dict(),
            "payload": to_json_safe(self.payload),
        }


def coerce_terminal_status(value: StepStatus | ExecutionOutcome) -> StepStatus:
    if isinstance(value, ExecutionOutcome):
        return value.status
    return value


def build_step_termination(
    step: StepReference,
    outcome: ExecutionOutcome,
    *,
    reason: TerminationReason | None = None,
) -> StepTermination:
    kind = step_termination_kind_from_status(outcome.status)
    resolved_reason = reason or TerminationReason(
        code=f"step_{kind.value}",
        message=outcome.message,
        source=TerminationReasonSource.EXECUTION,
        phase=outcome.phase,
    )
    return StepTermination(
        kind=kind,
        reason=resolved_reason,
        outcome_status=outcome.status,
    )


def step_termination_kind_from_status(status: StepStatus) -> StepTerminationKind:
    if status == StepStatus.PASS:
        return StepTerminationKind.COMPLETED
    if status == StepStatus.FAIL:
        return StepTerminationKind.FAILED
    if status == StepStatus.BLOCKED:
        return StepTerminationKind.BLOCKED
    return StepTerminationKind.ERRORED


def run_termination_kind_from_status(status: StepStatus) -> RunTerminationKind:
    if status == StepStatus.PASS:
        return RunTerminationKind.COMPLETED
    if status == StepStatus.FAIL:
        return RunTerminationKind.FAILED
    if status == StepStatus.BLOCKED:
        return RunTerminationKind.BLOCKED
    return RunTerminationKind.ERRORED


def completion_disposition(
    *,
    executed_step_count: int,
    total_step_count: int,
) -> CompletionDisposition:
    if total_step_count <= 0 or executed_step_count <= 0:
        return CompletionDisposition.NONE
    if executed_step_count >= total_step_count:
        return CompletionDisposition.COMPLETE
    return CompletionDisposition.PARTIAL


def issue_messages(issues: list[ExecutionIssue]) -> list[str]:
    return [issue.to_tooling_message() for issue in issues]
