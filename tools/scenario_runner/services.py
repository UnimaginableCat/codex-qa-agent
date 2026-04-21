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

        tooling_issues: list[str] = []
        finalization_statuses: list[StepStatus] = []
        preflight_statuses: list[StepStatus] = []
        preflight_checks: list[PreflightCheckResult] = []

        try:
            write_compiled_plan_json(run_context.compiled_plan_path, scenario_definition)
            write_bundle_compiled_plan_json(run_context, scenario_definition)
            write_context_json(run_context)
            write_journal_entry(
                run_context,
                {
                    "event": "run_initialized",
                    "run_id": run_context.run_id,
                    "scenario_path": str(run_context.scenario_path),
                    "compiled_plan_path": str(run_context.compiled_plan_path),
                    "started_at": run_context.started_at,
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                phase="initial run state persistence",
                exc=exc,
            )
            return self._finalize_run(
                run_context=run_context,
                scenario_definition=scenario_definition,
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                allow_report=False,
                preflight_statuses=preflight_statuses,
                preflight_checks=preflight_checks,
            )

        preflight_result = self._preflight_checker.run(scenario_definition, run_context.workspace_root)
        preflight_checks = preflight_result.checks
        if not self._try_write_journal(
            run_context,
            {
                "event": "preflight_completed",
                "run_id": run_context.run_id,
                "status": preflight_result.status.value,
                "checks": [check.to_dict() for check in preflight_checks],
            },
            tooling_issues,
            finalization_statuses,
            phase="preflight journal persistence",
        ):
            return self._finalize_run(
                run_context=run_context,
                scenario_definition=scenario_definition,
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                allow_report=False,
                preflight_statuses=preflight_statuses,
                preflight_checks=preflight_checks,
            )

        if not preflight_result.passed:
            preflight_statuses.append(preflight_result.status)
            tooling_issues.extend(preflight_result.issue_messages())
            step_summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                preflight_statuses=preflight_statuses,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            self._try_write_summary(run_context, step_summary, tooling_issues, finalization_statuses)
            return self._finalize_run(
                run_context=run_context,
                scenario_definition=scenario_definition,
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                allow_report=True,
                preflight_statuses=preflight_statuses,
                preflight_checks=preflight_checks,
            )

        try:
            initial_variables = build_initial_variables(run_context, scenario_definition)
            run_context.variables = initial_variables.variables
            tooling_issues.extend(initial_variables.warnings)
            write_context_json(run_context)
            write_journal_entry(
                run_context,
                {
                    "event": "initial_context_built",
                    "run_id": run_context.run_id,
                    "variable_keys": sorted(run_context.variables.keys()),
                    "warnings": list(initial_variables.warnings),
                },
            )
        except VariableResolutionError as exc:
            tooling_issues.extend(exc.warnings)
            if scenario_definition.steps:
                blocked_result = self._build_initial_context_blocked_result(
                    scenario_definition.steps[0],
                    exc,
                )
                run_context.step_results.append(blocked_result)
            else:
                preflight_statuses.append(StepStatus.BLOCKED)
            tooling_issues.append(str(exc))
            self._try_write_context(run_context, tooling_issues, finalization_statuses)
            step_summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                preflight_statuses=preflight_statuses,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            self._try_write_summary(run_context, step_summary, tooling_issues, finalization_statuses)
            return self._finalize_run(
                run_context=run_context,
                scenario_definition=scenario_definition,
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                allow_report=True,
                preflight_statuses=preflight_statuses,
                preflight_checks=preflight_checks,
            )
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                phase="initial context construction",
                exc=exc,
            )
            return self._finalize_run(
                run_context=run_context,
                scenario_definition=scenario_definition,
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                allow_report=True,
                preflight_statuses=preflight_statuses,
                preflight_checks=preflight_checks,
            )

        for step_index, step in enumerate(scenario_definition.steps):
            try:
                step_variables = resolve_step_variables(run_context, scenario_definition, step)
                run_context.variables = step_variables.variables
                self._extend_unique(tooling_issues, step_variables.warnings)
                step_executor = self._step_executor_factory.create(step, run_context.workspace_root)
                outcome = step_executor.execute(run_context, scenario_definition, step)
            except VariableResolutionError as exc:
                self._extend_unique(tooling_issues, exc.warnings)
                outcome = StepExecutionOutcome(
                    step_result=self._build_step_variable_blocked_result(step, exc),
                    journal_details={"phase": "step_variable_resolution"},
                )
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
                except ExpectationValidationError as exc:
                    outcome.step_result.status = StepStatus.BLOCKED
                    outcome.step_result.message = str(exc)
                except Exception as exc:  # noqa: BLE001
                    outcome.step_result.status = StepStatus.ERROR
                    outcome.step_result.message = f"Expectation validation failed: {exc}"

            run_context.step_results.append(outcome.step_result)
            if outcome.captured_values:
                run_context.variables.update(outcome.captured_values)
            if not self._try_write_context(run_context, tooling_issues, finalization_statuses):
                break

            step_summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                preflight_statuses=preflight_statuses,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            if not self._try_write_summary(run_context, step_summary, tooling_issues, finalization_statuses):
                break
            if not self._try_write_journal(
                run_context,
                {
                    "event": "step_completed",
                    "run_id": run_context.run_id,
                    "step_id": step.step_id,
                    "step_number": step.step_number,
                    "step_type": step.step_type.value,
                    "status": outcome.step_result.status.value,
                    "message": outcome.step_result.message,
                    "captures": sorted(outcome.captured_values.keys()),
                    "expectation_statuses": [
                        expectation_result.status.value
                        for expectation_result in outcome.step_result.expectation_results
                    ],
                    **outcome.journal_details,
                },
                tooling_issues,
                finalization_statuses,
                phase="step journal persistence",
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
                    self._try_write_context(run_context, tooling_issues, finalization_statuses)
                break

        return self._finalize_run(
            run_context=run_context,
            scenario_definition=scenario_definition,
            tooling_issues=tooling_issues,
            finalization_statuses=finalization_statuses,
            allow_report=True,
            preflight_statuses=preflight_statuses,
            preflight_checks=preflight_checks,
        )

    def _finalize_run(
        self,
        run_context: RunContext,
        scenario_definition: ScenarioDefinition,
        tooling_issues: list[str],
        finalization_statuses: list[StepStatus],
        allow_report: bool,
        preflight_statuses: list[StepStatus],
        preflight_checks: list[PreflightCheckResult],
    ) -> ScenarioExecutionSummary:
        summary = build_scenario_summary(
            run_context,
            scenario_definition,
            extra_tooling_issues=tooling_issues,
            finalization_statuses=finalization_statuses,
            preflight_statuses=preflight_statuses,
            preflight_checks=[check.to_dict() for check in preflight_checks],
        )

        if not allow_report:
            self._try_write_summary(run_context, summary, tooling_issues, finalization_statuses)
            return build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                preflight_statuses=preflight_statuses,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )

        try:
            report_path = create_report_path(run_context)
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                phase="report artifact path creation",
                exc=exc,
            )
            summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                preflight_statuses=preflight_statuses,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            self._try_write_journal(
                run_context,
                {
                    "event": "run_finished",
                    "run_id": run_context.run_id,
                    "status": summary.final_status.value,
                    "message": summary.message,
                    "executed_step_count": len(run_context.step_results),
                    "report_path": None,
                },
                tooling_issues,
                finalization_statuses,
                phase="final error journal persistence",
            )
            self._try_write_summary(run_context, summary, tooling_issues, finalization_statuses)
            return summary

        summary = build_scenario_summary(
            run_context,
            scenario_definition,
            report_path=report_path,
            extra_tooling_issues=tooling_issues,
            finalization_statuses=finalization_statuses,
            preflight_statuses=preflight_statuses,
            preflight_checks=[check.to_dict() for check in preflight_checks],
        )
        if not self._try_write_summary(run_context, summary, tooling_issues, finalization_statuses):
            return build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                preflight_statuses=preflight_statuses,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )

        if not self._try_write_journal(
            run_context,
            {
                "event": "run_finished",
                "run_id": run_context.run_id,
                "status": summary.final_status.value,
                "message": summary.message,
                "executed_step_count": len(run_context.step_results),
                "report_path": str(report_path),
            },
            tooling_issues,
            finalization_statuses,
            phase="final journal persistence",
        ):
            summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                preflight_statuses=preflight_statuses,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            self._try_write_summary(run_context, summary, tooling_issues, finalization_statuses)
            return summary

        try:
            self._build_report(run_context, scenario_definition, report_path)
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                phase="report generation",
                exc=exc,
            )
            summary = build_scenario_summary(
                run_context,
                scenario_definition,
                extra_tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                preflight_statuses=preflight_statuses,
                preflight_checks=[check.to_dict() for check in preflight_checks],
            )
            self._try_write_summary(run_context, summary, tooling_issues, finalization_statuses)
            return summary

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
        return StepExecutionOutcome(
            step_result=StepExecutionResult(
                step_id=step.step_id,
                step_number=step.step_number,
                step_type=step.step_type,
                status=StepStatus.ERROR,
                message=f"Step execution failed: {exc}",
                details={"phase": "step_execution"},
            ),
            journal_details={"phase": "step_execution"},
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
                "phase": "initial_context",
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
                "phase": "step_variable_resolution",
                "unresolved_variables": list(exc.unresolved_variables),
            },
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
        if step.db is not None:
            names.update(_collect_placeholder_names(step.db.sql))
            names.update(_collect_placeholder_names(step.db.params))
        return names

    @staticmethod
    def _record_finalization_error(
        tooling_issues: list[str],
        finalization_statuses: list[StepStatus],
        phase: str,
        exc: Exception,
    ) -> None:
        tooling_issues.append(f"{phase} failed: {exc}")
        finalization_statuses.append(StepStatus.ERROR)

    def _try_write_summary(
        self,
        run_context: RunContext,
        summary: ScenarioExecutionSummary,
        tooling_issues: list[str],
        finalization_statuses: list[StepStatus],
    ) -> bool:
        try:
            write_summary_json(run_context, summary)
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                phase="summary persistence",
                exc=exc,
            )
            return False

    @staticmethod
    def _extend_unique(target: list[str], values: list[str]) -> None:
        existing = set(target)
        for value in values:
            if value not in existing:
                target.append(value)
                existing.add(value)

    def _try_write_context(
        self,
        run_context: RunContext,
        tooling_issues: list[str],
        finalization_statuses: list[StepStatus],
    ) -> bool:
        try:
            write_context_json(run_context)
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                phase="context persistence",
                exc=exc,
            )
            return False

    def _try_write_journal(
        self,
        run_context: RunContext,
        entry: dict[str, object],
        tooling_issues: list[str],
        finalization_statuses: list[StepStatus],
        phase: str,
    ) -> bool:
        try:
            write_journal_entry(run_context, entry)
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_finalization_error(
                tooling_issues=tooling_issues,
                finalization_statuses=finalization_statuses,
                phase=phase,
                exc=exc,
            )
            return False
