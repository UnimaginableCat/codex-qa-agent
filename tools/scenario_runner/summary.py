"""Summary builders for the minimal scenario runner skeleton."""

from __future__ import annotations

from datetime import UTC, datetime
from tools.common.statuses import StepStatus

from .execution import ExecutionIssue, ExecutionOutcome, coerce_terminal_status, issue_messages
from .models import RunContext, ScenarioDefinition, ScenarioExecutionSummary


_STATUS_PRIORITY = {
    StepStatus.PASS: 0,
    StepStatus.FAIL: 1,
    StepStatus.BLOCKED: 2,
    StepStatus.ERROR: 3,
}


def build_scenario_summary(
    run_context: RunContext,
    scenario_definition: ScenarioDefinition,
    report_path=None,
    extra_tooling_issues: list[str | ExecutionIssue] | None = None,
    finalization_statuses: list[StepStatus | ExecutionOutcome] | None = None,
    preflight_statuses: list[StepStatus | ExecutionOutcome] | None = None,
    preflight_checks: list[dict] | None = None,
) -> ScenarioExecutionSummary:
    step_results = list(run_context.step_results)
    parse_warnings = [str(item) for item in scenario_definition.metadata.get("parse_warnings", [])]
    warnings = parse_warnings + _tooling_messages(extra_tooling_issues or [])
    final_status = resolve_final_status(
        [step_result.status for step_result in step_results]
        + [coerce_terminal_status(status) for status in preflight_statuses or []]
        + [coerce_terminal_status(status) for status in finalization_statuses or []]
    )
    executed_step_count = len(step_results)
    total_step_count = len(scenario_definition.steps)

    if finalization_statuses and final_status == StepStatus.ERROR:
        message = "Scenario finalization failed with status ERROR."
    elif preflight_statuses and final_status != StepStatus.PASS:
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
        scenario=scenario_definition.scenario_name,
        project=scenario_definition.project,
        environment=scenario_definition.environment,
        run_id=run_context.run_id,
        scenario_path=run_context.scenario_path,
        final_status=final_status,
        message=message,
        run_state_dir=run_context.run_state_dir,
        artifact_dir=run_context.artifact_dir,
        report_path=report_path,
        started_at=run_context.started_at,
        finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
        steps=step_results,
        assumptions=_build_assumptions(scenario_definition),
        tooling_issues=_build_tooling_issues(
            scenario_definition=scenario_definition,
            step_results=step_results,
            extra_tooling_issues=extra_tooling_issues or [],
        ),
        code_analysis_used=False,
        details={
            "scenario_name": scenario_definition.scenario_name,
            "project": scenario_definition.project,
            "environment": scenario_definition.environment,
            "parsed_plan_dir": run_context.parsed_plans_dir,
            "compiled_plan_path": run_context.compiled_plan_path,
            "run_bundle_dir": run_context.artifact_dir,
            "bundle_manifest_path": run_context.artifact_dir / "manifest.json",
            "bundle_context_path": run_context.artifact_dir / "context.json",
            "bundle_summary_path": run_context.artifact_dir / "summary.json",
            "bundle_journal_path": run_context.artifact_dir / "journal.jsonl",
            "bundle_compiled_plan_path": run_context.artifact_dir / "compiled-plan.json",
            "step_count": total_step_count,
            "executed_step_count": executed_step_count,
            "preflight_statuses": [coerce_terminal_status(status).value for status in preflight_statuses or []],
            "preflight_checks": preflight_checks or [],
            "finalization_statuses": [coerce_terminal_status(status).value for status in finalization_statuses or []],
            "variable_keys": sorted(run_context.variables.keys()),
            "warnings": warnings,
            "artifact_policy": "Artifacts are immutable outputs/evidence only; never write source code into artifacts/.",
        },
    )


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
