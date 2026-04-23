"""Typed contracts for scenario rendering preview artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.generation.domain.models import GenerationDiagnostic


@dataclass(slots=True)
class ScenarioDraft:
    draft_id: str
    case_id: str
    title: str
    markdown: str
    relative_path: Path
    source_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioDraft":
        return cls(
            draft_id=str(payload["draft_id"]),
            case_id=str(payload["case_id"]),
            title=str(payload["title"]),
            markdown=str(payload["markdown"]),
            relative_path=Path(str(payload["relative_path"])),
            source_refs=[str(item) for item in payload.get("source_refs", [])],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class UnsupportedCheck:
    case_id: str
    reason_code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "UnsupportedCheck":
        return cls(
            case_id=str(payload["case_id"]),
            reason_code=str(payload["reason_code"]),
            message=str(payload["message"]),
            details=dict(payload.get("details") or {}),
        )


@dataclass(slots=True)
class DeferredScenarioItem:
    case_id: str
    title: str
    reason_code: str
    message: str
    unsupported_checks: list[UnsupportedCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeferredScenarioItem":
        return cls(
            case_id=str(payload["case_id"]),
            title=str(payload["title"]),
            reason_code=str(payload["reason_code"]),
            message=str(payload["message"]),
            unsupported_checks=[
                UnsupportedCheck.from_dict(item) for item in payload.get("unsupported_checks", [])
            ],
        )


@dataclass(slots=True)
class ScenarioDraftValidationResult:
    draft_id: str
    case_id: str
    path: Path
    parse_valid: bool
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioDraftValidationResult":
        return cls(
            draft_id=str(payload["draft_id"]),
            case_id=str(payload["case_id"]),
            path=Path(str(payload["path"])),
            parse_valid=bool(payload["parse_valid"]),
            diagnostics=[dict(item) for item in payload.get("diagnostics", [])],
        )


@dataclass(slots=True)
class ScenarioDraftSet:
    plan_id: str
    drafts: list[ScenarioDraft] = field(default_factory=list)
    deferred_items: list[DeferredScenarioItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioDraftSet":
        return cls(
            plan_id=str(payload["plan_id"]),
            drafts=[ScenarioDraft.from_dict(item) for item in payload.get("drafts", [])],
            deferred_items=[
                DeferredScenarioItem.from_dict(item) for item in payload.get("deferred_items", [])
            ],
        )


@dataclass(slots=True)
class ScenarioRenderResult:
    draft_set: ScenarioDraftSet
    validation_results: list[ScenarioDraftValidationResult] = field(default_factory=list)
    unsupported_checks: list[UnsupportedCheck] = field(default_factory=list)
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioRenderResult":
        return cls(
            draft_set=ScenarioDraftSet.from_dict(dict(payload["draft_set"])),
            validation_results=[
                ScenarioDraftValidationResult.from_dict(item)
                for item in payload.get("validation_results", [])
            ],
            unsupported_checks=[
                UnsupportedCheck.from_dict(item) for item in payload.get("unsupported_checks", [])
            ],
            diagnostics=[GenerationDiagnostic.from_dict(item) for item in payload.get("diagnostics", [])],
        )
