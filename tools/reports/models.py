"""Models for QA report building."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.common.errors import ValidationError


@dataclass(slots=True)
class CheckResult:
    name: str
    status: str
    detail: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "CheckResult":
        name = str(payload.get("name", "")).strip() or "Unnamed check"
        status = str(payload.get("status", "")).strip() or "UNKNOWN"

        detail_raw = payload.get("detail")
        detail = str(detail_raw).strip() if detail_raw is not None else None
        if detail == "":
            detail = None

        return cls(name=name, status=status, detail=detail)


@dataclass(slots=True)
class GuidedActionData:
    action_id: str
    title: str
    description: str
    action_type: str
    recommended: bool = False

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "GuidedActionData":
        return cls(
            action_id=str(payload.get("action_id", "")).strip() or "unknown",
            title=str(payload.get("title", "")).strip() or "Untitled action",
            description=str(payload.get("description", "")).strip() or "No description provided.",
            action_type=str(payload.get("action_type", "")).strip() or "unknown",
            recommended=bool(payload.get("recommended", False)),
        )


@dataclass(slots=True)
class DecisionPointData:
    title: str
    prompt: str
    continuation_policy: str
    recommended_action_id: str | None = None
    available_operator_actions: list[GuidedActionData] = field(default_factory=list)
    recommended_operator_action_id: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "DecisionPointData":
        recommended_action_id = payload.get("recommended_action_id")
        recommended_operator_action_id = payload.get("recommended_operator_action_id")
        available_operator_actions_raw = payload.get("available_operator_actions") or []
        if not isinstance(available_operator_actions_raw, list):
            raise ValidationError("Field 'guided_diagnostics[].decision_point.available_operator_actions' must be an array")
        return cls(
            title=str(payload.get("title", "")).strip() or "Decision required",
            prompt=str(payload.get("prompt", "")).strip() or "A decision is required.",
            continuation_policy=str(payload.get("continuation_policy", "")).strip() or "unknown",
            recommended_action_id=(
                str(recommended_action_id).strip() if recommended_action_id is not None else None
            ),
            available_operator_actions=[
                GuidedActionData.from_mapping(item)
                for item in available_operator_actions_raw
                if isinstance(item, dict)
            ],
            recommended_operator_action_id=(
                str(recommended_operator_action_id).strip()
                if recommended_operator_action_id is not None
                else None
            ),
        )


@dataclass(slots=True)
class GuidedDiagnosticData:
    diagnostic_id: str
    title: str
    summary: str
    continuation_policy: str
    phase: str | None = None
    status: str | None = None
    tags: list[str] = field(default_factory=list)
    actions: list[GuidedActionData] = field(default_factory=list)
    decision_point: DecisionPointData | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "GuidedDiagnosticData":
        tags = payload.get("tags") or []
        if not isinstance(tags, list):
            raise ValidationError("Field 'guided_diagnostics[].tags' must be an array")

        actions_raw = payload.get("actions") or []
        if not isinstance(actions_raw, list):
            raise ValidationError("Field 'guided_diagnostics[].actions' must be an array")

        decision_point_raw = payload.get("decision_point")
        if decision_point_raw is not None and not isinstance(decision_point_raw, dict):
            raise ValidationError("Field 'guided_diagnostics[].decision_point' must be an object")

        return cls(
            diagnostic_id=str(payload.get("diagnostic_id", "")).strip() or "unknown",
            title=str(payload.get("title", "")).strip() or "Untitled diagnostic",
            summary=str(payload.get("summary", "")).strip() or "No summary provided.",
            continuation_policy=str(payload.get("continuation_policy", "")).strip() or "unknown",
            phase=_optional_string(payload, "phase"),
            status=_optional_string(payload, "status"),
            tags=[str(item).strip() for item in tags if str(item).strip()],
            actions=[GuidedActionData.from_mapping(item) for item in actions_raw if isinstance(item, dict)],
            decision_point=(
                None if decision_point_raw is None else DecisionPointData.from_mapping(decision_point_raw)
            ),
        )


@dataclass(slots=True)
class SummaryData:
    final_status: str
    notes: list[str] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    executive_summary: str | None = None
    code_analysis_summary: str | None = None
    blockers: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    guided_diagnostics: list[GuidedDiagnosticData] = field(default_factory=list)
    guided_stop_reason: GuidedDiagnosticData | None = None
    continuation_state: str = "terminal"
    resumable: bool = False
    resume_token: dict[str, Any] | None = None
    pause_state_path: str | None = None
    available_operator_actions: list[GuidedActionData] = field(default_factory=list)
    decision_resolution: dict[str, Any] | None = None
    resumed_from_pause: bool = False

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "SummaryData":
        final_status = str(payload.get("final_status", "")).strip() or "UNKNOWN"

        notes = cls._read_string_list(payload, "notes")
        blockers = cls._read_string_list(payload, "blockers")
        assumptions = cls._read_string_list(payload, "assumptions")
        artifacts = cls._read_string_list(payload, "artifacts")

        checks_raw = payload.get("checks") or []
        if not isinstance(checks_raw, list):
            raise ValidationError("Field 'checks' must be an array")

        checks: list[CheckResult] = []
        for item in checks_raw:
            if not isinstance(item, dict):
                raise ValidationError("Each item in 'checks' must be an object")
            checks.append(CheckResult.from_mapping(item))

        executive_summary = cls._read_optional_string(payload, "executive_summary")
        code_analysis_summary = cls._read_optional_string(payload, "code_analysis_summary")
        guided_diagnostics_raw = payload.get("guided_diagnostics") or []
        if not isinstance(guided_diagnostics_raw, list):
            raise ValidationError("Field 'guided_diagnostics' must be an array")
        guided_stop_reason_raw = payload.get("guided_stop_reason")
        if guided_stop_reason_raw is not None and not isinstance(guided_stop_reason_raw, dict):
            raise ValidationError("Field 'guided_stop_reason' must be an object")
        resume_token_raw = payload.get("resume_token")
        if resume_token_raw is not None and not isinstance(resume_token_raw, dict):
            raise ValidationError("Field 'resume_token' must be an object")
        available_operator_actions_raw = payload.get("available_operator_actions") or []
        if not isinstance(available_operator_actions_raw, list):
            raise ValidationError("Field 'available_operator_actions' must be an array")
        decision_resolution_raw = payload.get("decision_resolution")
        if decision_resolution_raw is not None and not isinstance(decision_resolution_raw, dict):
            raise ValidationError("Field 'decision_resolution' must be an object")

        return cls(
            final_status=final_status,
            notes=notes,
            checks=checks,
            executive_summary=executive_summary,
            code_analysis_summary=code_analysis_summary,
            blockers=blockers,
            assumptions=assumptions,
            artifacts=artifacts,
            guided_diagnostics=[
                GuidedDiagnosticData.from_mapping(item)
                for item in guided_diagnostics_raw
                if isinstance(item, dict)
            ],
            guided_stop_reason=(
                None if guided_stop_reason_raw is None else GuidedDiagnosticData.from_mapping(guided_stop_reason_raw)
            ),
            continuation_state=str(payload.get("continuation_state", "terminal")).strip() or "terminal",
            resumable=bool(payload.get("resumable", False)),
            resume_token=None if resume_token_raw is None else dict(resume_token_raw),
            pause_state_path=cls._read_optional_string(payload, "pause_state_path"),
            available_operator_actions=[
                GuidedActionData.from_mapping(item)
                for item in available_operator_actions_raw
                if isinstance(item, dict)
            ],
            decision_resolution=None if decision_resolution_raw is None else dict(decision_resolution_raw),
            resumed_from_pause=bool(payload.get("resumed_from_pause", False)),
        )

    @staticmethod
    def _read_string_list(payload: dict[str, Any], field_name: str) -> list[str]:
        raw_value = payload.get(field_name) or []
        if not isinstance(raw_value, list):
            raise ValidationError(f"Field '{field_name}' must be an array")

        values = [str(item).strip() for item in raw_value]
        return [item for item in values if item]

    @staticmethod
    def _read_optional_string(payload: dict[str, Any], field_name: str) -> str | None:
        raw_value = payload.get(field_name)
        if raw_value is None:
            return None

        value = str(raw_value).strip()
        return value or None


def _optional_string(payload: dict[str, Any], field_name: str) -> str | None:
    raw_value = payload.get(field_name)
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    return value or None


@dataclass(slots=True)
class ReportContext:
    project: str
    scenario: str
    summary: SummaryData
