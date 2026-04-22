"""Facade services for scenario runner execution and projection finalization."""

from __future__ import annotations

from pathlib import Path

from tools.common.errors import ValidationError

from ..domain.execution import ExecutionOutcome, ExecutionPhase, utc_now_iso
from ..domain.pause import ResumeRequest, RunContinuationState
from ..domain.models import ScenarioDefinition, ScenarioExecutionSummary
from ..persistence import load_pause_state, restore_session_from_pause_state
from ..projections.finalization import ScenarioRunFinalizer
from .context import initialize_run_context
from .engine import ScenarioExecutionEngine


class ScenarioRunnerService:
    """Application facade for scenario execution."""

    def __init__(
        self,
        step_executor_factory=None,
        step_validator=None,
        preflight_checker=None,
        engine: ScenarioExecutionEngine | None = None,
        finalizer: ScenarioRunFinalizer | None = None,
    ) -> None:
        self._engine = engine or ScenarioExecutionEngine(
            step_executor_factory=step_executor_factory,
            step_validator=step_validator,
            preflight_checker=preflight_checker,
        )
        self._finalizer = finalizer or ScenarioRunFinalizer()

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
            self._finalizer.persist_initial_state(session, scenario_definition)
        except Exception as exc:  # noqa: BLE001
            self._finalizer.record_finalization_error(
                session=session,
                finalization_outcomes=finalization_outcomes,
                phase=ExecutionPhase.PERSISTENCE,
                code="initial_run_state_persistence_failed",
                message="initial run state persistence failed",
                exc=exc,
            )
            return self._finalizer.finalize(
                session,
                scenario_definition,
                allow_report=False,
                finalization_outcomes=finalization_outcomes,
            )

        session = self._engine.execute(session, scenario_definition)
        return self._finalizer.finalize(
            session,
            scenario_definition,
            allow_report=True,
            finalization_outcomes=finalization_outcomes,
        )

    def resume(
        self,
        pause_state_path: Path,
        *,
        scenario_definition: ScenarioDefinition | None = None,
        selected_action_id: str | None = None,
    ) -> ScenarioExecutionSummary:
        pause_state = load_pause_state(pause_state_path)
        if not pause_state.resumable:
            raise ValidationError("Pause state is not active or resumable.")
        restored_scenario_definition, session = restore_session_from_pause_state(
            pause_state,
            scenario_definition=scenario_definition,
        )
        scenario = scenario_definition or restored_scenario_definition
        session.pause_state = pause_state

        finalization_outcomes: list[ExecutionOutcome] = []
        session = self._engine.resume(
            session,
            scenario,
            ResumeRequest(
                resume_token=pause_state.resume_token,
                selected_action_id=selected_action_id,
            ),
        )
        pause_state.mark_resumed(selected_action_id, utc_now_iso())
        summary = self._finalizer.finalize(
            session,
            scenario,
            allow_report=True,
            finalization_outcomes=finalization_outcomes,
        )
        if summary.continuation_state != RunContinuationState.PAUSED:
            self._finalizer.persist_pause_state(session.run_context, pause_state)
        return summary
