"""Normalization layer from raw tool/runtime outcomes to typed signals."""

from __future__ import annotations

from typing import Any

from tools.common.runtime_signals import (
    ContinuationHint,
    NormalizedRuntimeSignal,
    RetryHint,
    RuntimeFailureCategory,
    RuntimeSignalSource,
    RuntimeSignalTag,
    ToolFailureCode,
)
from tools.common.statuses import StepStatus

from ..domain.execution import ExecutionIssue, ExecutionPhase
from ..domain.models import ScenarioStepType, StepExecutionResult


def normalize_tool_runtime_signal(
    *,
    step_type: ScenarioStepType,
    status: StepStatus,
    message: str,
    payload: dict[str, Any] | None,
) -> NormalizedRuntimeSignal | None:
    payload = payload or {}
    explicit_signal = _runtime_signal_from_mapping(payload.get("runtime_signal"))
    if explicit_signal is not None:
        return explicit_signal

    classification = str(payload.get("classification", "")).strip().lower()
    if classification == "connectivity":
        return _build_signal(
            source=RuntimeSignalSource.TOOL,
            code=ToolFailureCode.API_CONNECTIVITY_BLOCKED,
            category=RuntimeFailureCategory.CONNECTIVITY,
            retry_hint=RetryHint.MANUAL_RETRY,
            continuation_hint=ContinuationHint.RETRY_MANUALLY,
            tags=(
                RuntimeSignalTag.RETRYABLE,
                RuntimeSignalTag.ENVIRONMENT_BLOCKED,
                RuntimeSignalTag.USER_FIXABLE,
            ),
            resumable=True,
            operator_fixable=True,
            details={"legacy_classification": classification},
        )
    if classification == "service_unavailable":
        return _build_signal(
            source=RuntimeSignalSource.TOOL,
            code=ToolFailureCode.API_SERVICE_UNAVAILABLE,
            category=RuntimeFailureCategory.SERVICE_AVAILABILITY,
            retry_hint=RetryHint.AFTER_SERVICE_RECOVERY,
            continuation_hint=ContinuationHint.WAIT_FOR_DECISION,
            tags=(RuntimeSignalTag.RETRYABLE, RuntimeSignalTag.REQUIRES_DECISION),
            resumable=True,
            requires_decision=True,
            details={"legacy_classification": classification},
        )

    if step_type == ScenarioStepType.API and _is_api_auth_or_config_message(message):
        return _build_signal(
            source=RuntimeSignalSource.TOOL,
            code=ToolFailureCode.API_AUTH_CONFIGURATION_BLOCKED,
            category=RuntimeFailureCategory.CONFIGURATION,
            retry_hint=RetryHint.AFTER_OPERATOR_FIX,
            continuation_hint=ContinuationHint.STOP_AND_FIX,
            tags=(RuntimeSignalTag.ENVIRONMENT_BLOCKED, RuntimeSignalTag.USER_FIXABLE),
            operator_fixable=True,
        )
    if step_type == ScenarioStepType.DB and _is_db_connection_configuration_message(message):
        return _build_signal(
            source=RuntimeSignalSource.TOOL,
            code=ToolFailureCode.DB_CONNECTION_CONFIGURATION_MISSING,
            category=RuntimeFailureCategory.CONFIGURATION,
            retry_hint=RetryHint.AFTER_OPERATOR_FIX,
            continuation_hint=ContinuationHint.STOP_AND_FIX,
            tags=(RuntimeSignalTag.ENVIRONMENT_BLOCKED, RuntimeSignalTag.USER_FIXABLE),
            operator_fixable=True,
        )
    if step_type == ScenarioStepType.DB and _is_db_read_only_violation_message(message):
        return _build_signal(
            source=RuntimeSignalSource.TOOL,
            code=ToolFailureCode.DB_READ_ONLY_GUARD_VIOLATION,
            category=RuntimeFailureCategory.READ_ONLY_GUARD,
            retry_hint=RetryHint.NONE,
            continuation_hint=ContinuationHint.STOP_AND_FIX,
            tags=(RuntimeSignalTag.USER_FIXABLE,),
            operator_fixable=True,
        )
    if step_type == ScenarioStepType.DB and _is_db_connection_failure_message(message):
        return _build_signal(
            source=RuntimeSignalSource.TOOL,
            code=ToolFailureCode.DB_CONNECTION_FAILED,
            category=RuntimeFailureCategory.DATABASE,
            retry_hint=RetryHint.MANUAL_RETRY,
            continuation_hint=ContinuationHint.RETRY_MANUALLY,
            tags=(
                RuntimeSignalTag.RETRYABLE,
                RuntimeSignalTag.ENVIRONMENT_BLOCKED,
                RuntimeSignalTag.USER_FIXABLE,
            ),
            resumable=True,
            operator_fixable=True,
        )

    if status == StepStatus.ERROR:
        return _build_signal(
            source=RuntimeSignalSource.TOOL,
            code=ToolFailureCode.RUNTIME_TOOL_FAILURE,
            category=RuntimeFailureCategory.TOOL_RUNTIME,
            retry_hint=RetryHint.MANUAL_RETRY,
            continuation_hint=ContinuationHint.RETRY_MANUALLY,
            tags=(RuntimeSignalTag.RETRYABLE,),
            resumable=True,
        )
    return None


def normalize_step_runtime_signal(step_result: StepExecutionResult) -> NormalizedRuntimeSignal | None:
    explicit_signal = _runtime_signal_from_mapping(step_result.details.get("runtime_signal"))
    if explicit_signal is not None:
        return explicit_signal
    phase = step_result.details.get("phase")
    if phase == ExecutionPhase.INTERPOLATION.value:
        return _build_signal(
            source=RuntimeSignalSource.EXECUTION,
            code=ToolFailureCode.STEP_INTERPOLATION_BLOCKED,
            category=RuntimeFailureCategory.VALIDATION,
            retry_hint=RetryHint.AFTER_OPERATOR_FIX,
            continuation_hint=ContinuationHint.STOP_AND_FIX,
            tags=(RuntimeSignalTag.USER_FIXABLE,),
            operator_fixable=True,
        )
    step_type = step_result.step_type
    return normalize_tool_runtime_signal(
        step_type=step_type,
        status=step_result.status,
        message=step_result.message,
        payload=step_result.details,
    )


def normalize_issue_runtime_signal(issue: ExecutionIssue) -> NormalizedRuntimeSignal | None:
    explicit_signal = _runtime_signal_from_mapping(issue.details.get("runtime_signal"))
    if explicit_signal is not None:
        return explicit_signal

    code = issue.code
    if code == "compile_unsupported_expectation":
        return _build_signal(
            source=RuntimeSignalSource.COMPILATION,
            code=ToolFailureCode.UNSUPPORTED_EXPECTATION,
            category=RuntimeFailureCategory.UNSUPPORTED,
            continuation_hint=ContinuationHint.STOP_UNSUPPORTED,
            tags=(RuntimeSignalTag.UNSUPPORTED_BY_RUNNER, RuntimeSignalTag.USER_FIXABLE),
            runner_unsupported=True,
            operator_fixable=True,
            affected_scope="run",
        )
    if code in {
        "compile_variables_section_invalid",
        "compile_capture_rule_invalid",
        "compile_capture_variable_invalid",
        "compile_variable_dependency_cycle",
        "compile_step_self_capture_dependency",
        "compile_future_capture_dependency",
        "compile_api_step_definition_missing",
        "compile_db_step_definition_missing",
    }:
        return _build_signal(
            source=RuntimeSignalSource.COMPILATION,
            code=ToolFailureCode.SCENARIO_CONTRACT_INVALID,
            category=RuntimeFailureCategory.VALIDATION,
            continuation_hint=ContinuationHint.STOP_AND_FIX,
            tags=(RuntimeSignalTag.USER_FIXABLE,),
            operator_fixable=True,
            affected_scope="run",
        )
    if code.startswith("preflight_dependency_"):
        return _build_signal(
            source=RuntimeSignalSource.PREFLIGHT,
            code=ToolFailureCode.DEPENDENCY_UNAVAILABLE,
            category=RuntimeFailureCategory.DEPENDENCY,
            continuation_hint=ContinuationHint.STOP_AND_FIX,
            tags=(RuntimeSignalTag.ENVIRONMENT_BLOCKED, RuntimeSignalTag.USER_FIXABLE),
            operator_fixable=True,
            affected_scope="run",
        )
    if code.startswith("preflight_"):
        return _build_signal(
            source=RuntimeSignalSource.PREFLIGHT,
            code=ToolFailureCode.MISSING_ENV_OR_CONFIG,
            category=RuntimeFailureCategory.CONFIGURATION,
            continuation_hint=ContinuationHint.STOP_AND_FIX,
            tags=(RuntimeSignalTag.ENVIRONMENT_BLOCKED, RuntimeSignalTag.USER_FIXABLE),
            operator_fixable=True,
            affected_scope="run",
        )
    if code in {"initial_context_resolution_blocked", "step_variable_resolution_blocked"}:
        return _build_signal(
            source=RuntimeSignalSource.EXECUTION,
            code=ToolFailureCode.VARIABLE_RESOLUTION_BLOCKED,
            category=RuntimeFailureCategory.VALIDATION,
            continuation_hint=ContinuationHint.STOP_AND_FIX,
            tags=(RuntimeSignalTag.USER_FIXABLE,),
            operator_fixable=True,
        )
    if code == "deferred_capture_blocked":
        return _build_signal(
            source=RuntimeSignalSource.EXECUTION,
            code=ToolFailureCode.DEFERRED_CAPTURE_BLOCKED,
            category=RuntimeFailureCategory.VALIDATION,
            retry_hint=RetryHint.AFTER_OPERATOR_FIX,
            continuation_hint=ContinuationHint.WAIT_FOR_DECISION,
            tags=(RuntimeSignalTag.REQUIRES_DECISION, RuntimeSignalTag.USER_FIXABLE),
            resumable=True,
            operator_fixable=True,
            requires_decision=True,
            details=dict(issue.details),
        )
    if code == "step_capture_failed":
        return _build_signal(
            source=RuntimeSignalSource.EXECUTION,
            code=ToolFailureCode.CAPTURE_CONTRACT_FAILED,
            category=RuntimeFailureCategory.VALIDATION,
            continuation_hint=ContinuationHint.STOP_AND_FIX,
            tags=(RuntimeSignalTag.USER_FIXABLE,),
            operator_fixable=True,
        )
    if code == "step_execution_failed":
        return _build_signal(
            source=RuntimeSignalSource.EXECUTION,
            code=ToolFailureCode.RUNTIME_TOOL_FAILURE,
            category=RuntimeFailureCategory.TOOL_RUNTIME,
            retry_hint=RetryHint.MANUAL_RETRY,
            continuation_hint=ContinuationHint.RETRY_MANUALLY,
            tags=(RuntimeSignalTag.RETRYABLE,),
            resumable=True,
        )
    if code in {"step_expectation_non_pass", "expectation_validation_blocked", "expectation_validation_failed"}:
        return _build_signal(
            source=RuntimeSignalSource.EXECUTION,
            code=ToolFailureCode.SCENARIO_CONTRACT_INVALID,
            category=RuntimeFailureCategory.VALIDATION,
            continuation_hint=ContinuationHint.STOP_AND_FIX,
            tags=(RuntimeSignalTag.INFORMATIVE,),
        )
    if code.endswith("_persistence_failed") or code in {
        "report_generation_failed",
        "report_artifact_path_creation_failed",
        "initial_run_state_persistence_failed",
    }:
        return _build_signal(
            source=RuntimeSignalSource.FINALIZATION,
            code=ToolFailureCode.FINALIZATION_FAILURE,
            category=RuntimeFailureCategory.FINALIZATION,
            retry_hint=RetryHint.MANUAL_RETRY,
            continuation_hint=ContinuationHint.RETRY_MANUALLY,
            tags=(RuntimeSignalTag.RETRYABLE,),
            affected_scope="run",
        )
    return None


def _runtime_signal_from_mapping(payload: Any) -> NormalizedRuntimeSignal | None:
    if not isinstance(payload, dict):
        return None
    try:
        return NormalizedRuntimeSignal.from_mapping(payload)
    except ValueError:
        return None


def _build_signal(
    *,
    source: RuntimeSignalSource,
    code: ToolFailureCode,
    category: RuntimeFailureCategory,
    retry_hint: RetryHint = RetryHint.NONE,
    continuation_hint: ContinuationHint = ContinuationHint.CONTINUE,
    tags: tuple[RuntimeSignalTag, ...] = (),
    resumable: bool = False,
    operator_fixable: bool = False,
    runner_unsupported: bool = False,
    requires_decision: bool = False,
    affected_scope: str = "step",
    details: dict[str, Any] | None = None,
) -> NormalizedRuntimeSignal:
    return NormalizedRuntimeSignal(
        source=source,
        code=code,
        category=category,
        retry_hint=retry_hint,
        continuation_hint=continuation_hint,
        tags=tags,
        resumable=resumable,
        operator_fixable=operator_fixable,
        runner_unsupported=runner_unsupported,
        requires_decision=requires_decision,
        affected_scope=affected_scope,
        details=details or {},
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


def _is_db_connection_configuration_message(message: str) -> bool:
    lowered = message.lower()
    return "missing db connection settings" in lowered or "database_url" in lowered


def _is_db_connection_failure_message(message: str) -> bool:
    lowered = message.lower()
    return lowered.startswith("database error:")


def _is_db_read_only_violation_message(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "only select queries are allowed",
            "read-only policy violation",
            "multiple sql statements are not allowed",
        )
    )
