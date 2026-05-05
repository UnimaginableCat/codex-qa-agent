"""Checklist contract models for draft review."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tools.common.json_safe import to_json_safe

from .enums import ScenarioRequirementStatus


@dataclass(slots=True)
class ScenarioRequirement:
    requirement_id: str
    description: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioRequirement":
        return cls(
            requirement_id=str(payload["requirement_id"]),
            description=str(payload["description"]),
            required=bool(payload.get("required", True)),
        )

@dataclass(slots=True)
class DraftRequirementCheck:
    requirement: ScenarioRequirement
    status: ScenarioRequirementStatus
    source: str = "unknown"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftRequirementCheck":
        return cls(
            requirement=ScenarioRequirement.from_dict(dict(payload["requirement"])),
            status=ScenarioRequirementStatus(str(payload["status"])),
            source=str(payload.get("source", "unknown")),
            notes=[str(item) for item in payload.get("notes", [])],
        )

@dataclass(slots=True)
class DraftChecklistResult:
    checklist_version: str = "v1"
    total_requirements: int = 0
    satisfied_count: int = 0
    missing_count: int = 0
    partial_count: int = 0
    completeness_ratio: float = 0.0
    checks: list[DraftRequirementCheck] = field(default_factory=list)
    diff_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftChecklistResult":
        return cls(
            checklist_version=str(payload.get("checklist_version", "v1")),
            total_requirements=int(payload.get("total_requirements", 0)),
            satisfied_count=int(payload.get("satisfied_count", 0)),
            missing_count=int(payload.get("missing_count", 0)),
            partial_count=int(payload.get("partial_count", 0)),
            completeness_ratio=float(payload.get("completeness_ratio", 0.0)),
            checks=[DraftRequirementCheck.from_dict(item) for item in payload.get("checks", [])],
            diff_lines=[str(item) for item in payload.get("diff_lines", [])],
        )
