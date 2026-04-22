"""Facade services for scenario runner execution and artifact projection."""

from __future__ import annotations

from pathlib import Path

from tools.common.statuses import StepStatus

from .artifacts import (
    create_report_path,
    write_bundle_compiled_plan_json,
    write_compiled_plan_json,
    write_context_json,
    write_journal_entry,
    write_summary_json,
)
from .context import initialize_run_context
from .engine import ScenarioExecutionEngine, ScenarioExecutionSession
from .execution import (
    ExecutionEvent,
    ExecutionIssue,
    ExecutionIssueKind,
    ExecutionOutcome,
    ExecutionPhase,
    ScenarioRunLifecycleState,
)
from .models import ScenarioDefinition, ScenarioExecutionSummary
from .summary import build_scenario_summary


class ScenarioRunnerService:
    """Application facade for scenario execution."""

    def __init__(
        self,
        step_executor_factory=None,
        step_validator=None,
        preflight_checker=None,
        engine: ScenarioExecutionEngine | None = None,
    ) -> None:
        self._engine = engine or ScenarioExecutionEngine(
            step_executor_factory=step_executor_factory,
            step_validator=step_validator,
            preflight_checker=preflight_checker,
        )

    def run(
        self,
        scenario_definition: ScenarioDefinition,
        workspace_root: Path | None = None,
    ) -> ScenarioExecutionSummary:
        run_context = initialize_run_context(
            scenario_definition=scenario_definition,
            workspace_root=workspace_root,
        )
        session = self._engine.create_session(run_context, scenario_definition)

        finalization_outcomes: list[ExecutionOutcome] = []
        try:
            self._persist_initial_run_state(session, scenario_definition)
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                session=session,
                finalization_outcomes=finalization_outcomes,
                phase=ExecutionPhase.PERSISTENCE,
                code="initial_run_state_persistence_failed",
                message="initial run state persistence failed",
                exc=exc,
            )
            return self._finalize_run(
                session=session,
                scenario_definition=scenario_definition,
                finalization_outcomes=finalization_outcomes,
                allow_report=False,
            )

        session = self._engine.execute(session, scenario_definition)
        return self._finalize_run(
            session=session,
            scenario_definition=scenario_definition,
            finalization_outcomes=finalization_outcomes,
            allow_report=True,
        )

    def _persist_initial_run_state(
        self,
        session: ScenarioExecutionSession,
        scenario_definition: ScenarioDefinition,
    ) -> None:
        write_compiled_plan_json(session.run_context.compiled_plan_path, scenario_definition)
        write_bundle_compiled_plan_json(session.run_context, scenario_definition)
        write_context_json(session.run_context)
        if session.execution_events:
            write_journal_entry(session.run_context, session.execution_events[0])

    def _finalize_run(
        self,
        session: ScenarioExecutionSession,
        scenario_definition: ScenarioDefinition,
        finalization_outcomes: list[ExecutionOutcome],
        allow_report: bool,
    ) -> ScenarioExecutionSummary:
        session.run_state.transition_to(ScenarioRunLifecycleState.FINALIZING)
        report_path: Path | None = None

        if not self._try_write_context(session, finalization_outcomes):
            allow_report = False

        if allow_report:
            try:
                report_path = create_report_path(session.run_context)
            except Exception as exc:  # noqa: BLE001
                self._record_finalization_error(
                    session=session,
                    finalization_outcomes=finalization_outcomes,
                    phase=ExecutionPhase.REPORTING,
                    code="report_artifact_path_creation_failed",
                    message="report artifact path creation failed",
                    exc=exc,
                )
                allow_report = False

        summary = self._build_summary(
            session=session,
            scenario_definition=scenario_definition,
            finalization_outcomes=finalization_outcomes,
            report_path=report_path if allow_report else None,
        )
        if not self._try_write_summary(session, summary, finalization_outcomes):
            summary = self._build_summary(
                session=session,
                scenario_definition=scenario_definition,
                finalization_outcomes=finalization_outcomes,
            )
            session.run_state.set_final_outcome(
                ExecutionOutcome.from_status(
                    summary.final_status,
                    summary.message,
                    phase=ExecutionPhase.FINALIZATION,
                )
            )
            session.run_state.transition_to(ScenarioRunLifecycleState.FINISHED)
            return summary

        if not self._try_write_engine_events(
            session=session,
            finalization_outcomes=finalization_outcomes,
            include_run_finished=True,
            report_path=report_path if allow_report else None,
            summary=summary,
        ):
            summary = self._build_summary(
                session=session,
                scenario_definition=scenario_definition,
                finalization_outcomes=finalization_outcomes,
            )
            self._try_write_summary(session, summary, finalization_outcomes)
            session.run_state.set_final_outcome(
                ExecutionOutcome.from_status(
                    summary.final_status,
                    summary.message,
                    phase=ExecutionPhase.FINALIZATION,
                )
            )
            session.run_state.transition_to(ScenarioRunLifecycleState.FINISHED)
            return summary

        if allow_report and report_path is not None:
            try:
                self._build_report(session.run_context, scenario_definition, report_path)
            except Exception as exc:  # noqa: BLE001
                self._record_finalization_error(
                    session=session,
                    finalization_outcomes=finalization_outcomes,
                    phase=ExecutionPhase.REPORTING,
                    code="report_generation_failed",
                    message="report generation failed",
                    exc=exc,
                )
                summary = self._build_summary(
                    session=session,
                    scenario_definition=scenario_definition,
                    finalization_outcomes=finalization_outcomes,
                )
                self._try_write_summary(session, summary, finalization_outcomes)
                session.run_state.set_final_outcome(
                    ExecutionOutcome.from_status(
                        summary.final_status,
                        summary.message,
                        phase=ExecutionPhase.FINALIZATION,
                    )
                )
                session.run_state.transition_to(ScenarioRunLifecycleState.FINISHED)
                return summary

        session.run_state.set_final_outcome(
            ExecutionOutcome.from_status(
                summary.final_status,
                summary.message,
                phase=ExecutionPhase.FINALIZATION,
            )
        )
        session.run_state.transition_to(ScenarioRunLifecycleState.FINISHED)
        return summary

    def _build_summary(
        self,
        session: ScenarioExecutionSession,
        scenario_definition: ScenarioDefinition,
        finalization_outcomes: list[ExecutionOutcome],
        report_path: Path | None = None,
    ) -> ScenarioExecutionSummary:
        return build_scenario_summary(
            session.run_context,
            scenario_definition,
            report_path=report_path,
            extra_tooling_issues=session.tooling_issues,
            finalization_statuses=finalization_outcomes,
            preflight_statuses=session.preflight_outcomes,
            preflight_checks=[check.to_dict() for check in session.preflight_checks],
        )

    @staticmethod
    def _build_report(
        run_context,
        scenario_definition: ScenarioDefinition,
        report_path: Path,
    ) -> Path:
        from tools.reports import build_service

        service = build_service()
        return service.build(
            project=scenario_definition.project,
            scenario=scenario_definition.scenario_name,
            summary_path=run_context.run_state_dir / "summary.json",
            output_path=report_path,
        )

    def _try_write_context(
        self,
        session: ScenarioExecutionSession,
        finalization_outcomes: list[ExecutionOutcome],
    ) -> bool:
        try:
            write_context_json(session.run_context)
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
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
        session: ScenarioExecutionSession,
        summary: ScenarioExecutionSummary,
        finalization_outcomes: list[ExecutionOutcome],
    ) -> bool:
        try:
            write_summary_json(session.run_context, summary)
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                session=session,
                finalization_outcomes=finalization_outcomes,
                phase=ExecutionPhase.PERSISTENCE,
                code="summary_persistence_failed",
                message="summary persistence failed",
                exc=exc,
            )
            return False

    def _try_write_engine_events(
        self,
        session: ScenarioExecutionSession,
        finalization_outcomes: list[ExecutionOutcome],
        include_run_finished: bool,
        report_path: Path | None,
        summary: ScenarioExecutionSummary,
    ) -> bool:
        try:
            for event in session.execution_events[1:]:
                write_journal_entry(session.run_context, event)

            if include_run_finished:
                summary_outcome = ExecutionOutcome.from_status(
                    summary.final_status,
                    summary.message,
                    phase=ExecutionPhase.FINALIZATION,
                )
                write_journal_entry(
                    session.run_context,
                    ExecutionEvent.create(
                        event_type="run_finished",
                        run_state=session.run_state,
                        phase=ExecutionPhase.FINALIZATION,
                        outcome=summary_outcome,
                        issue=session.tooling_issues[-1] if session.tooling_issues else None,
                        payload={
                            "executed_step_count": len(session.run_context.step_results),
                            "report_path": None if report_path is None else str(report_path),
                        },
                    ),
                )
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                session=session,
                finalization_outcomes=finalization_outcomes,
                phase=ExecutionPhase.PERSISTENCE,
                code="journal_persistence_failed",
                message="journal persistence failed",
                exc=exc,
            )
            return False

    @staticmethod
    def _record_finalization_error(
        session: ScenarioExecutionSession,
        finalization_outcomes: list[ExecutionOutcome],
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
