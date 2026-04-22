"""Guided diagnostics projections derived from execution state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from tools.common.statuses import StepStatus

from ..domain.execution import ExecutionIssue, ExecutionPhase
from ..domain.guided import (
    ContinuationPolicy,
    DecisionPoint,
    GuidedAction,
    GuidedActionType,
    GuidedDiagnostic,
    GuidedDiagnosticTag,
)
from ..domain.models import ScenarioStepType, StepExecutionResult
from .models import ExecutionProjectionState, GuidedRunProjection


@dataclass(frozen=True, slots=True)
class _GuidedTemplate:
    title: str
    summary: str
    tags: tuple[GuidedDiagnosticTag, ...]
    continuation_policy: ContinuationPolicy
    actions: tuple[GuidedAction, ...]
    decision_point: DecisionPoint | None = None


def build_guided_projection(state: ExecutionProjectionState) -> GuidedRunProjection:
    diagnostics: list[GuidedDiagnostic] = []
    covered_steps = _covered_issue_steps(state.tooling_issues)

    for issue in state.tooling_issues:
        diagnostic = _diagnostic_from_issue(issue)
        if diagnostic is not None:
            diagnostics.append(diagnostic)

    for step_result in state.step_results:
        if step_result.status == StepStatus.PASS:
            continue
        if step_result.step_id in covered_steps:
            continue
        diagnostic = _diagnostic_from_step_result(step_result)
        if diagnostic is not None:
            diagnostics.append(diagnostic)

    stop_reason = next(
        (
            diagnostic
            for diagnostic in diagnostics
            if diagnostic.continuation_policy != ContinuationPolicy.CONTINUE
        ),
        None,
    )
    decision_points = tuple(
        diagnostic.decision_point for diagnostic in diagnostics if diagnostic.decision_point is not None
    )
    return GuidedRunProjection(
        diagnostics=tuple(diagnostics),
        stop_reason=stop_reason,
        decision_points=decision_points,
    )


def _covered_issue_steps(issues: Iterable[ExecutionIssue]) -> set[str]:
    covered: set[str] = set()
    for issue in issues:
        if issue.step is not None:
            covered.add(issue.step.step_id)
    return covered


def _diagnostic_from_issue(issue: ExecutionIssue) -> GuidedDiagnostic | None:
    template = _guided_template_for_issue(issue)
    if template is None:
        return None
    return GuidedDiagnostic(
        diagnostic_id=issue.code,
        title=template.title,
        summary=template.summary or issue.message,
        phase=issue.phase,
        status=issue.outcome,
        step=issue.step,
        issue_code=issue.code,
        continuation_policy=template.continuation_policy,
        tags=template.tags,
        actions=template.actions,
        decision_point=template.decision_point,
        details=issue.details,
    )


def _diagnostic_from_step_result(step_result: StepExecutionResult) -> GuidedDiagnostic | None:
    template = _guided_template_for_step_result(step_result)
    if template is None:
        return None
    phase = _step_result_phase(step_result)
    return GuidedDiagnostic(
        diagnostic_id=f"step:{step_result.step_id}:{phase.value}:{step_result.status.value.lower()}",
        title=template.title,
        summary=template.summary or step_result.message,
        phase=phase,
        status=step_result.status,
        step=_step_reference(step_result),
        issue_code=None,
        continuation_policy=template.continuation_policy,
        tags=template.tags,
        actions=template.actions,
        decision_point=template.decision_point,
        details=dict(step_result.details),
    )


def _guided_template_for_issue(issue: ExecutionIssue) -> _GuidedTemplate | None:
    code = issue.code
    if code == "compile_variables_section_invalid":
        return _template(
            title="Scenario contract is not machine-readable",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.USER_FIXABLE,),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "fix_variables_dsl",
                    GuidedActionType.UPDATE_SCENARIO,
                    "Fix variables DSL",
                    "Rewrite ambiguous variable definitions using the supported machine-readable DSL.",
                    recommended=True,
                ),
            ),
        )
    if code in {
        "compile_capture_rule_invalid",
        "compile_capture_variable_invalid",
        "compile_variable_dependency_cycle",
        "compile_step_self_capture_dependency",
        "compile_future_capture_dependency",
        "compile_api_step_definition_missing",
        "compile_db_step_definition_missing",
    }:
        return _template(
            title="Scenario contract blocks execution before runtime",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.USER_FIXABLE,),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "update_scenario_contract",
                    GuidedActionType.UPDATE_SCENARIO,
                    "Update scenario contract",
                    "Adjust step dependencies, capture rules, or missing step definitions so the contract is executable.",
                    recommended=True,
                ),
            ),
        )
    if code == "compile_unsupported_expectation":
        return _template(
            title="Scenario uses runner syntax that is not supported",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.UNSUPPORTED_BY_RUNNER, GuidedDiagnosticTag.USER_FIXABLE),
            continuation_policy=ContinuationPolicy.STOP_UNSUPPORTED,
            actions=(
                _action(
                    "rewrite_expectation",
                    GuidedActionType.REVIEW_RUNNER_LIMITATION,
                    "Rewrite unsupported expectation",
                    "Replace the unsupported expectation with a supported DSL rule or move the assertion to DB/manual verification.",
                    recommended=True,
                ),
            ),
        )
    if code.startswith("preflight_environment_file_exists"):
        return _template(
            title="Environment file is missing",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.ENVIRONMENT_BLOCKED, GuidedDiagnosticTag.USER_FIXABLE),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "provide_env_file",
                    GuidedActionType.REVIEW_CONFIGURATION,
                    "Provide environment file",
                    "Create or point the scenario to a valid env file before rerunning.",
                    recommended=True,
                ),
            ),
        )
    if code.startswith("preflight_target_project_path_exists"):
        return _template(
            title="Target project path is unavailable",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.ENVIRONMENT_BLOCKED, GuidedDiagnosticTag.USER_FIXABLE),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "fix_project_path",
                    GuidedActionType.REVIEW_CONFIGURATION,
                    "Fix project path",
                    "Update the scenario project path or restore the missing project directory.",
                    recommended=True,
                ),
            ),
        )
    if code.startswith("preflight_external_inputs_resolvable"):
        return _template(
            title="Required environment inputs are missing",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.ENVIRONMENT_BLOCKED, GuidedDiagnosticTag.USER_FIXABLE),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "set_missing_env_variables",
                    GuidedActionType.REVIEW_CONFIGURATION,
                    "Provide required inputs",
                    "Populate the missing env variables or update the scenario variable mapping.",
                    recommended=True,
                ),
            ),
        )
    if code.startswith("preflight_dependency_"):
        return _template(
            title="Required Python dependency is unavailable",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.ENVIRONMENT_BLOCKED, GuidedDiagnosticTag.USER_FIXABLE),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "install_dependency",
                    GuidedActionType.INSTALL_DEPENDENCY,
                    "Install missing dependency",
                    "Install the missing Python dependency required for this scenario type.",
                    recommended=True,
                ),
            ),
        )
    if code.startswith("preflight_api_tool_entrypoint_exists") or code.startswith("preflight_db_tool_entrypoint_exists"):
        return _template(
            title="Runner tool entrypoint is missing",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.ENVIRONMENT_BLOCKED, GuidedDiagnosticTag.USER_FIXABLE),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "restore_tool_entrypoint",
                    GuidedActionType.REVIEW_CONFIGURATION,
                    "Restore tool entrypoint",
                    "Restore the required API/DB tool script under tools/ before rerunning.",
                    recommended=True,
                ),
            ),
        )
    if code.startswith("preflight_output_directory_available"):
        return _template(
            title="Runner output directories are unavailable",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.ENVIRONMENT_BLOCKED, GuidedDiagnosticTag.USER_FIXABLE),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "fix_output_directory",
                    GuidedActionType.REVIEW_CONFIGURATION,
                    "Fix output directory access",
                    "Restore write access to .codex-qa/ and artifacts/agent before rerunning.",
                    recommended=True,
                ),
            ),
        )
    if code in {"initial_context_resolution_blocked", "step_variable_resolution_blocked"}:
        return _template(
            title="A required variable could not be resolved",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.USER_FIXABLE,),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "fix_variable_resolution",
                    GuidedActionType.UPDATE_SCENARIO,
                    "Fix variable mapping",
                    "Populate the missing variable source or adjust the placeholder usage before rerunning.",
                    recommended=True,
                ),
            ),
        )
    if code == "deferred_capture_blocked":
        retry_action = _action(
            "retry_after_fixing_producer",
            GuidedActionType.RETRY_RUN,
            "Retry after fixing producer step",
            "Fix the earlier producer step and rerun the scenario so the downstream capture becomes available.",
            recommended=True,
        )
        inspect_action = _action(
            "inspect_producer_artifacts",
            GuidedActionType.INSPECT_ARTIFACTS,
            "Inspect producer step artifacts",
            "Review the upstream step input/raw-result artifacts to understand why the capture was not produced.",
        )
        return _template(
            title="Downstream step is blocked by an earlier missing capture",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.REQUIRES_DECISION, GuidedDiagnosticTag.USER_FIXABLE),
            continuation_policy=ContinuationPolicy.WAIT_FOR_DECISION,
            actions=(retry_action, inspect_action),
            decision_point=DecisionPoint(
                decision_id=f"decision:{issue.code}:{issue.step.step_id if issue.step else 'run'}",
                title="Resolve blocked downstream capture",
                prompt=(
                    "The scenario can only continue after the earlier producer step is fixed. "
                    "Choose whether to inspect the producer artifacts first or rerun after a fix."
                ),
                continuation_policy=ContinuationPolicy.WAIT_FOR_DECISION,
                recommended_action_id=retry_action.action_id,
                actions=(retry_action, inspect_action),
            ),
        )
    if code == "step_capture_failed":
        return _template(
            title="Capture contract did not match the step output",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.USER_FIXABLE,),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "inspect_capture_contract",
                    GuidedActionType.UPDATE_SCENARIO,
                    "Inspect capture contract",
                    "Compare the capture rule with the actual tool payload and update the path if needed.",
                    recommended=True,
                ),
            ),
        )
    if code == "step_execution_failed":
        retry_action = _action(
            "retry_runtime_failure",
            GuidedActionType.RETRY_RUN,
            "Retry run",
            "Retry the scenario after checking the runner tool and local environment.",
            recommended=True,
        )
        return _template(
            title="Runner tool failed during step execution",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.RETRYABLE,),
            continuation_policy=ContinuationPolicy.RETRY_MANUALLY,
            actions=(
                retry_action,
                _action(
                    "inspect_step_artifacts",
                    GuidedActionType.INSPECT_ARTIFACTS,
                    "Inspect step artifacts",
                    "Review the step input and raw-result artifacts for the failing step.",
                ),
            ),
            decision_point=DecisionPoint(
                decision_id=f"decision:{issue.code}:{issue.step.step_id if issue.step else 'run'}",
                title="Retry failed runtime step",
                prompt="Decide whether to retry the run after checking the tool/runtime environment.",
                continuation_policy=ContinuationPolicy.RETRY_MANUALLY,
                recommended_action_id=retry_action.action_id,
                actions=(
                    retry_action,
                    _action(
                        "inspect_step_artifacts",
                        GuidedActionType.INSPECT_ARTIFACTS,
                        "Inspect step artifacts",
                        "Review the recorded artifacts before retrying.",
                    ),
                ),
            ),
        )
    if code in {"step_expectation_non_pass", "expectation_validation_blocked", "expectation_validation_failed"}:
        return _template(
            title="Expectation evaluation needs attention",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.INFORMATIVE,),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "review_expectation_results",
                    GuidedActionType.INSPECT_ARTIFACTS,
                    "Review expectation results",
                    "Inspect the actual response/query payload and adjust the expectation or investigated system behavior.",
                    recommended=True,
                ),
            ),
        )
    if code.endswith("_persistence_failed") or code in {
        "report_generation_failed",
        "report_artifact_path_creation_failed",
        "initial_run_state_persistence_failed",
    }:
        return _template(
            title="Runner finalization failed after execution",
            summary=issue.message,
            tags=(GuidedDiagnosticTag.RETRYABLE,),
            continuation_policy=ContinuationPolicy.RETRY_MANUALLY,
            actions=(
                _action(
                    "retry_finalization",
                    GuidedActionType.RETRY_RUN,
                    "Retry run",
                    "Retry after checking local filesystem access and report tooling.",
                    recommended=True,
                ),
            ),
        )
    return None


def _guided_template_for_step_result(step_result: StepExecutionResult) -> _GuidedTemplate | None:
    message = step_result.message
    details = step_result.details
    tool_classification = str(details.get("tool_classification", "")).strip().lower()
    phase = _step_result_phase(step_result)

    if phase == ExecutionPhase.INTERPOLATION:
        return _template(
            title="Step payload could not be interpolated",
            summary=message,
            tags=(GuidedDiagnosticTag.USER_FIXABLE,),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "fix_interpolation",
                    GuidedActionType.UPDATE_SCENARIO,
                    "Fix interpolation inputs",
                    "Populate the missing placeholders or correct the step payload template.",
                    recommended=True,
                ),
            ),
        )
    if tool_classification == "connectivity":
        retry_action = _action(
            "retry_after_connectivity_fix",
            GuidedActionType.RETRY_RUN,
            "Retry after connectivity fix",
            "Verify DNS/network access or API base URL configuration and rerun the scenario.",
            recommended=True,
        )
        inspect_action = _action(
            "inspect_request_debug",
            GuidedActionType.INSPECT_ARTIFACTS,
            "Inspect request debug",
            "Review request_debug in the step artifacts to see DNS and resolver diagnostics.",
        )
        return _template(
            title="External service connectivity blocked the step",
            summary=message,
            tags=(
                GuidedDiagnosticTag.RETRYABLE,
                GuidedDiagnosticTag.ENVIRONMENT_BLOCKED,
                GuidedDiagnosticTag.USER_FIXABLE,
            ),
            continuation_policy=ContinuationPolicy.RETRY_MANUALLY,
            actions=(retry_action, inspect_action),
            decision_point=DecisionPoint(
                decision_id=f"decision:connectivity:{step_result.step_id}",
                title="Resolve connectivity blocker",
                prompt=(
                    "The step did not reach the external service. "
                    "Decide whether to inspect diagnostics first or retry after fixing connectivity."
                ),
                continuation_policy=ContinuationPolicy.RETRY_MANUALLY,
                recommended_action_id=retry_action.action_id,
                actions=(retry_action, inspect_action),
            ),
        )
    if tool_classification == "service_unavailable":
        retry_action = _action(
            "retry_after_service_recovery",
            GuidedActionType.RETRY_RUN,
            "Retry after service recovery",
            "Retry the scenario when the upstream service becomes available.",
            recommended=True,
        )
        return _template(
            title="Upstream service is unavailable",
            summary=message,
            tags=(GuidedDiagnosticTag.RETRYABLE, GuidedDiagnosticTag.REQUIRES_DECISION),
            continuation_policy=ContinuationPolicy.WAIT_FOR_DECISION,
            actions=(
                retry_action,
                _action(
                    "inspect_response_artifacts",
                    GuidedActionType.INSPECT_ARTIFACTS,
                    "Inspect service response",
                    "Review the recorded response and retry metadata before deciding to retry.",
                ),
            ),
            decision_point=DecisionPoint(
                decision_id=f"decision:service_unavailable:{step_result.step_id}",
                title="Wait or retry unavailable service",
                prompt="The upstream service returned a temporary availability error. Decide when to retry.",
                continuation_policy=ContinuationPolicy.WAIT_FOR_DECISION,
                recommended_action_id=retry_action.action_id,
                actions=(
                    retry_action,
                    _action(
                        "inspect_response_artifacts",
                        GuidedActionType.INSPECT_ARTIFACTS,
                        "Inspect service response",
                        "Review the current failure evidence before retrying.",
                    ),
                ),
            ),
        )
    if _is_api_auth_or_config_message(message):
        return _template(
            title="API auth or base URL configuration blocked the step",
            summary=message,
            tags=(GuidedDiagnosticTag.ENVIRONMENT_BLOCKED, GuidedDiagnosticTag.USER_FIXABLE),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "fix_api_auth",
                    GuidedActionType.REVIEW_CONFIGURATION,
                    "Fix API auth/config",
                    "Populate the missing API auth/base URL variables or adjust API_AUTH_TYPE before rerunning.",
                    recommended=True,
                ),
            ),
        )
    if _is_db_connection_message(message):
        return _template(
            title="DB connection settings are missing",
            summary=message,
            tags=(GuidedDiagnosticTag.ENVIRONMENT_BLOCKED, GuidedDiagnosticTag.USER_FIXABLE),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "fix_db_connection",
                    GuidedActionType.REVIEW_CONFIGURATION,
                    "Fix DB connection settings",
                    "Provide DATABASE_URL or the required DB credential variables before rerunning.",
                    recommended=True,
                ),
            ),
        )
    if _is_db_read_only_violation(message):
        return _template(
            title="DB step violates the read-only safety contract",
            summary=message,
            tags=(GuidedDiagnosticTag.USER_FIXABLE,),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "rewrite_sql_as_read_only",
                    GuidedActionType.UPDATE_SCENARIO,
                    "Rewrite SQL as read-only",
                    "Replace the SQL with a single read-only SELECT query that only verifies persisted state.",
                    recommended=True,
                ),
            ),
        )
    if step_result.status == StepStatus.FAIL:
        return _template(
            title="Scenario expectation failed at runtime",
            summary=message,
            tags=(GuidedDiagnosticTag.INFORMATIVE,),
            continuation_policy=ContinuationPolicy.STOP_AND_FIX,
            actions=(
                _action(
                    "inspect_runtime_mismatch",
                    GuidedActionType.INSPECT_ARTIFACTS,
                    "Inspect runtime mismatch",
                    "Compare the expected and actual runtime data recorded for this step.",
                    recommended=True,
                ),
            ),
        )
    if step_result.status == StepStatus.ERROR:
        return _template(
            title="Runner integration failed during step execution",
            summary=message,
            tags=(GuidedDiagnosticTag.RETRYABLE,),
            continuation_policy=ContinuationPolicy.RETRY_MANUALLY,
            actions=(
                _action(
                    "retry_after_runner_failure",
                    GuidedActionType.RETRY_RUN,
                    "Retry run",
                    "Retry after checking the local runner tool output and step artifacts.",
                    recommended=True,
                ),
            ),
        )
    return None


def _step_result_phase(step_result: StepExecutionResult) -> ExecutionPhase:
    raw_phase = step_result.details.get("phase")
    if isinstance(raw_phase, str):
        try:
            return ExecutionPhase(raw_phase)
        except ValueError:
            if raw_phase == "deferred_capture":
                return ExecutionPhase.CAPTURE
    return ExecutionPhase.STEP_EXECUTION


def _step_reference(step_result: StepExecutionResult):
    from ..domain.execution import StepReference

    return StepReference(
        step_id=step_result.step_id,
        step_number=step_result.step_number,
        step_type=step_result.step_type,
    )


def _is_api_auth_or_config_message(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "missing api_base_url",
            "api_auth_type=",
            "unsupported api_auth_type",
            "unsupported auth type",
        )
    )


def _is_db_connection_message(message: str) -> bool:
    lowered = message.lower()
    return "missing db connection settings" in lowered or "database_url" in lowered


def _is_db_read_only_violation(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "only select queries are allowed",
            "read-only policy violation",
            "multiple sql statements are not allowed",
        )
    )


def _template(
    *,
    title: str,
    summary: str,
    tags: tuple[GuidedDiagnosticTag, ...],
    continuation_policy: ContinuationPolicy,
    actions: tuple[GuidedAction, ...],
    decision_point: DecisionPoint | None = None,
) -> _GuidedTemplate:
    return _GuidedTemplate(
        title=title,
        summary=summary,
        tags=tags,
        continuation_policy=continuation_policy,
        actions=actions,
        decision_point=decision_point,
    )


def _action(
    action_id: str,
    action_type: GuidedActionType,
    title: str,
    description: str,
    *,
    recommended: bool = False,
) -> GuidedAction:
    return GuidedAction(
        action_id=action_id,
        action_type=action_type,
        title=title,
        description=description,
        recommended=recommended,
    )
