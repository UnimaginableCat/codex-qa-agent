"""Core orchestration engine for scenario execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tools.common.statuses import StepStatus

from .compiler import CompileCheckResult, CompiledScenario, ScenarioCompiler
from ..domain.pause import ResumeRequest, RunContinuationState
from ..domain.execution import (
    AbortDisposition,
    ExecutionEvent,
    ExecutionIssue,
    ExecutionIssueKind,
    ExecutionOutcome,
    ExecutionPhase,
    RunTermination,
    RunTerminationKind,
    ScenarioRunLifecycleState,
    ScenarioRunState,
    SkipDisposition,
    StepExecutionLifecycleState,
    StepExecutionState,
    StepReference,
    StepTermination,
    StepTerminationKind,
    TerminationReason,
    TerminationReasonSource,
    completion_disposition,
    run_termination_kind_from_status,
)
from ..runtime.executors import StepExecutionOutcome, StepExecutorFactory
from ..domain.models import RunContext, ScenarioDefinition, ScenarioStep, StepExecutionResult
from .preflight import PreflightCheckResult, PreflightResult, ScenarioPreflightChecker
from ..projections.summary import resolve_final_status
from ..runtime.validators import ExpectationValidationError, ScenarioStepValidator
from ..runtime.variables import VariableResolutionError, build_initial_variables, resolve_step_variables

if TYPE_CHECKING:
    from ..domain.pause import PauseState
    from ..domain.manual import DecisionResolution


@dataclass(slots=True)
class ScenarioExecutionSession:
    run_context: RunContext
    run_state: ScenarioRunState
    tooling_issues: list[ExecutionIssue] = field(default_factory=list)
    compile_outcomes: list[ExecutionOutcome] = field(default_factory=list)
    compile_checks: list[CompileCheckResult] = field(default_factory=list)
    preflight_outcomes: list[ExecutionOutcome] = field(default_factory=list)
    preflight_checks: list[PreflightCheckResult] = field(default_factory=list)
    execution_events: list[ExecutionEvent] = field(default_factory=list)
    continuation_state: RunContinuationState = RunContinuationState.ACTIVE
    pause_state: "PauseState | None" = None
    decision_resolution: "DecisionResolution | None" = None
    resumed_from_pause: bool = False

    def append_event(self, event: ExecutionEvent) -> None:
        self.execution_events.append(event)

    def add_issue(self, issue: ExecutionIssue) -> None:
        self.tooling_issues.append(issue)
        self.run_state.add_issue(issue)

    def add_step_state(self, step_state: StepExecutionState) -> None:
        self.run_state.add_step_state(step_state)


class ScenarioExecutionEngine:
    """Runs scenario execution lifecycle without persistence/report side effects."""

    def __init__(
        self,
        step_executor_factory: StepExecutorFactory | None = None,
        step_validator: ScenarioStepValidator | None = None,
        preflight_checker: ScenarioPreflightChecker | None = None,
        compiler: ScenarioCompiler | None = None,
    ) -> None:
        self._step_executor_factory = step_executor_factory or StepExecutorFactory()
        self._step_validator = step_validator or ScenarioStepValidator()
        self._preflight_checker = preflight_checker or ScenarioPreflightChecker()
        self._compiler = compiler or ScenarioCompiler(step_validator=self._step_validator)

    def create_session(
        self,
        run_context: RunContext,
        scenario_definition: ScenarioDefinition,
    ) -> ScenarioExecutionSession:
        run_state = ScenarioRunState(
            run_id=run_context.run_id,
            scenario_name=scenario_definition.scenario_name,
            scenario_path=run_context.scenario_path,
        )
        run_state.transition_to(ScenarioRunLifecycleState.INITIALIZING)
        session = ScenarioExecutionSession(run_context=run_context, run_state=run_state)
        session.append_event(
            ExecutionEvent.create(
                event_type="run_initialized",
                run_state=run_state,
                phase=ExecutionPhase.RUN_INITIALIZATION,
                payload={
                    "scenario_path": str(run_context.scenario_path),
                    "compiled_plan_path": str(run_context.compiled_plan_path),
                    "started_at": run_context.started_at,
                },
            )
        )
        return session

    def execute(
        self,
        session: ScenarioExecutionSession,
        scenario_definition: ScenarioDefinition,
    ) -> ScenarioExecutionSession:
        compiled_scenario = self._compile_scenario(session, scenario_definition)
        if compiled_scenario is None:
            self._set_terminal_execution_outcome(session, scenario_definition)
            return session

        if not self._run_preflight(session, compiled_scenario):
            self._set_terminal_execution_outcome(session, scenario_definition)
            return session

        if not self._build_initial_context(session, compiled_scenario.scenario_definition):
            self._set_terminal_execution_outcome(session, scenario_definition)
            return session

        self._execute_steps(session, compiled_scenario.scenario_definition)
        self._set_terminal_execution_outcome(session, scenario_definition)
        return session

    def resume(
        self,
        session: ScenarioExecutionSession,
        scenario_definition: ScenarioDefinition,
        resume_request: ResumeRequest,
    ) -> ScenarioExecutionSession:
        pause_state = session.pause_state
        if pause_state is None:
            raise ValueError("Session is not paused and cannot be resumed.")
        if pause_state.resume_token != resume_request.resume_token:
            raise ValueError("Resume token does not match the paused run.")

        decision_resolution = resume_request.decision_resolution
        selected_action_id = (
            resume_request.selected_action_id
            if resume_request.selected_action_id is not None
            else None if decision_resolution is None else decision_resolution.selected_action_id
        )
        session.decision_resolution = decision_resolution
        session.continuation_state = RunContinuationState.RESUMED
        session.resumed_from_pause = True
        session.run_state.transition_to(ScenarioRunLifecycleState.RESUMING)
        session.append_event(
            ExecutionEvent.create(
                event_type="decision_resolved",
                run_state=session.run_state,
                phase=ExecutionPhase.RUN_INITIALIZATION,
                payload={
                    "decision_point_id": None if decision_resolution is None else decision_resolution.decision_point_id,
                    "selected_action_id": selected_action_id,
                    "resume_strategy": (
                        None
                        if decision_resolution is None
                        else decision_resolution.resume_strategy.value
                    ),
                },
            )
        )
        plan = self._resume_plan_from_request(session, pause_state, decision_resolution)
        self._apply_operator_step_termination(session, decision_resolution)
        if plan.prepare_from_step_index is not None:
            self._prepare_session_for_resume(session, scenario_definition, plan.prepare_from_step_index)

        if not plan.execute_steps:
            completed_step_count = self._completed_step_count(session)
            total_step_count = len(scenario_definition.steps)
            session.run_state.set_termination(
                RunTermination(
                    kind=RunTerminationKind.ABORTED,
                    reason=TerminationReason(
                        code="operator_aborted_run",
                        message="Operator selected abort for the paused run.",
                        source=TerminationReasonSource.OPERATOR,
                        phase=ExecutionPhase.RUN_INITIALIZATION,
                        details={
                            "selected_action_id": selected_action_id,
                            "resume_from_step_id": pause_state.resume_from_step_id,
                        },
                    ),
                    completion_disposition=completion_disposition(
                        executed_step_count=completed_step_count,
                        total_step_count=total_step_count,
                    ),
                    outcome_status=resolve_final_status(
                        [step_result.status for step_result in session.run_context.step_results]
                        + [outcome.status for outcome in session.compile_outcomes]
                        + [outcome.status for outcome in session.preflight_outcomes]
                    ),
                    abort_disposition=AbortDisposition.OPERATOR,
                    operator_resolution=(
                        None if decision_resolution is None else decision_resolution.to_dict()
                    ),
                    completed_step_count=completed_step_count,
                    total_step_count=total_step_count,
                )
            )
            session.append_event(
                ExecutionEvent.create(
                    event_type="run_aborted",
                    run_state=session.run_state,
                    phase=ExecutionPhase.RUN_INITIALIZATION,
                    payload={
                        "selected_action_id": selected_action_id,
                        "resume_strategy": (
                            None
                            if decision_resolution is None
                            else decision_resolution.resume_strategy.value
                        ),
                    },
                )
            )
            self._set_terminal_execution_outcome(session, scenario_definition)
            return session

        session.append_event(
            ExecutionEvent.create(
                event_type="run_resumed",
                run_state=session.run_state,
                phase=ExecutionPhase.RUN_INITIALIZATION,
                payload={
                    "resume_from_step_id": plan.resume_from_step_id,
                    "resume_from_step_index": plan.resume_from_step_index,
                    "selected_action_id": selected_action_id,
                    "resume_strategy": (
                        None
                        if decision_resolution is None
                        else decision_resolution.resume_strategy.value
                    ),
                },
            )
        )
        self._execute_steps(
            session,
            scenario_definition,
            start_step_index=plan.resume_from_step_index,
        )
        self._set_terminal_execution_outcome(session, scenario_definition)
        return session

    def _compile_scenario(
        self,
        session: ScenarioExecutionSession,
        scenario_definition: ScenarioDefinition,
    ) -> CompiledScenario | None:
        session.run_state.transition_to(ScenarioRunLifecycleState.COMPILING)
        compiled_scenario = self._compiler.compile(scenario_definition)
        session.compile_checks = compiled_scenario.compile_result.checks
        compile_outcome = ExecutionOutcome.from_status(
            compiled_scenario.compile_result.status,
            f"Scenario compilation completed with status {compiled_scenario.compile_result.status.value}.",
            phase=ExecutionPhase.COMPILATION,
            details={
                "required_external_inputs": [
                    item.to_dict() for item in compiled_scenario.compile_result.required_external_inputs
                ]
            },
        )
        session.append_event(
            ExecutionEvent.create(
                event_type="compilation_completed",
                run_state=session.run_state,
                phase=ExecutionPhase.COMPILATION,
                outcome=compile_outcome,
                issue=(
                    compiled_scenario.compile_result.issues[0]
                    if compiled_scenario.compile_result.issues
                    else None
                ),
                payload={
                    "checks": [check.to_dict() for check in session.compile_checks],
                    "required_external_inputs": [
                        item.to_dict() for item in compiled_scenario.compile_result.required_external_inputs
                    ],
                },
            )
        )
        session.compile_outcomes.append(compile_outcome)
        if compiled_scenario.compile_result.passed:
            return compiled_scenario

        for issue in compiled_scenario.compile_result.issues:
            session.add_issue(issue)
        return None

    def _run_preflight(
        self,
        session: ScenarioExecutionSession,
        compiled_scenario: CompiledScenario,
    ) -> bool:
        session.run_state.transition_to(ScenarioRunLifecycleState.PREFLIGHT_RUNNING)
        preflight_result = self._preflight_checker.run(compiled_scenario, session.run_context.workspace_root)
        session.preflight_checks = preflight_result.checks
        session.append_event(
            ExecutionEvent.create(
                event_type="preflight_completed",
                run_state=session.run_state,
                phase=ExecutionPhase.PREFLIGHT,
                outcome=ExecutionOutcome.from_status(
                    preflight_result.status,
                    f"Preflight completed with status {preflight_result.status.value}.",
                    phase=ExecutionPhase.PREFLIGHT,
                ),
                payload={"checks": [check.to_dict() for check in session.preflight_checks]},
            )
        )

        if preflight_result.passed:
            session.run_state.transition_to(ScenarioRunLifecycleState.READY)
            return True

        session.preflight_outcomes.append(
            ExecutionOutcome.from_status(
                preflight_result.status,
                f"Scenario preflight failed with status {preflight_result.status.value}.",
                phase=ExecutionPhase.PREFLIGHT,
            )
        )
        for check in preflight_result.failed_checks():
            session.add_issue(self._build_preflight_issue(check))
        return False

    def _build_initial_context(
        self,
        session: ScenarioExecutionSession,
        scenario_definition: ScenarioDefinition,
    ) -> bool:
        try:
            initial_variables = build_initial_variables(session.run_context, scenario_definition)
            session.run_context.variables = initial_variables.variables
            self._append_warning_issues(
                session=session,
                messages=initial_variables.warnings,
                phase=ExecutionPhase.INITIAL_CONTEXT,
                code_prefix="initial_context_warning",
            )
            session.append_event(
                ExecutionEvent.create(
                    event_type="initial_context_built",
                    run_state=session.run_state,
                    phase=ExecutionPhase.INITIAL_CONTEXT,
                    payload={
                        "variable_keys": sorted(session.run_context.variables.keys()),
                        "warnings": list(initial_variables.warnings),
                    },
                )
            )
            return True
        except VariableResolutionError as exc:
            self._append_warning_issues(
                session=session,
                messages=exc.warnings,
                phase=ExecutionPhase.INITIAL_CONTEXT,
                code_prefix="initial_context_warning",
            )
            issue = self._build_variable_issue(
                code="initial_context_resolution_blocked",
                message=str(exc),
                phase=ExecutionPhase.INITIAL_CONTEXT,
                exc=exc,
                step=scenario_definition.steps[0] if scenario_definition.steps else None,
                status=StepStatus.BLOCKED,
            )
            session.add_issue(issue)
            if scenario_definition.steps:
                blocked_result = self._build_initial_context_blocked_result(
                    scenario_definition.steps[0],
                    exc,
                )
                session.run_context.step_results.append(blocked_result)
                session.add_step_state(
                    StepExecutionState.from_step(scenario_definition.steps[0]).finish(
                        ExecutionOutcome.from_step_result(blocked_result, phase=ExecutionPhase.INITIAL_CONTEXT),
                        issues=[issue],
                    )
                )
            else:
                session.preflight_outcomes.append(
                    ExecutionOutcome.from_status(
                        StepStatus.BLOCKED,
                        str(exc),
                        phase=ExecutionPhase.INITIAL_CONTEXT,
                    )
                )
            session.append_event(
                ExecutionEvent.create(
                    event_type="initial_context_blocked",
                    run_state=session.run_state,
                    phase=ExecutionPhase.INITIAL_CONTEXT,
                    outcome=ExecutionOutcome.from_status(
                        StepStatus.BLOCKED,
                        str(exc),
                        phase=ExecutionPhase.INITIAL_CONTEXT,
                    ),
                    issue=issue,
                    payload={"unresolved_variables": list(exc.unresolved_variables)},
                )
            )
            return False
        except Exception as exc:  # noqa: BLE001
            issue = ExecutionIssue(
                code="initial_context_construction_failed",
                message=f"initial context construction failed: {exc}",
                phase=ExecutionPhase.INITIAL_CONTEXT,
                issue_type=ExecutionIssueKind.EXECUTION,
                outcome=StepStatus.ERROR,
                details={"error_type": type(exc).__name__},
            )
            session.add_issue(issue)
            session.preflight_outcomes.append(
                ExecutionOutcome.from_status(
                    StepStatus.ERROR,
                    issue.message,
                    phase=ExecutionPhase.INITIAL_CONTEXT,
                    details=issue.details,
                )
            )
            session.append_event(
                ExecutionEvent.create(
                    event_type="initial_context_failed",
                    run_state=session.run_state,
                    phase=ExecutionPhase.INITIAL_CONTEXT,
                    outcome=session.preflight_outcomes[-1],
                    issue=issue,
                )
            )
            return False

    def _execute_steps(
        self,
        session: ScenarioExecutionSession,
        scenario_definition: ScenarioDefinition,
        *,
        start_step_index: int = 0,
    ) -> None:
        for step_index in range(start_step_index, len(scenario_definition.steps)):
            step = scenario_definition.steps[step_index]
            step_reference = StepReference.from_step(step)
            session.run_state.transition_to(
                ScenarioRunLifecycleState.STEP_RUNNING,
                current_step=step_reference,
            )
            try:
                step_variables = resolve_step_variables(session.run_context, scenario_definition, step)
                session.run_context.variables = step_variables.variables
                self._append_warning_issues(
                    session=session,
                    messages=step_variables.warnings,
                    phase=ExecutionPhase.STEP_VARIABLE_RESOLUTION,
                    code_prefix="step_variable_warning",
                    step=step_reference,
                )
                step_executor = self._step_executor_factory.create(step, session.run_context.workspace_root)
                outcome = step_executor.execute(session.run_context, scenario_definition, step)
            except VariableResolutionError as exc:
                self._append_warning_issues(
                    session=session,
                    messages=exc.warnings,
                    phase=ExecutionPhase.STEP_VARIABLE_RESOLUTION,
                    code_prefix="step_variable_warning",
                    step=step_reference,
                )
                outcome = self._build_step_variable_blocked_outcome(step, exc)
            except Exception as exc:  # noqa: BLE001
                outcome = self._build_step_execution_error(step, exc)

            if outcome.step_result.status == StepStatus.PASS and outcome.captured_values:
                session.run_context.variables.update(outcome.captured_values)

            if outcome.step_result.status == StepStatus.PASS and outcome.tool_payload is not None:
                self._validate_expectations(session, step, step_reference, outcome)

            step_state = self._resolve_step_state(step, outcome)
            session.add_step_state(step_state)
            for issue in outcome.issues:
                session.add_issue(issue)

            session.run_context.step_results.append(outcome.step_result)
            if outcome.captured_values:
                session.run_context.variables.update(outcome.captured_values)

            session.append_event(
                ExecutionEvent.create(
                    event_type="step_completed",
                    run_state=session.run_state,
                    phase=self._step_outcome_phase(step_result=outcome.step_result, outcome=outcome),
                    step_state=step_state,
                    outcome=step_state.outcome,
                    issue=outcome.issues[0] if outcome.issues else None,
                    payload={
                        "message": outcome.step_result.message,
                        "captures": sorted(outcome.captured_values.keys()),
                        "expectation_statuses": [
                            expectation_result.status.value
                            for expectation_result in outcome.step_result.expectation_results
                        ],
                        **outcome.journal_details,
                    },
                )
            )

            if outcome.step_result.status != StepStatus.PASS:
                deferred_blocked_result = self._build_deferred_capture_blocked_result(
                    failed_step=step,
                    future_steps=scenario_definition.steps[step_index + 1 :],
                    available_variables=session.run_context.variables,
                )
                if deferred_blocked_result is not None:
                    deferred_issue = ExecutionIssue(
                        code="deferred_capture_blocked",
                        message=deferred_blocked_result.message,
                        phase=ExecutionPhase.CAPTURE,
                        issue_type=ExecutionIssueKind.VALIDATION,
                        outcome=StepStatus.BLOCKED,
                        step=StepReference(
                            step_id=deferred_blocked_result.step_id,
                            step_number=deferred_blocked_result.step_number,
                            step_type=deferred_blocked_result.step_type,
                        ),
                        details=dict(deferred_blocked_result.details),
                    )
                    session.run_context.step_results.append(deferred_blocked_result)
                    session.add_issue(deferred_issue)
                    session.add_step_state(
                        StepExecutionState(
                            step=deferred_issue.step,
                            lifecycle_state=StepExecutionLifecycleState.FINISHED,
                            outcome=ExecutionOutcome.from_step_result(
                                deferred_blocked_result,
                                phase=ExecutionPhase.CAPTURE,
                            ),
                            termination=StepTermination(
                                kind=StepTerminationKind.BLOCKED,
                                reason=TerminationReason(
                                    code="deferred_capture_blocked",
                                    message=deferred_blocked_result.message,
                                    source=TerminationReasonSource.EXECUTION,
                                    phase=ExecutionPhase.CAPTURE,
                                    details=dict(deferred_blocked_result.details),
                                ),
                                outcome_status=StepStatus.BLOCKED,
                            ),
                            issues=[deferred_issue],
                        )
                    )
                break

            session.run_state.transition_to(ScenarioRunLifecycleState.READY)

    def _prepare_session_for_resume(
        self,
        session: ScenarioExecutionSession,
        scenario_definition: ScenarioDefinition,
        resume_from_step_index: int,
    ) -> None:
        rerun_step_ids = {
            step.step_id for step in scenario_definition.steps[resume_from_step_index:]
        }
        session.run_context.step_results = [
            result for result in session.run_context.step_results if result.step_id not in rerun_step_ids
        ]
        session.run_state.step_states = [
            step_state
            for step_state in session.run_state.step_states
            if step_state.step.step_id not in rerun_step_ids
        ]
        session.tooling_issues = [
            issue
            for issue in session.tooling_issues
            if issue.step is None or issue.step.step_id not in rerun_step_ids
        ]
        session.run_state.issues = [
            issue
            for issue in session.run_state.issues
            if issue.step is None or issue.step.step_id not in rerun_step_ids
        ]
        session.run_state.current_step = None
        session.run_state.final_outcome = None
        session.run_state.termination = None

    @staticmethod
    def _resume_plan_from_request(
        session: ScenarioExecutionSession,
        pause_state,
        decision_resolution,
    ):
        from dataclasses import dataclass

        from ..domain.manual import ResumeStrategy

        @dataclass(frozen=True, slots=True)
        class _ResumePlan:
            prepare_from_step_index: int | None
            resume_from_step_index: int
            resume_from_step_id: str
            execute_steps: bool

        if decision_resolution is None:
            return _ResumePlan(
                prepare_from_step_index=pause_state.resume_from_step_index,
                resume_from_step_index=pause_state.resume_from_step_index,
                resume_from_step_id=pause_state.resume_from_step_id,
                execute_steps=True,
            )

        selected_action = decision_resolution.selected_action
        if decision_resolution.resume_strategy == ResumeStrategy.ABORT:
            return _ResumePlan(
                prepare_from_step_index=None,
                resume_from_step_index=pause_state.resume_from_step_index,
                resume_from_step_id=pause_state.resume_from_step_id,
                execute_steps=False,
            )

        target_step_index = (
            pause_state.resume_from_step_index
            if selected_action.target_step_index is None
            else selected_action.target_step_index
        )
        target_step_id = selected_action.target_step_id or pause_state.resume_from_step_id

        if decision_resolution.resume_strategy == ResumeStrategy.CONTINUE_FROM_NEXT_STEP:
            return _ResumePlan(
                prepare_from_step_index=target_step_index + 1,
                resume_from_step_index=target_step_index + 1,
                resume_from_step_id=target_step_id,
                execute_steps=True,
            )

        return _ResumePlan(
            prepare_from_step_index=target_step_index,
            resume_from_step_index=target_step_index,
            resume_from_step_id=target_step_id,
            execute_steps=True,
        )

    def _validate_expectations(
        self,
        session: ScenarioExecutionSession,
        step: ScenarioStep,
        step_reference: StepReference,
        outcome: StepExecutionOutcome,
    ) -> None:
        try:
            expectation_results = self._step_validator.validate(
                step,
                outcome.tool_payload,
                variables=session.run_context.variables,
            )
            outcome.step_result.expectation_results.extend(expectation_results)
            validation_status = self._step_validator.final_status(expectation_results)
            if validation_status != StepStatus.PASS:
                non_pass_expectation = next(
                    expectation_result
                    for expectation_result in expectation_results
                    if expectation_result.status != StepStatus.PASS
                )
                outcome.step_result.status = validation_status
                outcome.step_result.message = (
                    f"Expectation {validation_status.value.lower()}: {non_pass_expectation.rule}"
                )
                outcome.issues.append(
                    ExecutionIssue(
                        code="step_expectation_non_pass",
                        message=outcome.step_result.message,
                        phase=ExecutionPhase.EXPECTATION_VALIDATION,
                        issue_type=ExecutionIssueKind.VALIDATION,
                        outcome=validation_status,
                        step=step_reference,
                        details={"rule": non_pass_expectation.rule},
                    )
                )
        except ExpectationValidationError as exc:
            outcome.step_result.status = StepStatus.BLOCKED
            outcome.step_result.message = str(exc)
            outcome.issues.append(
                ExecutionIssue(
                    code="expectation_validation_blocked",
                    message=str(exc),
                    phase=ExecutionPhase.EXPECTATION_VALIDATION,
                    issue_type=ExecutionIssueKind.VALIDATION,
                    outcome=StepStatus.BLOCKED,
                    step=step_reference,
                )
            )
        except Exception as exc:  # noqa: BLE001
            outcome.step_result.status = StepStatus.ERROR
            outcome.step_result.message = f"Expectation validation failed: {exc}"
            outcome.issues.append(
                ExecutionIssue(
                    code="expectation_validation_failed",
                    message=outcome.step_result.message,
                    phase=ExecutionPhase.EXPECTATION_VALIDATION,
                    issue_type=ExecutionIssueKind.VALIDATION,
                    outcome=StepStatus.ERROR,
                    step=step_reference,
                )
            )

    def _set_terminal_execution_outcome(
        self,
        session: ScenarioExecutionSession,
        scenario_definition: ScenarioDefinition,
    ) -> None:
        compile_failed = any(outcome.status != StepStatus.PASS for outcome in session.compile_outcomes)
        final_status = resolve_final_status(
            [step_result.status for step_result in session.run_context.step_results]
            + [outcome.status for outcome in session.compile_outcomes]
            + [outcome.status for outcome in session.preflight_outcomes]
        )
        executed_step_count = len(session.run_context.step_results)
        total_step_count = len(scenario_definition.steps)

        if compile_failed:
            message = f"Scenario compilation failed with status {final_status.value}."
        elif session.preflight_outcomes and final_status != StepStatus.PASS:
            message = f"Scenario preflight failed with status {final_status.value}."
        elif not session.run_context.step_results:
            message = "Scenario run initialized. Scenario execution is not implemented yet."
        elif final_status == StepStatus.PASS and executed_step_count == total_step_count:
            message = "Scenario execution completed."
        elif final_status == StepStatus.PASS:
            message = "Scenario execution ended before all steps were run."
        else:
            message = f"Scenario execution stopped with status {final_status.value}."

        session.run_state.set_final_outcome(
            ExecutionOutcome.from_status(
                final_status,
                message,
                phase=self._terminal_phase(session),
            )
        )
        if session.run_state.termination is None:
            session.run_state.set_termination(
                self._build_run_termination(
                    session=session,
                    scenario_definition=scenario_definition,
                    final_status=final_status,
                    message=message,
                )
            )

    def _build_run_termination(
        self,
        *,
        session: ScenarioExecutionSession,
        scenario_definition: ScenarioDefinition,
        final_status: StepStatus,
        message: str,
    ) -> RunTermination:
        phase = self._terminal_phase(session)
        completed_step_count = self._completed_step_count(session)
        total_step_count = len(scenario_definition.steps)
        return RunTermination(
            kind=run_termination_kind_from_status(final_status),
            reason=TerminationReason(
                code=self._terminal_reason_code(session, final_status),
                message=message,
                source=self._terminal_reason_source(session, phase),
                phase=phase,
            ),
            completion_disposition=completion_disposition(
                executed_step_count=completed_step_count,
                total_step_count=total_step_count,
            ),
            outcome_status=final_status,
            operator_resolution=(
                None if session.decision_resolution is None else session.decision_resolution.to_dict()
            ),
            completed_step_count=completed_step_count,
            total_step_count=total_step_count,
        )

    @staticmethod
    def _completed_step_count(session: ScenarioExecutionSession) -> int:
        return sum(1 for step_result in session.run_context.step_results if step_result.status == StepStatus.PASS)

    @staticmethod
    def _terminal_reason_code(session: ScenarioExecutionSession, final_status: StepStatus) -> str:
        if session.tooling_issues:
            return session.tooling_issues[-1].code
        if session.compile_outcomes and any(outcome.status != StepStatus.PASS for outcome in session.compile_outcomes):
            return "compilation_stopped"
        if session.preflight_outcomes and final_status != StepStatus.PASS:
            return "preflight_stopped"
        return f"run_{run_termination_kind_from_status(final_status).value}"

    @staticmethod
    def _terminal_reason_source(
        session: ScenarioExecutionSession,
        phase: ExecutionPhase,
    ) -> TerminationReasonSource:
        if session.decision_resolution is not None:
            return TerminationReasonSource.OPERATOR
        if phase == ExecutionPhase.COMPILATION:
            return TerminationReasonSource.COMPILATION
        if phase == ExecutionPhase.PREFLIGHT:
            return TerminationReasonSource.PREFLIGHT
        if phase == ExecutionPhase.FINALIZATION:
            return TerminationReasonSource.FINALIZATION
        if session.tooling_issues and session.tooling_issues[-1].issue_type == ExecutionIssueKind.TOOLING:
            return TerminationReasonSource.RUNTIME
        return TerminationReasonSource.EXECUTION

    @staticmethod
    def _apply_operator_step_termination(
        session: ScenarioExecutionSession,
        decision_resolution: "DecisionResolution | None",
    ) -> None:
        if decision_resolution is None:
            return
        if decision_resolution.selected_action.action_type.value != "skip_step":
            return

        selected_action = decision_resolution.selected_action
        target_step_id = selected_action.target_step_id
        target_step_index = selected_action.target_step_index
        if target_step_id is None and target_step_index is not None:
            for step_state in session.run_state.step_states:
                if step_state.step.step_number == target_step_index + 1:
                    target_step_id = step_state.step.step_id
                    break
        if target_step_id is None:
            return

        for index, step_state in enumerate(session.run_state.step_states):
            if step_state.step.step_id != target_step_id:
                continue
            outcome_status = None if step_state.outcome is None else step_state.outcome.status
            session.run_state.step_states[index] = step_state.with_termination(
                StepTermination(
                    kind=StepTerminationKind.SKIPPED,
                    reason=TerminationReason(
                        code="operator_skipped_step",
                        message="Operator selected skip for this paused step.",
                        source=TerminationReasonSource.OPERATOR,
                        phase=None if step_state.outcome is None else step_state.outcome.phase,
                        details={"selected_action_id": decision_resolution.selected_action_id},
                    ),
                    outcome_status=outcome_status,
                    skip_disposition=SkipDisposition.OPERATOR,
                    operator_resolution=decision_resolution.to_dict(),
                )
            )
            session.append_event(
                ExecutionEvent.create(
                    event_type="step_skipped",
                    run_state=session.run_state,
                    phase=ExecutionPhase.RUN_INITIALIZATION,
                    step_state=session.run_state.step_states[index],
                    payload={
                        "skip_disposition": SkipDisposition.OPERATOR.value,
                        "selected_action_id": decision_resolution.selected_action_id,
                    },
                )
            )
            return

    @staticmethod
    def _terminal_phase(session: ScenarioExecutionSession) -> ExecutionPhase:
        if session.tooling_issues:
            return session.tooling_issues[-1].phase
        if session.run_context.step_results:
            raw_phase = session.run_context.step_results[-1].details.get("phase")
            if isinstance(raw_phase, str):
                try:
                    return ExecutionPhase(raw_phase)
                except ValueError:
                    pass
            return ExecutionPhase.STEP_EXECUTION
        if session.preflight_checks:
            return ExecutionPhase.PREFLIGHT
        if session.compile_checks:
            return ExecutionPhase.COMPILATION
        return ExecutionPhase.PREFLIGHT

    @staticmethod
    def _build_preflight_issue(check: PreflightCheckResult) -> ExecutionIssue:
        message = check.message
        errors = check.details.get("errors")
        if isinstance(errors, list) and errors:
            message = f"{message} {'; '.join(str(error) for error in errors)}"
        missing_variables = check.details.get("missing_variables")
        if isinstance(missing_variables, list) and missing_variables:
            message = f"{message} Missing variables: {', '.join(str(item) for item in missing_variables)}."
        return ExecutionIssue(
            code=f"preflight_{check.name}",
            message=message,
            phase=ExecutionPhase.PREFLIGHT,
            issue_type=ExecutionIssueKind.PREFLIGHT,
            outcome=check.status,
            details=check.to_dict(),
        )

    @staticmethod
    def _build_variable_issue(
        *,
        code: str,
        message: str,
        phase: ExecutionPhase,
        exc: VariableResolutionError,
        step: ScenarioStep | None,
        status: StepStatus,
    ) -> ExecutionIssue:
        return ExecutionIssue(
            code=code,
            message=message,
            phase=phase,
            issue_type=ExecutionIssueKind.VALIDATION,
            outcome=status,
            step=None if step is None else StepReference.from_step(step),
            details={"unresolved_variables": list(exc.unresolved_variables)},
        )

    @staticmethod
    def _append_warning_issues(
        session: ScenarioExecutionSession,
        messages: list[str],
        phase: ExecutionPhase,
        code_prefix: str,
        step: StepReference | None = None,
    ) -> None:
        existing = {
            (issue.phase, issue.message, issue.step.step_id if issue.step else None)
            for issue in session.tooling_issues
        }
        for index, message in enumerate(messages, start=1):
            key = (phase, message, step.step_id if step else None)
            if key in existing:
                continue
            session.add_issue(
                ExecutionIssue(
                    code=f"{code_prefix}_{index}",
                    message=message,
                    phase=phase,
                    issue_type=ExecutionIssueKind.WARNING,
                    step=step,
                )
            )
            existing.add(key)

    @staticmethod
    def _build_step_execution_error(step: ScenarioStep, exc: Exception) -> StepExecutionOutcome:
        step_result = StepExecutionResult(
            step_id=step.step_id,
            step_number=step.step_number,
            step_type=step.step_type,
            status=StepStatus.ERROR,
            message=f"Step execution failed: {exc}",
            details={"phase": ExecutionPhase.STEP_EXECUTION.value},
        )
        issue = ExecutionIssue(
            code="step_execution_failed",
            message=step_result.message,
            phase=ExecutionPhase.STEP_EXECUTION,
            issue_type=ExecutionIssueKind.EXECUTION,
            outcome=StepStatus.ERROR,
            step=StepReference.from_step(step),
        )
        return StepExecutionOutcome(
            step_result=step_result,
            journal_details={"phase": ExecutionPhase.STEP_EXECUTION.value},
            execution_state=StepExecutionState.from_step(step).finish(
                ExecutionOutcome.from_step_result(step_result, phase=ExecutionPhase.STEP_EXECUTION),
                issues=[issue],
            ),
            issues=[issue],
        )

    @staticmethod
    def _build_initial_context_blocked_result(
        step: ScenarioStep,
        exc: VariableResolutionError,
    ) -> StepExecutionResult:
        return StepExecutionResult(
            step_id=step.step_id,
            step_number=step.step_number,
            step_type=step.step_type,
            status=StepStatus.BLOCKED,
            message=f"Initial variable resolution blocked: {exc}",
            details={
                "phase": ExecutionPhase.INITIAL_CONTEXT.value,
                "unresolved_variables": list(exc.unresolved_variables),
            },
        )

    @staticmethod
    def _build_step_variable_blocked_result(
        step: ScenarioStep,
        exc: VariableResolutionError,
    ) -> StepExecutionResult:
        return StepExecutionResult(
            step_id=step.step_id,
            step_number=step.step_number,
            step_type=step.step_type,
            status=StepStatus.BLOCKED,
            message=f"Step variable resolution blocked: {exc}",
            details={
                "phase": ExecutionPhase.STEP_VARIABLE_RESOLUTION.value,
                "unresolved_variables": list(exc.unresolved_variables),
            },
        )

    def _build_step_variable_blocked_outcome(
        self,
        step: ScenarioStep,
        exc: VariableResolutionError,
    ) -> StepExecutionOutcome:
        step_result = self._build_step_variable_blocked_result(step, exc)
        issue = self._build_variable_issue(
            code="step_variable_resolution_blocked",
            message=str(exc),
            phase=ExecutionPhase.STEP_VARIABLE_RESOLUTION,
            exc=exc,
            step=step,
            status=StepStatus.BLOCKED,
        )
        return StepExecutionOutcome(
            step_result=step_result,
            journal_details={"phase": ExecutionPhase.STEP_VARIABLE_RESOLUTION.value},
            execution_state=StepExecutionState.from_step(step).finish(
                ExecutionOutcome.from_step_result(step_result, phase=ExecutionPhase.STEP_VARIABLE_RESOLUTION),
                issues=[issue],
            ),
            issues=[issue],
        )

    @classmethod
    def _build_deferred_capture_blocked_result(
        cls,
        failed_step: ScenarioStep,
        future_steps: list[ScenarioStep],
        available_variables: dict,
    ) -> StepExecutionResult | None:
        failed_capture_names = cls._capture_variable_names(failed_step) - set(available_variables)
        if not failed_capture_names:
            return None

        for future_step in future_steps:
            future_placeholders = cls._step_placeholder_names(future_step)
            missing_capture_names = sorted(failed_capture_names & future_placeholders)
            if not missing_capture_names:
                continue
            return StepExecutionResult(
                step_id=future_step.step_id,
                step_number=future_step.step_number,
                step_type=future_step.step_type,
                status=StepStatus.BLOCKED,
                message=(
                    f"Step blocked because required captured variable(s) were not produced by "
                    f"{failed_step.step_id}: {', '.join(missing_capture_names)}."
                ),
                details={
                    "phase": "deferred_capture",
                    "producer_step_id": failed_step.step_id,
                    "unresolved_variables": missing_capture_names,
                },
            )
        return None

    @staticmethod
    def _capture_variable_names(step: ScenarioStep) -> set[str]:
        capture_rules = []
        if step.api is not None:
            capture_rules.extend(step.api.capture)
        if step.db is not None:
            capture_rules.extend(step.db.capture)

        variable_names: set[str] = set()
        for capture_rule in capture_rules:
            if "->" not in capture_rule:
                continue
            variable_name = capture_rule.split("->", 1)[1].strip()
            if variable_name:
                variable_names.add(variable_name)
        return variable_names

    @staticmethod
    def _step_placeholder_names(step: ScenarioStep) -> set[str]:
        from ..runtime.variables import _collect_placeholder_names

        names: set[str] = set()
        if step.api is not None:
            names.update(_collect_placeholder_names(step.api.method))
            names.update(_collect_placeholder_names(step.api.path))
            names.update(_collect_placeholder_names(step.api.headers))
            names.update(_collect_placeholder_names(step.api.params))
            names.update(_collect_placeholder_names(step.api.body))
            names.update(_collect_placeholder_names(step.api.retry))
        if step.db is not None:
            names.update(_collect_placeholder_names(step.db.sql))
            names.update(_collect_placeholder_names(step.db.params))
        return names

    @staticmethod
    def _resolve_step_state(step: ScenarioStep, outcome: StepExecutionOutcome) -> StepExecutionState:
        base_state = outcome.execution_state or StepExecutionState.from_step(step)
        return base_state.finish(
            ExecutionOutcome.from_step_result(
                outcome.step_result,
                phase=ScenarioExecutionEngine._step_outcome_phase(
                    step_result=outcome.step_result,
                    outcome=outcome,
                ),
            ),
            issues=outcome.issues,
        )

    @staticmethod
    def _step_outcome_phase(step_result: StepExecutionResult, outcome: StepExecutionOutcome) -> ExecutionPhase:
        if outcome.issues:
            return outcome.issues[-1].phase
        raw_phase = step_result.details.get("phase")
        if isinstance(raw_phase, str):
            try:
                return ExecutionPhase(raw_phase)
            except ValueError:
                pass
        return ExecutionPhase.STEP_EXECUTION
