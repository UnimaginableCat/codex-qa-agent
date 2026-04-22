"""Core orchestration engine for scenario execution."""

from __future__ import annotations

from dataclasses import dataclass, field

from tools.common.statuses import StepStatus

from .compiler import CompileCheckResult, CompiledScenario, ScenarioCompiler
from ..domain.execution import (
    ExecutionEvent,
    ExecutionIssue,
    ExecutionIssueKind,
    ExecutionOutcome,
    ExecutionPhase,
    ScenarioRunLifecycleState,
    ScenarioRunState,
    StepExecutionLifecycleState,
    StepExecutionState,
    StepReference,
)
from ..runtime.executors import StepExecutionOutcome, StepExecutorFactory
from ..domain.models import RunContext, ScenarioDefinition, ScenarioStep, StepExecutionResult
from .preflight import PreflightCheckResult, PreflightResult, ScenarioPreflightChecker
from ..projections.summary import resolve_final_status
from ..runtime.validators import ExpectationValidationError, ScenarioStepValidator
from ..runtime.variables import VariableResolutionError, build_initial_variables, resolve_step_variables


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
    ) -> None:
        for step_index, step in enumerate(scenario_definition.steps):
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
                            issues=[deferred_issue],
                        )
                    )
                break

            session.run_state.transition_to(ScenarioRunLifecycleState.READY)

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
