"""Summary projections derived from execution read state."""

from __future__ import annotations

from datetime import UTC, datetime

from tools.common.statuses import StepStatus

from ..domain.execution import (
    ExecutionIssue,
    ExecutionIssueKind,
    ExecutionOutcome,
    ExecutionPhase,
    RunTerminationKind,
    coerce_terminal_status,
    issue_messages,
)
from ..domain.models import RunContext, ScenarioDefinition, ScenarioExecutionSummary
from ..domain.pause import RunContinuationState
from .guided import build_guided_projection
from .models import ExecutionProjectionState


_STATUS_PRIORITY = {
    StepStatus.PASS: 0,
    StepStatus.FAIL: 1,
    StepStatus.BLOCKED: 2,
    StepStatus.ERROR: 3,
}


def build_summary_projection(state: ExecutionProjectionState) -> ScenarioExecutionSummary:
    step_results = list(state.run_context.step_results)
    warnings = state.parse_warnings + _tooling_messages(list(state.tooling_issues))
    guided_projection = build_guided_projection(state)
    compile_failed = any(coerce_terminal_status(status) != StepStatus.PASS for status in state.compile_outcomes)
    final_status = resolve_final_status(
        [step_result.status for step_result in step_results]
        + [coerce_terminal_status(status) for status in state.compile_outcomes]
        + [coerce_terminal_status(status) for status in state.preflight_outcomes]
        + [coerce_terminal_status(status) for status in state.finalization_outcomes]
    )
    executed_step_count = len(step_results)
    total_step_count = len(state.scenario_definition.steps)
    run_termination = state.run_termination

    if run_termination is not None and run_termination.kind == RunTerminationKind.ABORTED:
        message = "Scenario execution ended after operator aborted the paused run."
    elif run_termination is not None and run_termination.kind == RunTerminationKind.PAUSED:
        message = f"Scenario execution paused with status {final_status.value}."
    elif state.resumed_from_pause and final_status == StepStatus.PASS and executed_step_count == total_step_count:
        message = "Scenario execution resumed and completed."
    elif state.finalization_outcomes and final_status == StepStatus.ERROR:
        message = "Scenario finalization failed with status ERROR."
    elif compile_failed:
        message = f"Scenario compilation failed with status {final_status.value}."
    elif state.preflight_outcomes and final_status != StepStatus.PASS:
        message = f"Scenario preflight failed with status {final_status.value}."
    elif not step_results:
        message = "Scenario run initialized. Scenario execution is not implemented yet."
    elif final_status == StepStatus.PASS and executed_step_count == total_step_count:
        message = "Scenario execution completed."
    elif final_status == StepStatus.PASS:
        message = "Scenario execution ended before all steps were run."
    else:
        message = f"Scenario execution stopped with status {final_status.value}."

    return ScenarioExecutionSummary(
        scenario=state.scenario_definition.scenario_name,
        project=state.scenario_definition.project,
        environment=state.scenario_definition.environment,
        run_id=state.run_context.run_id,
        scenario_path=state.run_context.scenario_path,
        final_status=final_status,
        message=message,
        run_state_dir=state.run_context.run_state_dir,
        artifact_dir=state.run_context.artifact_dir,
        report_path=state.report_path,
        started_at=state.run_context.started_at,
        finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
        steps=step_results,
        assumptions=_build_assumptions(state.scenario_definition),
        tooling_issues=_build_tooling_issues(
            scenario_definition=state.scenario_definition,
            step_results=step_results,
            extra_tooling_issues=list(state.tooling_issues),
        ),
        code_analysis_used=False,
        guided_diagnostics=list(guided_projection.diagnostics),
        guided_stop_reason=guided_projection.stop_reason,
        continuation_state=state.continuation_state,
        resumable=state.pause_state is not None and state.pause_state.resumable,
        resume_token=None if state.pause_state is None else state.pause_state.resume_token,
        pause_state_path=None if state.pause_state is None else state.pause_state.pause_state_path,
        available_operator_actions=(
            [] if state.pause_state is None else list(state.pause_state.available_operator_actions)
        ),
        decision_resolution=state.decision_resolution,
        resumed_from_pause=state.resumed_from_pause,
        details={
            "scenario_name": state.scenario_definition.scenario_name,
            "project": state.scenario_definition.project,
            "environment": state.scenario_definition.environment,
            "run_mode": state.run_mode.value,
            "parsed_plan_dir": state.run_context.parsed_plans_dir,
            "compiled_plan_path": state.run_context.compiled_plan_path,
            "run_bundle_dir": state.run_context.artifact_dir,
            "bundle_manifest_path": state.run_context.artifact_dir / "manifest.json",
            "bundle_context_path": state.run_context.artifact_dir / "context.json",
            "bundle_summary_path": state.run_context.artifact_dir / "summary.json",
            "bundle_journal_path": state.run_context.artifact_dir / "journal.jsonl",
            "bundle_compiled_plan_path": state.run_context.artifact_dir / "compiled-plan.json",
            "step_count": total_step_count,
            "executed_step_count": executed_step_count,
            "compile_statuses": [coerce_terminal_status(status).value for status in state.compile_outcomes],
            "compile_checks": list(state.compile_checks),
            "preflight_statuses": [coerce_terminal_status(status).value for status in state.preflight_outcomes],
            "preflight_checks": list(state.preflight_checks),
            "finalization_statuses": [
                coerce_terminal_status(status).value for status in state.finalization_outcomes
            ],
            "run_termination": None if run_termination is None else run_termination.to_dict(),
            "step_terminations": _step_terminations(state),
            "partial_completion": (
                False if run_termination is None else run_termination.completion_disposition.value == "partial"
            ),
            "completed_step_count": None if run_termination is None else run_termination.completed_step_count,
            "remaining_step_count": (
                None
                if run_termination is None
                else max(run_termination.total_step_count - run_termination.completed_step_count, 0)
            ),
            "legacy_status_projection": {
                "final_status": final_status.value,
                "source": "projection",
                "rule": "ERROR > BLOCKED > FAIL > PASS over execution, compile, preflight, and finalization outcomes",
            },
            "guided_diagnostics_count": len(guided_projection.diagnostics),
            "guided_decision_points_count": len(guided_projection.decision_points),
            "continuation_state": state.continuation_state.value,
            "resumable": state.pause_state is not None and state.pause_state.resumable,
            "available_operator_actions": (
                []
                if state.pause_state is None
                else [action.to_dict() for action in state.pause_state.available_operator_actions]
            ),
            "decision_resolution": (
                None if state.decision_resolution is None else state.decision_resolution.to_dict()
            ),
            "variable_keys": sorted(state.run_context.variables.keys()),
            "warnings": warnings,
            "artifact_policy": "Artifacts are immutable outputs/evidence only; never write source code into artifacts/.",
        },
    )


def build_scenario_summary(
    run_context: RunContext,
    scenario_definition: ScenarioDefinition,
    report_path=None,
    extra_tooling_issues: list[str | ExecutionIssue] | None = None,
    compile_statuses: list[StepStatus | ExecutionOutcome] | None = None,
    compile_checks: list[dict] | None = None,
    finalization_statuses: list[StepStatus | ExecutionOutcome] | None = None,
    preflight_statuses: list[StepStatus | ExecutionOutcome] | None = None,
    preflight_checks: list[dict] | None = None,
) -> ScenarioExecutionSummary:
    """Compatibility wrapper around the projection-first summary builder."""

    normalized_tooling_issues = [
        issue
        if isinstance(issue, ExecutionIssue)
        else ExecutionIssue(
            code="compatibility_tooling_issue",
            message=str(issue),
            phase=ExecutionPhase.FINALIZATION,
            issue_type=ExecutionIssueKind.TOOLING,
        )
        for issue in extra_tooling_issues or []
    ]

    state = ExecutionProjectionState(
        scenario_definition=scenario_definition,
        run_context=run_context,
        run_state=None,  # type: ignore[arg-type]
        tooling_issues=tuple(normalized_tooling_issues),
        compile_outcomes=tuple(
            status
            if isinstance(status, ExecutionOutcome)
            else ExecutionOutcome.from_status(status, f"Compilation ended with {status.value}.")
            for status in compile_statuses or []
        ),
        compile_checks=tuple(compile_checks or []),
        preflight_outcomes=tuple(
            status
            if isinstance(status, ExecutionOutcome)
            else ExecutionOutcome.from_status(status, f"Preflight ended with {status.value}.")
            for status in preflight_statuses or []
        ),
        preflight_checks=tuple(preflight_checks or []),
        finalization_outcomes=tuple(
            status
            if isinstance(status, ExecutionOutcome)
            else ExecutionOutcome.from_status(status, f"Finalization ended with {status.value}.")
            for status in finalization_statuses or []
        ),
        report_path=report_path,
        continuation_state=RunContinuationState.TERMINAL,
    )
    return build_summary_projection(state)


def resolve_final_status(statuses: list[StepStatus]) -> StepStatus:
    if not statuses:
        return StepStatus.PASS
    return max(statuses, key=_STATUS_PRIORITY.__getitem__)


def _build_assumptions(scenario_definition: ScenarioDefinition) -> list[str]:
    assumptions = [line.strip() for line in scenario_definition.notes.splitlines() if line.strip()]
    return assumptions


def _build_tooling_issues(
    scenario_definition: ScenarioDefinition,
    step_results: list,
    extra_tooling_issues: list[str | ExecutionIssue],
) -> list[str]:
    issues = _tooling_messages(extra_tooling_issues)
    issues.extend(str(item) for item in scenario_definition.metadata.get("parse_warnings", []))
    for step_result in step_results:
        if step_result.status in {StepStatus.ERROR, StepStatus.BLOCKED}:
            issues.append(f"{step_result.step_id}: {step_result.message}")
    return issues


def _tooling_messages(extra_tooling_issues: list[str | ExecutionIssue]) -> list[str]:
    typed_issues = [issue for issue in extra_tooling_issues if isinstance(issue, ExecutionIssue)]
    messages = issue_messages(typed_issues)
    messages.extend(str(issue) for issue in extra_tooling_issues if not isinstance(issue, ExecutionIssue))
    return messages


def _step_terminations(state: ExecutionProjectionState) -> list[dict]:
    if state.run_state is None:
        return []
    return [
        {
            "step": step_state.step.to_dict(),
            "termination": None if step_state.termination is None else step_state.termination.to_dict(),
        }
        for step_state in state.run_state.step_states
    ]
