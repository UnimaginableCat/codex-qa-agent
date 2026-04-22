"""Services for the reusable scenario runner skeleton."""

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
from .execution import (
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
from .executors import StepExecutionOutcome, StepExecutorFactory
from .models import RunContext, ScenarioDefinition, ScenarioExecutionSummary, ScenarioStep, StepExecutionResult
from .preflight import PreflightCheckResult, ScenarioPreflightChecker
from .summary import build_scenario_summary
from .validators import ExpectationValidationError, ScenarioStepValidator
from .variables import VariableResolutionError, build_initial_variables, resolve_step_variables


class ScenarioRunnerService:
    """Initializes reusable scenario runner state from a parsed scenario definition."""

    def __init__(
        self,
        step_executor_factory: StepExecutorFactory | None = None,
        step_validator: ScenarioStepValidator | None = None,
        preflight_checker: ScenarioPreflightChecker | None = None,
    ) -> None:
        self._step_executor_factory = step_executor_factory or StepExecutorFactory()
        self._step_validator = step_validator or ScenarioStepValidator()
        self._preflight_checker = preflight_checker or ScenarioPreflightChecker()

    def run(
        self,
        scenario_definition: ScenarioDefinition,
        workspace_root: Path | None = None,
    ) -> ScenarioExecutionSummary:
        run_context = initialize_run_context(
            scenario_definition=scenario_definition,
            workspace_root=workspace_root,
        )
        run_state = ScenarioRunState(
            run_id=run_context.run_id,
            scenario_name=scenario_definition.scenario_name,
            scenario_path=run_context.scenario_path,
        )
        run_state.transition_to(ScenarioRunLifecycleState.INITIALIZING)

        tooling_issues: list[ExecutionIssue] = []
        finalization_outcomes: list[ExecutionOutcome] = []
        preflight_outcomes: list[ExecutionOutcome] = []
        preflight_checks: list[PreflightCheckResult] = []

        try:
            write_compiled_plan_json(run_context.compiled_plan_path, scenario_definition)
            write_bundle_compiled_plan_json(run_context, scenario_definition)
            write_context_json(run_context)
            write_journal_entry(
                run_context,
                ExecutionEvent.create(
                    event_type="run_initialized",
                    run_state=run_state,
                    phase=ExecutionPhase.RUN_INITIALIZATION,
                    payload={
                        "scenario_path": str(run_context.scenario_path),
                        "compiled_plan_path": str(run_context.compiled_plan_path),
                        "started_at": run_context.started_at,
                    },
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                run_state=run_state,
                phase=ExecutionPhase.PERSISTENCE,
                code="initial_run_state_persistence_failed",
                message="initial run state persistence failed",
                exc=exc,
            )
            return self._finalize_run(
                run_context=run_context,
                scenario_definition=scenario_definition,
                run_state=run_state,
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                allow_report=False,
                preflight_outcomes=preflight_outcomes,
                preflight_checks=preflight_checks,
            )

        run_state.transition_to(ScenarioRunLifecycleState.PREFLIGHT_RUNNING)
        preflight_result = self._preflight_checker.run(scenario_definition, run_context.workspace_root)
        preflight_checks = preflight_result.checks
        if not self._try_write_journal(
            run_context,
            ExecutionEvent.create(
                event_type="preflight_completed",
                run_state=run_state,
                phase=ExecutionPhase.PREFLIGHT,
                outcome=ExecutionOutcome.from_status(
                    preflight_result.status,
                    f"Preflight completed with status {preflight_result.status.value}.",
                    phase=ExecutionPhase.PREFLIGHT,
                ),
                payload={"checks": [check.to_dict() for check in preflight_checks]},
            ),
            tooling_issues,
            finalization_outcomes,
            run_state=run_state,
            phase=ExecutionPhase.PERSISTENCE,
            code="preflight_journal_persistence_failed",
            message="preflight journal persistence failed",
        ):
            return self._finalize_run(
                run_context=run_context,
                scenario_definition=scenario_definition,
                run_state=run_state,
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                allow_report=False,
                preflight_outcomes=preflight_outcomes,
                preflight_checks=preflight_checks,
            )

        if not preflight_result.passed:
            preflight_outcomes.append(
                ExecutionOutcome.from_status(
                    preflight_result.status,
                    f"Scenario preflight failed with status {preflight_result.status.value}.",
                    phase=ExecutionPhase.PREFLIGHT,
                )
            )
            for check in preflight_result.failed_checks():
                issue = self._build_preflight_issue(check)
                tooling_issues.append(issue)
                run_state.add_issue(issue)
            step_summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_outcomes,
                preflight_statuses=preflight_outcomes,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            self._try_write_summary(run_context, step_summary, tooling_issues, finalization_outcomes, run_state)
            return self._finalize_run(
                run_context=run_context,
                scenario_definition=scenario_definition,
                run_state=run_state,
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                allow_report=True,
                preflight_outcomes=preflight_outcomes,
                preflight_checks=preflight_checks,
            )

        run_state.transition_to(ScenarioRunLifecycleState.READY)
        try:
            initial_variables = build_initial_variables(run_context, scenario_definition)
            run_context.variables = initial_variables.variables
            self._append_warning_issues(
                target=tooling_issues,
                run_state=run_state,
                messages=initial_variables.warnings,
                phase=ExecutionPhase.INITIAL_CONTEXT,
                code_prefix="initial_context_warning",
            )
            write_context_json(run_context)
            write_journal_entry(
                run_context,
                ExecutionEvent.create(
                    event_type="initial_context_built",
                    run_state=run_state,
                    phase=ExecutionPhase.INITIAL_CONTEXT,
                    payload={
                        "variable_keys": sorted(run_context.variables.keys()),
                        "warnings": list(initial_variables.warnings),
                    },
                ),
            )
        except VariableResolutionError as exc:
            self._append_warning_issues(
                target=tooling_issues,
                run_state=run_state,
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
            tooling_issues.append(issue)
            run_state.add_issue(issue)
            if scenario_definition.steps:
                blocked_result = self._build_initial_context_blocked_result(
                    scenario_definition.steps[0],
                    exc,
                )
                run_context.step_results.append(blocked_result)
                run_state.add_step_state(
                    StepExecutionState.from_step(scenario_definition.steps[0]).finish(
                        ExecutionOutcome.from_step_result(blocked_result, phase=ExecutionPhase.INITIAL_CONTEXT),
                        issues=[issue],
                    )
                )
            else:
                preflight_outcomes.append(
                    ExecutionOutcome.from_status(
                        StepStatus.BLOCKED,
                        str(exc),
                        phase=ExecutionPhase.INITIAL_CONTEXT,
                    )
                )
            self._try_write_context(run_context, tooling_issues, finalization_outcomes, run_state)
            step_summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_outcomes,
                preflight_statuses=preflight_outcomes,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            self._try_write_summary(run_context, step_summary, tooling_issues, finalization_outcomes, run_state)
            return self._finalize_run(
                run_context=run_context,
                scenario_definition=scenario_definition,
                run_state=run_state,
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                allow_report=True,
                preflight_outcomes=preflight_outcomes,
                preflight_checks=preflight_checks,
            )
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                run_state=run_state,
                phase=ExecutionPhase.INITIAL_CONTEXT,
                code="initial_context_construction_failed",
                message="initial context construction failed",
                exc=exc,
            )
            return self._finalize_run(
                run_context=run_context,
                scenario_definition=scenario_definition,
                run_state=run_state,
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                allow_report=True,
                preflight_outcomes=preflight_outcomes,
                preflight_checks=preflight_checks,
            )

        for step_index, step in enumerate(scenario_definition.steps):
            step_reference = StepReference.from_step(step)
            run_state.transition_to(
                ScenarioRunLifecycleState.STEP_RUNNING,
                current_step=step_reference,
            )
            try:
                step_variables = resolve_step_variables(run_context, scenario_definition, step)
                run_context.variables = step_variables.variables
                self._append_warning_issues(
                    target=tooling_issues,
                    run_state=run_state,
                    messages=step_variables.warnings,
                    phase=ExecutionPhase.STEP_VARIABLE_RESOLUTION,
                    step=step_reference,
                    code_prefix="step_variable_warning",
                )
                step_executor = self._step_executor_factory.create(step, run_context.workspace_root)
                outcome = step_executor.execute(run_context, scenario_definition, step)
            except VariableResolutionError as exc:
                self._append_warning_issues(
                    target=tooling_issues,
                    run_state=run_state,
                    messages=exc.warnings,
                    phase=ExecutionPhase.STEP_VARIABLE_RESOLUTION,
                    step=step_reference,
                    code_prefix="step_variable_warning",
                )
                outcome = self._build_step_variable_blocked_outcome(step, exc)
            except Exception as exc:  # noqa: BLE001
                outcome = self._build_step_execution_error(step, exc)

            if outcome.step_result.status == StepStatus.PASS and outcome.captured_values:
                run_context.variables.update(outcome.captured_values)

            if outcome.step_result.status == StepStatus.PASS and outcome.tool_payload is not None:
                try:
                    expectation_results = self._step_validator.validate(
                        step,
                        outcome.tool_payload,
                        variables=run_context.variables,
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

            step_state = self._resolve_step_state(step, outcome)
            run_state.add_step_state(step_state)
            for issue in outcome.issues:
                tooling_issues.append(issue)
                run_state.add_issue(issue)

            run_context.step_results.append(outcome.step_result)
            if outcome.captured_values:
                run_context.variables.update(outcome.captured_values)
            if not self._try_write_context(run_context, tooling_issues, finalization_outcomes, run_state):
                break

            step_summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_outcomes,
                preflight_statuses=preflight_outcomes,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            if not self._try_write_summary(run_context, step_summary, tooling_issues, finalization_outcomes, run_state):
                break
            if not self._try_write_journal(
                run_context,
                ExecutionEvent.create(
                    event_type="step_completed",
                    run_state=run_state,
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
                ),
                tooling_issues,
                finalization_outcomes,
                run_state=run_state,
                phase=ExecutionPhase.PERSISTENCE,
                code="step_journal_persistence_failed",
                message="step journal persistence failed",
            ):
                break

            if outcome.step_result.status != StepStatus.PASS:
                deferred_blocked_result = self._build_deferred_capture_blocked_result(
                    failed_step=step,
                    future_steps=scenario_definition.steps[step_index + 1 :],
                    available_variables=run_context.variables,
                )
                if deferred_blocked_result is not None:
                    run_context.step_results.append(deferred_blocked_result)
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
                    tooling_issues.append(deferred_issue)
                    run_state.add_issue(deferred_issue)
                    run_state.add_step_state(
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
                    self._try_write_context(run_context, tooling_issues, finalization_outcomes, run_state)
                break
            run_state.transition_to(ScenarioRunLifecycleState.READY)

        return self._finalize_run(
            run_context=run_context,
            scenario_definition=scenario_definition,
            run_state=run_state,
            tooling_issues=tooling_issues,
            finalization_outcomes=finalization_outcomes,
            allow_report=True,
            preflight_outcomes=preflight_outcomes,
            preflight_checks=preflight_checks,
        )

    def _finalize_run(
        self,
        run_context: RunContext,
        scenario_definition: ScenarioDefinition,
        run_state: ScenarioRunState,
        tooling_issues: list[ExecutionIssue],
        finalization_outcomes: list[ExecutionOutcome],
        allow_report: bool,
        preflight_outcomes: list[ExecutionOutcome],
        preflight_checks: list[PreflightCheckResult],
    ) -> ScenarioExecutionSummary:
        run_state.transition_to(ScenarioRunLifecycleState.FINALIZING)
        summary = build_scenario_summary(
            run_context,
            scenario_definition,
            extra_tooling_issues=tooling_issues,
            finalization_statuses=finalization_outcomes,
            preflight_statuses=preflight_outcomes,
            preflight_checks=[check.to_dict() for check in preflight_checks],
        )

        if not allow_report:
            self._try_write_summary(run_context, summary, tooling_issues, finalization_outcomes, run_state)
            summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_outcomes,
                preflight_statuses=preflight_outcomes,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            run_state.set_final_outcome(
                ExecutionOutcome.from_status(
                    summary.final_status,
                    summary.message,
                    phase=ExecutionPhase.FINALIZATION,
                )
            )
            run_state.transition_to(ScenarioRunLifecycleState.FINISHED)
            return summary

        try:
            report_path = create_report_path(run_context)
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                run_state=run_state,
                phase=ExecutionPhase.REPORTING,
                code="report_artifact_path_creation_failed",
                message="report artifact path creation failed",
                exc=exc,
            )
            summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_outcomes,
                preflight_statuses=preflight_outcomes,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            self._try_write_journal(
                run_context,
                ExecutionEvent.create(
                    event_type="run_finished",
                    run_state=run_state,
                    phase=ExecutionPhase.FINALIZATION,
                    outcome=ExecutionOutcome.from_status(
                        summary.final_status,
                        summary.message,
                        phase=ExecutionPhase.FINALIZATION,
                    ),
                    issue=tooling_issues[-1] if tooling_issues else None,
                    payload={
                        "executed_step_count": len(run_context.step_results),
                        "report_path": None,
                    },
                ),
                tooling_issues,
                finalization_outcomes,
                run_state=run_state,
                phase=ExecutionPhase.PERSISTENCE,
                code="final_error_journal_persistence_failed",
                message="final error journal persistence failed",
            )
            self._try_write_summary(run_context, summary, tooling_issues, finalization_outcomes, run_state)
            run_state.set_final_outcome(
                ExecutionOutcome.from_status(
                    summary.final_status,
                    summary.message,
                    phase=ExecutionPhase.FINALIZATION,
                )
            )
            run_state.transition_to(ScenarioRunLifecycleState.FINISHED)
            return summary

        summary = build_scenario_summary(
            run_context,
            scenario_definition,
            report_path=report_path,
            extra_tooling_issues=tooling_issues,
            finalization_statuses=finalization_outcomes,
            preflight_statuses=preflight_outcomes,
            preflight_checks=[check.to_dict() for check in preflight_checks],
        )
        if not self._try_write_summary(run_context, summary, tooling_issues, finalization_outcomes, run_state):
            summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_outcomes,
                preflight_statuses=preflight_outcomes,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            run_state.set_final_outcome(
                ExecutionOutcome.from_status(
                    summary.final_status,
                    summary.message,
                    phase=ExecutionPhase.FINALIZATION,
                )
            )
            run_state.transition_to(ScenarioRunLifecycleState.FINISHED)
            return summary

        if not self._try_write_journal(
            run_context,
            ExecutionEvent.create(
                event_type="run_finished",
                run_state=run_state,
                phase=ExecutionPhase.FINALIZATION,
                outcome=ExecutionOutcome.from_status(
                    summary.final_status,
                    summary.message,
                    phase=ExecutionPhase.FINALIZATION,
                ),
                payload={
                    "executed_step_count": len(run_context.step_results),
                    "report_path": str(report_path),
                },
            ),
            tooling_issues,
            finalization_outcomes,
            run_state=run_state,
            phase=ExecutionPhase.PERSISTENCE,
            code="final_journal_persistence_failed",
            message="final journal persistence failed",
        ):
            summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_outcomes,
                preflight_statuses=preflight_outcomes,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            self._try_write_summary(run_context, summary, tooling_issues, finalization_outcomes, run_state)
            run_state.set_final_outcome(
                ExecutionOutcome.from_status(
                    summary.final_status,
                    summary.message,
                    phase=ExecutionPhase.FINALIZATION,
                )
            )
            run_state.transition_to(ScenarioRunLifecycleState.FINISHED)
            return summary

        try:
            self._build_report(run_context, scenario_definition, report_path)
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                run_state=run_state,
                phase=ExecutionPhase.REPORTING,
                code="report_generation_failed",
                message="report generation failed",
                exc=exc,
            )
            summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_outcomes,
                preflight_statuses=preflight_outcomes,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            self._try_write_summary(run_context, summary, tooling_issues, finalization_outcomes, run_state)
            run_state.set_final_outcome(
                ExecutionOutcome.from_status(
                    summary.final_status,
                    summary.message,
                    phase=ExecutionPhase.FINALIZATION,
                )
            )
            run_state.transition_to(ScenarioRunLifecycleState.FINISHED)
            return summary

        run_state.set_final_outcome(
            ExecutionOutcome.from_status(
                summary.final_status,
                summary.message,
                phase=ExecutionPhase.FINALIZATION,
            )
        )
        run_state.transition_to(ScenarioRunLifecycleState.FINISHED)
        return summary

    @staticmethod
    def _build_report(run_context: RunContext, scenario_definition: ScenarioDefinition, report_path: Path) -> Path:
        from tools.reports import build_service

        service = build_service()
        return service.build(
            project=scenario_definition.project,
            scenario=scenario_definition.scenario_name,
            summary_path=run_context.run_state_dir / "summary.json",
            output_path=report_path,
        )

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
        from .variables import _collect_placeholder_names

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
    def _build_preflight_issue(check: PreflightCheckResult) -> ExecutionIssue:
        message = check.message
        errors = check.details.get("errors")
        if isinstance(errors, list) and errors:
            message = f"{message} {'; '.join(str(error) for error in errors)}"
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

    def _record_finalization_error(
        self,
        tooling_issues: list[ExecutionIssue],
        finalization_outcomes: list[ExecutionOutcome],
        run_state: ScenarioRunState,
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
        tooling_issues.append(issue)
        run_state.add_issue(issue)
        finalization_outcomes.append(
            ExecutionOutcome.from_status(
                StepStatus.ERROR,
                issue.message,
                phase=phase,
                details=issue.details,
            )
        )

    @staticmethod
    def _append_warning_issues(
        target: list[ExecutionIssue],
        run_state: ScenarioRunState,
        messages: list[str],
        phase: ExecutionPhase,
        code_prefix: str,
        step: StepReference | None = None,
    ) -> None:
        existing = {(issue.phase, issue.message, issue.step.step_id if issue.step else None) for issue in target}
        for index, message in enumerate(messages, start=1):
            key = (phase, message, step.step_id if step else None)
            if key in existing:
                continue
            issue = ExecutionIssue(
                code=f"{code_prefix}_{index}",
                message=message,
                phase=phase,
                issue_type=ExecutionIssueKind.WARNING,
                step=step,
            )
            target.append(issue)
            run_state.add_issue(issue)
            existing.add(key)

    def _try_write_summary(
        self,
        run_context: RunContext,
        summary: ScenarioExecutionSummary,
        tooling_issues: list[ExecutionIssue],
        finalization_outcomes: list[ExecutionOutcome],
        run_state: ScenarioRunState,
    ) -> bool:
        try:
            write_summary_json(run_context, summary)
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                run_state=run_state,
                phase=ExecutionPhase.PERSISTENCE,
                code="summary_persistence_failed",
                message="summary persistence failed",
                exc=exc,
            )
            return False

    def _try_write_context(
        self,
        run_context: RunContext,
        tooling_issues: list[ExecutionIssue],
        finalization_outcomes: list[ExecutionOutcome],
        run_state: ScenarioRunState,
    ) -> bool:
        try:
            write_context_json(run_context)
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                run_state=run_state,
                phase=ExecutionPhase.PERSISTENCE,
                code="context_persistence_failed",
                message="context persistence failed",
                exc=exc,
            )
            return False

    def _try_write_journal(
        self,
        run_context: RunContext,
        entry: ExecutionEvent | dict[str, object],
        tooling_issues: list[ExecutionIssue],
        finalization_outcomes: list[ExecutionOutcome],
        run_state: ScenarioRunState,
        phase: ExecutionPhase,
        code: str,
        message: str,
    ) -> bool:
        try:
            write_journal_entry(run_context, entry)
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_outcomes=finalization_outcomes,
                run_state=run_state,
                phase=phase,
                code=code,
                message=message,
                exc=exc,
            )
            return False

    @staticmethod
    def _resolve_step_state(step: ScenarioStep, outcome: StepExecutionOutcome) -> StepExecutionState:
        base_state = outcome.execution_state or StepExecutionState.from_step(step)
        return base_state.finish(
            ExecutionOutcome.from_step_result(
                outcome.step_result,
                phase=ScenarioRunnerService._step_outcome_phase(
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
