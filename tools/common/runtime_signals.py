"""Shared normalized runtime/tool signals for orchestration and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .json_safe import to_json_safe


class RuntimeSignalSource(StrEnum):
    TOOL = "tool"
    EXECUTION = "execution"
    PREFLIGHT = "preflight"
    COMPILATION = "compilation"
    FINALIZATION = "finalization"


class RuntimeFailureCategory(StrEnum):
    CONFIGURATION = "configuration"
    CONNECTIVITY = "connectivity"
    SERVICE_AVAILABILITY = "service_availability"
    DATABASE = "database"
    READ_ONLY_GUARD = "read_only_guard"
    VALIDATION = "validation"
    UNSUPPORTED = "unsupported"
    DEPENDENCY = "dependency"
    TOOL_RUNTIME = "tool_runtime"
    FINALIZATION = "finalization"


class ToolFailureCode(StrEnum):
    MISSING_ENV_OR_CONFIG = "missing_env_or_config"
    API_AUTH_CONFIGURATION_BLOCKED = "api_auth_configuration_blocked"
    API_CONNECTIVITY_BLOCKED = "api_connectivity_blocked"
    API_SERVICE_UNAVAILABLE = "api_service_unavailable"
    DB_CONNECTION_CONFIGURATION_MISSING = "db_connection_configuration_missing"
    DB_CONNECTION_FAILED = "db_connection_failed"
    DB_READ_ONLY_GUARD_VIOLATION = "db_read_only_guard_violation"
    UNSUPPORTED_EXPECTATION = "unsupported_expectation"
    SCENARIO_CONTRACT_INVALID = "scenario_contract_invalid"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    VARIABLE_RESOLUTION_BLOCKED = "variable_resolution_blocked"
    STEP_INTERPOLATION_BLOCKED = "step_interpolation_blocked"
    CAPTURE_CONTRACT_FAILED = "capture_contract_failed"
    DEFERRED_CAPTURE_BLOCKED = "deferred_capture_blocked"
    RUNTIME_TOOL_FAILURE = "runtime_tool_failure"
    FINALIZATION_FAILURE = "finalization_failure"


class RetryHint(StrEnum):
    NONE = "none"
    AFTER_OPERATOR_FIX = "after_operator_fix"
    MANUAL_RETRY = "manual_retry"
    AFTER_SERVICE_RECOVERY = "after_service_recovery"


class ContinuationHint(StrEnum):
    CONTINUE = "continue"
    STOP_AND_FIX = "stop_and_fix"
    RETRY_MANUALLY = "retry_manually"
    WAIT_FOR_DECISION = "wait_for_decision"
    STOP_UNSUPPORTED = "stop_unsupported"


class RuntimeSignalTag(StrEnum):
    INFORMATIVE = "informative"
    RETRYABLE = "retryable"
    USER_FIXABLE = "user_fixable"
    ENVIRONMENT_BLOCKED = "environment_blocked"
    UNSUPPORTED_BY_RUNNER = "unsupported_by_runner"
    REQUIRES_DECISION = "requires_decision"


@dataclass(frozen=True, slots=True)
class NormalizedRuntimeSignal:
    source: RuntimeSignalSource
    code: ToolFailureCode
    category: RuntimeFailureCategory
    retry_hint: RetryHint = RetryHint.NONE
    continuation_hint: ContinuationHint = ContinuationHint.CONTINUE
    tags: tuple[RuntimeSignalTag, ...] = ()
    resumable: bool = False
    operator_fixable: bool = False
    runner_unsupported: bool = False
    requires_decision: bool = False
    affected_scope: str = "step"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "source": self.source.value,
                "code": self.code.value,
                "category": self.category.value,
                "retry_hint": self.retry_hint.value,
                "continuation_hint": self.continuation_hint.value,
                "tags": [tag.value for tag in self.tags],
                "resumable": self.resumable,
                "operator_fixable": self.operator_fixable,
                "runner_unsupported": self.runner_unsupported,
                "requires_decision": self.requires_decision,
                "affected_scope": self.affected_scope,
                "details": self.details,
            }
        )

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "NormalizedRuntimeSignal":
        return cls(
            source=RuntimeSignalSource(str(payload.get("source", "")).strip()),
            code=ToolFailureCode(str(payload.get("code", "")).strip()),
            category=RuntimeFailureCategory(str(payload.get("category", "")).strip()),
            retry_hint=RetryHint(str(payload.get("retry_hint", RetryHint.NONE.value)).strip()),
            continuation_hint=ContinuationHint(
                str(payload.get("continuation_hint", ContinuationHint.CONTINUE.value)).strip()
            ),
            tags=tuple(
                RuntimeSignalTag(str(item).strip())
                for item in payload.get("tags") or []
                if str(item).strip()
            ),
            resumable=bool(payload.get("resumable", False)),
            operator_fixable=bool(payload.get("operator_fixable", False)),
            runner_unsupported=bool(payload.get("runner_unsupported", False)),
            requires_decision=bool(payload.get("requires_decision", False)),
            affected_scope=str(payload.get("affected_scope", "step")).strip() or "step",
            details=dict(payload.get("details") or {}),
        )
