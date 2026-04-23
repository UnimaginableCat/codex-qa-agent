"""Typed evidence contracts for generation code facts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.generation.domain.models import GenerationDiagnostic


class TargetStack(StrEnum):
    PYTHON = "python"
    JAVA_SPRING = "java_spring"


class EvidenceConfidence(StrEnum):
    EXPLICIT = "explicit"
    STRONG_INFERENCE = "strong_inference"
    WEAK_INFERENCE = "weak_inference"


@dataclass(slots=True)
class EvidenceProvenance:
    source_kind: str
    file_path: Path
    symbol: str | None = None
    line_range: tuple[int, int] | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceProvenance":
        line_range_raw = payload.get("line_range")
        line_range = None
        if isinstance(line_range_raw, list | tuple) and len(line_range_raw) == 2:
            line_range = (int(line_range_raw[0]), int(line_range_raw[1]))
        return cls(
            source_kind=str(payload["source_kind"]),
            file_path=Path(str(payload["file_path"])),
            symbol=None if payload.get("symbol") is None else str(payload["symbol"]),
            line_range=line_range,
            notes=str(payload.get("notes", "")),
        )


@dataclass(slots=True)
class GenerationEvidenceFact:
    fact_id: str
    fact_type: str
    summary: str
    payload: dict[str, Any]
    provenance: EvidenceProvenance
    confidence: EvidenceConfidence
    related_entities: list[str] = field(default_factory=list)
    related_interfaces: list[str] = field(default_factory=list)
    related_case_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GenerationEvidenceFact":
        return cls(
            fact_id=str(payload["fact_id"]),
            fact_type=str(payload["fact_type"]),
            summary=str(payload["summary"]),
            payload=dict(payload.get("payload") or {}),
            provenance=EvidenceProvenance.from_dict(dict(payload["provenance"])),
            confidence=EvidenceConfidence(str(payload["confidence"])),
            related_entities=[str(item) for item in payload.get("related_entities", [])],
            related_interfaces=[str(item) for item in payload.get("related_interfaces", [])],
            related_case_ids=[str(item) for item in payload.get("related_case_ids", [])],
        )


@dataclass(slots=True)
class GenerationEvidenceBundle:
    bundle_id: str
    target_project: str
    scope: str
    facts: list[GenerationEvidenceFact] = field(default_factory=list)
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GenerationEvidenceBundle":
        return cls(
            bundle_id=str(payload["bundle_id"]),
            target_project=str(payload["target_project"]),
            scope=str(payload["scope"]),
            facts=[GenerationEvidenceFact.from_dict(item) for item in payload.get("facts", [])],
            diagnostics=[GenerationDiagnostic.from_dict(item) for item in payload.get("diagnostics", [])],
            created_at=str(payload.get("created_at", "")),
        )


@dataclass(slots=True)
class CodeFactsScope:
    scope_id: str
    paths: list[Path] = field(default_factory=list)
    file_patterns: list[str] = field(default_factory=lambda: ["*.py", "*.java"])
    max_files: int = 20
    stack_hint: TargetStack | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CodeFactsScope":
        return cls(
            scope_id=str(payload["scope_id"]),
            paths=[Path(str(item)) for item in payload.get("paths", [])],
            file_patterns=[str(item) for item in payload.get("file_patterns", ["*.py", "*.java"])],
            max_files=int(payload.get("max_files", 20)),
            stack_hint=(
                None
                if payload.get("stack_hint") in {None, ""}
                else TargetStack(str(payload["stack_hint"]))
            ),
        )

