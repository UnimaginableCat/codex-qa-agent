"""Compile and preflight validation contract models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe

from .enums import (
    CompileIssueType,
    ExecutionEnvironmentReadinessCategory,
    ExecutionReadinessCategory,
    PreflightIssueType,
    ScenarioCompileStatus,
    ScenarioDraftParseStatus,
    ScenarioPreflightStatus,
)


@dataclass(slots=True)
class CompileIssue:
    issue_id: str
    issue_type: CompileIssueType
    message: str
    severity: str = "error"
    source: str = "compile"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CompileIssue":
        return cls(
            issue_id=str(payload["issue_id"]),
            issue_type=CompileIssueType(str(payload["issue_type"])),
            message=str(payload["message"]),
            severity=str(payload.get("severity", "error")),
            source=str(payload.get("source", "compile")),
            details=dict(payload.get("details") or {}),
        )

@dataclass(slots=True)
class ScenarioCompileValidationResult:
    file_path: Path
    parse_status: ScenarioDraftParseStatus
    compile_status: ScenarioCompileStatus = ScenarioCompileStatus.SKIPPED
    issues: list[CompileIssue] = field(default_factory=list)
    warnings: list[CompileIssue] = field(default_factory=list)
    readiness_category: ExecutionReadinessCategory = ExecutionReadinessCategory.PARSER_INVALID
    summary: str = ""
    checks: list[dict[str, Any]] = field(default_factory=list)
    required_external_inputs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioCompileValidationResult":
        return cls(
            file_path=Path(str(payload["file_path"])),
            parse_status=ScenarioDraftParseStatus(str(payload["parse_status"])),
            compile_status=ScenarioCompileStatus(
                str(payload.get("compile_status", ScenarioCompileStatus.SKIPPED.value))
            ),
            issues=[CompileIssue.from_dict(item) for item in payload.get("issues", [])],
            warnings=[CompileIssue.from_dict(item) for item in payload.get("warnings", [])],
            readiness_category=ExecutionReadinessCategory(
                str(payload.get("readiness_category", ExecutionReadinessCategory.PARSER_INVALID.value))
            ),
            summary=str(payload.get("summary", "")),
            checks=[dict(item) for item in payload.get("checks", [])],
            required_external_inputs=[dict(item) for item in payload.get("required_external_inputs", [])],
        )

@dataclass(slots=True)
class PreflightIssue:
    issue_type: PreflightIssueType
    message: str
    severity: str = "blocked"
    source: str = "preflight"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PreflightIssue":
        return cls(
            issue_type=PreflightIssueType(str(payload["issue_type"])),
            message=str(payload["message"]),
            severity=str(payload.get("severity", "blocked")),
            source=str(payload.get("source", "preflight")),
            details=dict(payload.get("details") or {}),
        )

@dataclass(slots=True)
class ScenarioPreflightValidationResult:
    file_path: Path
    parse_status: ScenarioDraftParseStatus
    compile_status: ScenarioCompileStatus
    preflight_status: ScenarioPreflightStatus = ScenarioPreflightStatus.SKIPPED
    readiness_category: ExecutionEnvironmentReadinessCategory = (
        ExecutionEnvironmentReadinessCategory.SKIPPED_DUE_TO_PARSER_ERROR
    )
    issues: list[PreflightIssue] = field(default_factory=list)
    warnings: list[PreflightIssue] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioPreflightValidationResult":
        return cls(
            file_path=Path(str(payload["file_path"])),
            parse_status=ScenarioDraftParseStatus(str(payload["parse_status"])),
            compile_status=ScenarioCompileStatus(str(payload["compile_status"])),
            preflight_status=ScenarioPreflightStatus(
                str(payload.get("preflight_status", ScenarioPreflightStatus.SKIPPED.value))
            ),
            readiness_category=ExecutionEnvironmentReadinessCategory(
                str(
                    payload.get(
                        "readiness_category",
                        ExecutionEnvironmentReadinessCategory.SKIPPED_DUE_TO_PARSER_ERROR.value,
                    )
                )
            ),
            issues=[PreflightIssue.from_dict(item) for item in payload.get("issues", [])],
            warnings=[PreflightIssue.from_dict(item) for item in payload.get("warnings", [])],
            checks=[dict(item) for item in payload.get("checks", [])],
            summary=str(payload.get("summary", "")),
        )
