"""Projection-oriented read models for scenario execution outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.execution import ExecutionEvent, ExecutionIssue, ExecutionOutcome, ScenarioRunState
from ..domain.guided import DecisionPoint, GuidedDiagnostic
from ..domain.manual import DecisionResolution
from ..domain.models import RunContext, ScenarioDefinition
from ..domain.pause import PauseState, RunContinuationState


@dataclass(frozen=True, slots=True)
class ExecutionProjectionState:
    """Stable read snapshot built from execution state plus finalization outcomes."""

    scenario_definition: ScenarioDefinition
    run_context: RunContext
    run_state: ScenarioRunState | None
    tooling_issues: tuple[ExecutionIssue, ...] = ()
    compile_outcomes: tuple[ExecutionOutcome, ...] = ()
    compile_checks: tuple[dict[str, Any], ...] = ()
    preflight_outcomes: tuple[ExecutionOutcome, ...] = ()
    preflight_checks: tuple[dict[str, Any], ...] = ()
    finalization_outcomes: tuple[ExecutionOutcome, ...] = ()
    execution_events: tuple[ExecutionEvent, ...] = ()
    report_path: Path | None = None
    continuation_state: RunContinuationState = RunContinuationState.ACTIVE
    pause_state: PauseState | None = None
    decision_resolution: DecisionResolution | None = None
    resumed_from_pause: bool = False

    @classmethod
    def from_session(
        cls,
        session,
        scenario_definition: ScenarioDefinition,
        *,
        finalization_outcomes: list[ExecutionOutcome] | None = None,
        report_path: Path | None = None,
    ) -> "ExecutionProjectionState":
        return cls(
            scenario_definition=scenario_definition,
            run_context=session.run_context,
            run_state=session.run_state,
            tooling_issues=tuple(session.tooling_issues),
            compile_outcomes=tuple(session.compile_outcomes),
            compile_checks=tuple(check.to_dict() for check in session.compile_checks),
            preflight_outcomes=tuple(session.preflight_outcomes),
            preflight_checks=tuple(check.to_dict() for check in session.preflight_checks),
            finalization_outcomes=tuple(finalization_outcomes or []),
            execution_events=tuple(session.execution_events),
            report_path=report_path,
            continuation_state=session.continuation_state,
            pause_state=session.pause_state,
            decision_resolution=session.decision_resolution,
            resumed_from_pause=session.resumed_from_pause,
        )

    @property
    def step_results(self) -> list:
        return list(self.run_context.step_results)

    @property
    def executed_step_count(self) -> int:
        return len(self.run_context.step_results)

    @property
    def total_step_count(self) -> int:
        return len(self.scenario_definition.steps)

    @property
    def parse_warnings(self) -> list[str]:
        return [str(item) for item in self.scenario_definition.metadata.get("parse_warnings", [])]


@dataclass(frozen=True, slots=True)
class JournalProjection:
    """Projected journal entries derived from execution events and terminal outcome."""

    entries: tuple[ExecutionEvent, ...]

    def persisted_entries(self, *, skip: int = 0) -> tuple[ExecutionEvent, ...]:
        if skip <= 0:
            return self.entries
        return self.entries[skip:]


@dataclass(frozen=True, slots=True)
class GuidedRunProjection:
    """Projected operator-facing diagnostics derived from execution state."""

    diagnostics: tuple[GuidedDiagnostic, ...]
    stop_reason: GuidedDiagnostic | None = None
    decision_points: tuple[DecisionPoint, ...] = ()
