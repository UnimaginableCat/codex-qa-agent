"""Finalization coordinator for projection assembly and artifact persistence."""

from __future__ import annotations

from pathlib import Path

from tools.common.statuses import StepStatus
from tools.reports import build_service

from ..domain.execution import (
    ExecutionIssue,
    ExecutionIssueKind,
    ExecutionOutcome,
    ExecutionPhase,
    ScenarioRunLifecycleState,
)
from ..domain.models import ScenarioDefinition, ScenarioExecutionSummary
from ..domain.pause import RunContinuationState
from ..persistence.artifacts import ScenarioRunArtifactStore
from .journal import build_journal_projection
from .models import ExecutionProjectionState
from .pause import build_pause_state
from .reporting import build_report_context
from .summary import build_summary_projection


class ScenarioRunFinalizer:
    """Builds projections from execution state and persists them as artifacts."""

    def __init__(self, artifact_store: ScenarioRunArtifactStore | None = None) -> None:
        self._artifact_store = artifact_store or ScenarioRunArtifactStore()

    def persist_initial_state(
        self,
        session,
        scenario_definition: ScenarioDefinition,
    ) -> None:
        self._artifact_store.write_initial_state(session, scenario_definition)

    def persist_pause_state(self, run_context, pause_state) -> Path:
        return self._artifact_store.write_pause_state(run_context, pause_state)

    def finalize(
        self,
        session,
        scenario_definition: ScenarioDefinition,
        *,
        allow_report: bool,
        finalization_outcomes: list[ExecutionOutcome] | None = None,
    ) -> ScenarioExecutionSummary:
        session.run_state.transition_to(ScenarioRunLifecycleState.FINALIZING)
        outcomes = finalization_outcomes if finalization_outcomes is not None else []
        report_path: Path | None = None

        if not self._try_write_context(session, outcomes):
            allow_report = False

        if allow_report:
            try:
                report_path = self._artifact_store.create_report_path(session.run_context)
            except Exception as exc:  # noqa: BLE001
                self.record_finalization_error(
                    session=session,
                    finalization_outcomes=outcomes,
                    phase=ExecutionPhase.REPORTING,
                    code="report_artifact_path_creation_failed",
                    message="report artifact path creation failed",
                    exc=exc,
                )
                allow_report = False

        session.continuation_state = (
            RunContinuationState.RESUMED if session.resumed_from_pause else RunContinuationState.TERMINAL
        )
        if not session.resumed_from_pause:
            session.pause_state = None
        projection_state = ExecutionProjectionState.from_session(
            session,
            scenario_definition,
            finalization_outcomes=outcomes,
            report_path=report_path if allow_report else None,
        )
        pause_state = build_pause_state(projection_state)
        if pause_state is not None:
            try:
                pause_path = self._artifact_store.write_pause_state(session.run_context, pause_state)
                pause_state.set_path(pause_path)
                session.pause_state = pause_state
                session.continuation_state = RunContinuationState.PAUSED
                session.run_state.transition_to(ScenarioRunLifecycleState.PAUSED)
            except Exception as exc:  # noqa: BLE001
                self.record_finalization_error(
                    session=session,
                    finalization_outcomes=outcomes,
                    phase=ExecutionPhase.PERSISTENCE,
                    code="pause_state_persistence_failed",
                    message="pause state persistence failed",
                    exc=exc,
                )
                session.continuation_state = (
                    RunContinuationState.RESUMED if session.resumed_from_pause else RunContinuationState.TERMINAL
                )
                session.pause_state = None

        projection_state = ExecutionProjectionState.from_session(
            session,
            scenario_definition,
            finalization_outcomes=outcomes,
            report_path=report_path if allow_report else None,
        )
        summary = build_summary_projection(projection_state)

        if not self._try_write_summary(session, summary, outcomes):
            return self._finish_without_report(
                session=session,
                scenario_definition=scenario_definition,
                finalization_outcomes=outcomes,
            )

        if not self._try_write_journal(session, summary, projection_state, outcomes):
            fallback_summary = self._finish_without_report(
                session=session,
                scenario_definition=scenario_definition,
                finalization_outcomes=outcomes,
            )
            self._try_write_summary(session, fallback_summary, outcomes)
            return fallback_summary

        if allow_report and report_path is not None:
            try:
                self._build_report(summary, report_path)
            except Exception as exc:  # noqa: BLE001
                self.record_finalization_error(
                    session=session,
                    finalization_outcomes=outcomes,
                    phase=ExecutionPhase.REPORTING,
                    code="report_generation_failed",
                    message="report generation failed",
                    exc=exc,
                )
                summary = self._finish_without_report(
                    session=session,
                    scenario_definition=scenario_definition,
                    finalization_outcomes=outcomes,
                )
                self._try_write_summary(session, summary, outcomes)
                return summary

        return self._finish_with_summary(session, summary)

    def record_finalization_error(
        self,
        session,
        finalization_outcomes: list[ExecutionOutcome],
        *,
        phase: ExecutionPhase,
        code: str,
        message: str,
        exc: Exception,
    ) -> None:
        issue = ExecutionIssue(
            code=code,
            message=f"{message}: {exc}",
            phase=phase,
            issue_type=ExecutionIssueKind.FINALIZATION,
            outcome=StepStatus.ERROR,
            details={"error_type": type(exc).__name__},
        )
        session.add_issue(issue)
        finalization_outcomes.append(
            ExecutionOutcome.from_status(
                StepStatus.ERROR,
                issue.message,
                phase=phase,
                details=issue.details,
            )
        )

    @staticmethod
    def _build_report(summary: ScenarioExecutionSummary, report_path: Path) -> Path:
        service = build_service()
        context = build_report_context(summary)
        return service.build_from_context(context=context, output_path=report_path)

    def _finish_without_report(
        self,
        session,
        scenario_definition: ScenarioDefinition,
        finalization_outcomes: list[ExecutionOutcome],
    ) -> ScenarioExecutionSummary:
        summary = build_summary_projection(
            ExecutionProjectionState.from_session(
                session,
                scenario_definition,
                finalization_outcomes=finalization_outcomes,
            )
        )
        return self._finish_with_summary(session, summary)

    @staticmethod
    def _finish_with_summary(session, summary: ScenarioExecutionSummary) -> ScenarioExecutionSummary:
        session.run_state.set_final_outcome(
            ExecutionOutcome.from_status(
                summary.final_status,
                summary.message,
                phase=ExecutionPhase.FINALIZATION,
            )
        )
        session.run_state.transition_to(
            ScenarioRunLifecycleState.PAUSED
            if summary.continuation_state == RunContinuationState.PAUSED
            else ScenarioRunLifecycleState.FINISHED
        )
        return summary

    def _try_write_context(
        self,
        session,
        finalization_outcomes: list[ExecutionOutcome],
    ) -> bool:
        try:
            self._artifact_store.write_context(session.run_context)
            return True
        except Exception as exc:  # noqa: BLE001
            self.record_finalization_error(
                session=session,
                finalization_outcomes=finalization_outcomes,
                phase=ExecutionPhase.PERSISTENCE,
                code="context_persistence_failed",
                message="context persistence failed",
                exc=exc,
            )
            return False

    def _try_write_summary(
        self,
        session,
        summary: ScenarioExecutionSummary,
        finalization_outcomes: list[ExecutionOutcome],
    ) -> bool:
        try:
            self._artifact_store.write_summary(session.run_context, summary)
            return True
        except Exception as exc:  # noqa: BLE001
            self.record_finalization_error(
                session=session,
                finalization_outcomes=finalization_outcomes,
                phase=ExecutionPhase.PERSISTENCE,
                code="summary_persistence_failed",
                message="summary persistence failed",
                exc=exc,
            )
            return False

    def _try_write_journal(
        self,
        session,
        summary: ScenarioExecutionSummary,
        projection_state: ExecutionProjectionState,
        finalization_outcomes: list[ExecutionOutcome],
    ) -> bool:
        try:
            journal = build_journal_projection(projection_state, summary, include_run_finished=True)
            skip_count = 1 if session.execution_events and session.execution_events[0].event_type == "run_initialized" else 0
            self._artifact_store.write_journal(session.run_context, journal.persisted_entries(skip=skip_count))
            return True
        except Exception as exc:  # noqa: BLE001
            self.record_finalization_error(
                session=session,
                finalization_outcomes=finalization_outcomes,
                phase=ExecutionPhase.PERSISTENCE,
                code="journal_persistence_failed",
                message="journal persistence failed",
                exc=exc,
            )
            return False
