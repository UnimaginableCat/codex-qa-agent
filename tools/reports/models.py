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
class SummaryData:
    final_status: str
    notes: list[str] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    executive_summary: str | None = None
    code_analysis_summary: str | None = None
    blockers: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

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

        return cls(
            final_status=final_status,
            notes=notes,
            checks=checks,
            executive_summary=executive_summary,
            code_analysis_summary=code_analysis_summary,
            blockers=blockers,
            assumptions=assumptions,
            artifacts=artifacts,
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


@dataclass(slots=True)
class ReportContext:
    project: str
    scenario: str
    summary: SummaryData
