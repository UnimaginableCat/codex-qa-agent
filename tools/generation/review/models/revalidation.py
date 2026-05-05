"""Scenario revalidation contract models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus

from .checklist import DraftChecklistResult
from .drafts import DraftEditTargetList, DraftGapSummary
from .enums import (
    DraftPromotionAdvisory,
    ExecutionEnvironmentReadinessCategory,
    ExecutionReadinessCategory,
    ScenarioDraftParseStatus,
)
from .validation import ScenarioCompileValidationResult, ScenarioPreflightValidationResult


@dataclass(slots=True)
class ScenarioRevalidationResult:
    file_path: Path
    parse_status: ScenarioDraftParseStatus
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    checklist: DraftChecklistResult = field(default_factory=DraftChecklistResult)
    gap_summary: DraftGapSummary = field(default_factory=DraftGapSummary)
    edit_targets: DraftEditTargetList = field(default_factory=lambda: DraftEditTargetList(draft_id=""))
    promotion_advisory: DraftPromotionAdvisory = DraftPromotionAdvisory.SAFE_PREVIEW_ONLY
    completeness_ratio: float = 0.0
    based_on_generated_draft: bool = False
    generation_run_id: str = ""
    draft_id: str = ""
    validation_mode: str = "parser"
    compile_validation: ScenarioCompileValidationResult | None = None
    preflight_validation: ScenarioPreflightValidationResult | None = None
    execution_readiness_category: ExecutionReadinessCategory = ExecutionReadinessCategory.COMPILE_VALID_BUT_INCOMPLETE
    environment_readiness_category: ExecutionEnvironmentReadinessCategory | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioRevalidationResult":
        return cls(
            file_path=Path(str(payload["file_path"])),
            parse_status=ScenarioDraftParseStatus(str(payload["parse_status"])),
            diagnostics=[dict(item) for item in payload.get("diagnostics", [])],
            checklist=DraftChecklistResult.from_dict(dict(payload.get("checklist") or {})),
            gap_summary=DraftGapSummary.from_dict(dict(payload.get("gap_summary") or {})),
            edit_targets=DraftEditTargetList.from_dict(
                dict(payload.get("edit_targets") or {"draft_id": payload.get("draft_id", "")})
            ),
            promotion_advisory=DraftPromotionAdvisory(
                str(payload.get("promotion_advisory", DraftPromotionAdvisory.SAFE_PREVIEW_ONLY.value))
            ),
            completeness_ratio=float(payload.get("completeness_ratio", 0.0)),
            based_on_generated_draft=bool(payload.get("based_on_generated_draft", False)),
            generation_run_id=str(payload.get("generation_run_id", "")),
            draft_id=str(payload.get("draft_id", "")),
            validation_mode=str(payload.get("validation_mode", "parser")),
            compile_validation=(
                None
                if not payload.get("compile_validation")
                else ScenarioCompileValidationResult.from_dict(dict(payload["compile_validation"]))
            ),
            preflight_validation=(
                None
                if not payload.get("preflight_validation")
                else ScenarioPreflightValidationResult.from_dict(dict(payload["preflight_validation"]))
            ),
            execution_readiness_category=ExecutionReadinessCategory(
                str(
                    payload.get(
                        "execution_readiness_category",
                        ExecutionReadinessCategory.COMPILE_VALID_BUT_INCOMPLETE.value,
                    )
                )
            ),
            environment_readiness_category=(
                None
                if not payload.get("environment_readiness_category")
                else ExecutionEnvironmentReadinessCategory(str(payload["environment_readiness_category"]))
            ),
        )

@dataclass(slots=True)
class ScenarioDirectoryRevalidationResult:
    directory_path: Path
    validation_mode: str
    status: StepStatus
    scenario_count: int = 0
    failure_count: int = 0
    readiness_counts: dict[str, int] = field(default_factory=dict)
    failure_items: list[dict[str, Any]] = field(default_factory=list)
    results: list[ScenarioRevalidationResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = to_json_safe(asdict(self))
        payload["status"] = self.status.value
        payload["results"] = [item.to_dict() for item in self.results]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioDirectoryRevalidationResult":
        return cls(
            directory_path=Path(str(payload["directory_path"])),
            validation_mode=str(payload["validation_mode"]),
            status=StepStatus(str(payload["status"])),
            scenario_count=int(payload.get("scenario_count", 0)),
            failure_count=int(payload.get("failure_count", 0)),
            readiness_counts={str(key): int(value) for key, value in dict(payload.get("readiness_counts") or {}).items()},
            failure_items=[dict(item) for item in payload.get("failure_items", [])],
            results=[ScenarioRevalidationResult.from_dict(item) for item in payload.get("results", [])],
        )
