"""Typed contracts for scenario draft review and promotion."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.domain.models import GenerationDiagnostic


class ScenarioDraftParseStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


@dataclass(slots=True)
class ScenarioDraftReviewItem:
    draft_id: str
    file_path: Path
    parse_status: ScenarioDraftParseStatus
    diagnostics_summary: list[str] = field(default_factory=list)
    has_unsupported_items: bool = False
    has_deferred_items: bool = False

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioDraftReviewItem":
        return cls(
            draft_id=str(payload["draft_id"]),
            file_path=Path(str(payload["file_path"])),
            parse_status=ScenarioDraftParseStatus(str(payload["parse_status"])),
            diagnostics_summary=[str(item) for item in payload.get("diagnostics_summary", [])],
            has_unsupported_items=bool(payload.get("has_unsupported_items", False)),
            has_deferred_items=bool(payload.get("has_deferred_items", False)),
        )


@dataclass(slots=True)
class ScenarioDraftReviewSet:
    run_id: str
    source_id: str
    artifact_dir: Path
    items: list[ScenarioDraftReviewItem] = field(default_factory=list)
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioDraftReviewSet":
        return cls(
            run_id=str(payload["run_id"]),
            source_id=str(payload["source_id"]),
            artifact_dir=Path(str(payload["artifact_dir"])),
            items=[ScenarioDraftReviewItem.from_dict(item) for item in payload.get("items", [])],
            diagnostics=[GenerationDiagnostic.from_dict(item) for item in payload.get("diagnostics", [])],
        )


@dataclass(slots=True)
class ScenarioPromotionRequest:
    run_id: str
    draft_id: str
    workspace_root: Path = Path(".")
    target_dir: Path = Path("scenarios/generated")
    allow_invalid: bool = False

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))


@dataclass(slots=True)
class ScenarioPromotionResult:
    run_id: str
    draft_id: str
    status: StepStatus
    source_path: Path | None = None
    target_path: Path | None = None
    promotion_result_path: Path | None = None
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = to_json_safe(asdict(self))
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioPromotionResult":
        return cls(
            run_id=str(payload["run_id"]),
            draft_id=str(payload["draft_id"]),
            status=StepStatus(str(payload["status"])),
            source_path=_optional_path(payload.get("source_path")),
            target_path=_optional_path(payload.get("target_path")),
            promotion_result_path=_optional_path(payload.get("promotion_result_path")),
            diagnostics=[GenerationDiagnostic.from_dict(item) for item in payload.get("diagnostics", [])],
        )


def _optional_path(value: object) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))
