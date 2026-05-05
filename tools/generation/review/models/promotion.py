"""Scenario promotion result contract models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.domain.models import GenerationDiagnostic

from .common import _optional_path


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

@dataclass(slots=True)
class ScenarioPromotionBatchResult:
    run_id: str
    status: StepStatus
    requested_count: int = 0
    promoted_count: int = 0
    error_count: int = 0
    blocked_count: int = 0
    target_dir: Path | None = None
    promotion_result_path: Path | None = None
    results: list[ScenarioPromotionResult] = field(default_factory=list)
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = to_json_safe(asdict(self))
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioPromotionBatchResult":
        return cls(
            run_id=str(payload["run_id"]),
            status=StepStatus(str(payload["status"])),
            requested_count=int(payload.get("requested_count", 0)),
            promoted_count=int(payload.get("promoted_count", 0)),
            error_count=int(payload.get("error_count", 0)),
            blocked_count=int(payload.get("blocked_count", 0)),
            target_dir=_optional_path(payload.get("target_dir")),
            promotion_result_path=_optional_path(payload.get("promotion_result_path")),
            results=[ScenarioPromotionResult.from_dict(item) for item in payload.get("results", [])],
            diagnostics=[GenerationDiagnostic.from_dict(item) for item in payload.get("diagnostics", [])],
        )
