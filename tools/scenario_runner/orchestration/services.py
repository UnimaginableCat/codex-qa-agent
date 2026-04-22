"""Facade services for scenario runner execution and projection finalization."""

from __future__ import annotations

from pathlib import Path

from ..domain.execution import ExecutionOutcome, ExecutionPhase
from ..domain.models import ScenarioDefinition, ScenarioExecutionSummary
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
