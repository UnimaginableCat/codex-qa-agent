"""Draft review contract models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.generation.domain.models import GenerationDiagnostic

from .checklist import DraftChecklistResult
from .enums import DraftEditTargetType, DraftPromotionAdvisory, DraftReadinessCategory, ScenarioDraftParseStatus
from .patches import DraftPatchSuggestion


@dataclass(slots=True)
class DraftEditTarget:
    target_id: str
    draft_id: str
    section_name: str
    target_type: DraftEditTargetType
    reason: str
    related_requirements: list[str] = field(default_factory=list)
    priority: str = "normal"
    suggested_minimum_patch: str = ""
    patch_suggestion: DraftPatchSuggestion = field(default_factory=DraftPatchSuggestion)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftEditTarget":
        return cls(
            target_id=str(payload["target_id"]),
            draft_id=str(payload["draft_id"]),
            section_name=str(payload["section_name"]),
            target_type=DraftEditTargetType(str(payload["target_type"])),
            reason=str(payload["reason"]),
            related_requirements=[str(item) for item in payload.get("related_requirements", [])],
            priority=str(payload.get("priority", "normal")),
            suggested_minimum_patch=str(payload.get("suggested_minimum_patch", "")),
            patch_suggestion=DraftPatchSuggestion.from_dict(dict(payload.get("patch_suggestion") or {})),
        )

@dataclass(slots=True)
class DraftEditTargetList:
    draft_id: str
    targets: list[DraftEditTarget] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftEditTargetList":
        return cls(
            draft_id=str(payload["draft_id"]),
            targets=[DraftEditTarget.from_dict(item) for item in payload.get("targets", [])],
        )

@dataclass(slots=True)
class DraftGapSummary:
    gap_codes: list[str] = field(default_factory=list)
    gap_messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftGapSummary":
        return cls(
            gap_codes=[str(item) for item in payload.get("gap_codes", [])],
            gap_messages=[str(item) for item in payload.get("gap_messages", [])],
        )

@dataclass(slots=True)
class DraftReviewDiagnosticsSummary:
    parse_diagnostics_count: int = 0
    render_diagnostics_count: int = 0
    parse_messages: list[str] = field(default_factory=list)
    render_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftReviewDiagnosticsSummary":
        return cls(
            parse_diagnostics_count=int(payload.get("parse_diagnostics_count", 0)),
            render_diagnostics_count=int(payload.get("render_diagnostics_count", 0)),
            parse_messages=[str(item) for item in payload.get("parse_messages", [])],
            render_codes=[str(item) for item in payload.get("render_codes", [])],
        )

@dataclass(slots=True)
class DeferredDraftReviewItem:
    case_id: str
    title: str
    reason_code: str
    message: str
    readiness_category: DraftReadinessCategory = DraftReadinessCategory.UNSUPPORTED_DEFERRED
    gap_summary: DraftGapSummary = field(default_factory=DraftGapSummary)
    promotion_advisory: DraftPromotionAdvisory = DraftPromotionAdvisory.NOT_RECOMMENDED_FOR_PROMOTION
    checklist: DraftChecklistResult = field(default_factory=DraftChecklistResult)
    edit_targets: DraftEditTargetList = field(default_factory=lambda: DraftEditTargetList(draft_id=""))
    edit_target_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeferredDraftReviewItem":
        return cls(
            case_id=str(payload["case_id"]),
            title=str(payload["title"]),
            reason_code=str(payload["reason_code"]),
            message=str(payload["message"]),
            readiness_category=DraftReadinessCategory(
                str(payload.get("readiness_category", DraftReadinessCategory.UNSUPPORTED_DEFERRED.value))
            ),
            gap_summary=DraftGapSummary.from_dict(dict(payload.get("gap_summary") or {})),
            promotion_advisory=DraftPromotionAdvisory(
                str(
                    payload.get(
                        "promotion_advisory",
                        DraftPromotionAdvisory.NOT_RECOMMENDED_FOR_PROMOTION.value,
                    )
                )
            ),
            checklist=DraftChecklistResult.from_dict(dict(payload.get("checklist") or {})),
            edit_targets=DraftEditTargetList.from_dict(
                dict(payload.get("edit_targets") or {"draft_id": payload.get("case_id", "")})
            ),
            edit_target_count=int(payload.get("edit_target_count", 0)),
        )

@dataclass(slots=True)
class ScenarioDraftReviewItem:
    draft_id: str
    case_id: str
    title: str
    file_path: Path
    parse_status: ScenarioDraftParseStatus
    diagnostics_summary: list[str] = field(default_factory=list)
    has_unsupported_items: bool = False
    has_deferred_items: bool = False
    readiness_category: DraftReadinessCategory = DraftReadinessCategory.PARSER_VALID_PARTIAL
    route_status: str = "unknown"
    gap_summary: DraftGapSummary = field(default_factory=DraftGapSummary)
    promotion_advisory: DraftPromotionAdvisory = DraftPromotionAdvisory.SAFE_PREVIEW_ONLY
    diagnostics_details: DraftReviewDiagnosticsSummary = field(default_factory=DraftReviewDiagnosticsSummary)
    checklist: DraftChecklistResult = field(default_factory=DraftChecklistResult)
    edit_targets: DraftEditTargetList = field(default_factory=lambda: DraftEditTargetList(draft_id=""))
    edit_target_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioDraftReviewItem":
        return cls(
            draft_id=str(payload["draft_id"]),
            case_id=str(payload.get("case_id", "")),
            title=str(payload.get("title", "")),
            file_path=Path(str(payload["file_path"])),
            parse_status=ScenarioDraftParseStatus(str(payload["parse_status"])),
            diagnostics_summary=[str(item) for item in payload.get("diagnostics_summary", [])],
            has_unsupported_items=bool(payload.get("has_unsupported_items", False)),
            has_deferred_items=bool(payload.get("has_deferred_items", False)),
            readiness_category=DraftReadinessCategory(
                str(payload.get("readiness_category", DraftReadinessCategory.PARSER_VALID_PARTIAL.value))
            ),
            route_status=str(payload.get("route_status", "unknown")),
            gap_summary=DraftGapSummary.from_dict(dict(payload.get("gap_summary") or {})),
            promotion_advisory=DraftPromotionAdvisory(
                str(payload.get("promotion_advisory", DraftPromotionAdvisory.SAFE_PREVIEW_ONLY.value))
            ),
            diagnostics_details=DraftReviewDiagnosticsSummary.from_dict(
                dict(payload.get("diagnostics_details") or {})
            ),
            checklist=DraftChecklistResult.from_dict(dict(payload.get("checklist") or {})),
            edit_targets=DraftEditTargetList.from_dict(
                dict(payload.get("edit_targets") or {"draft_id": payload.get("draft_id", "")})
            ),
            edit_target_count=int(payload.get("edit_target_count", 0)),
        )

@dataclass(slots=True)
class ScenarioDraftReviewSet:
    run_id: str
    source_id: str
    artifact_dir: Path
    items: list[ScenarioDraftReviewItem] = field(default_factory=list)
    deferred_items: list[DeferredDraftReviewItem] = field(default_factory=list)
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
            deferred_items=[
                DeferredDraftReviewItem.from_dict(item) for item in payload.get("deferred_items", [])
            ],
            diagnostics=[GenerationDiagnostic.from_dict(item) for item in payload.get("diagnostics", [])],
        )
