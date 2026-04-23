"""Typed enrichment contracts for applying evidence to planned test cases."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.generation.domain.models import GenerationDiagnostic, NormalizedTestPlan, TraceabilityLink
from tools.generation.evidence.models import EvidenceConfidence


class TestCaseReadiness(StrEnum):
    NEEDS_CLARIFICATION = "needs_clarification"
    PROSE_ONLY = "prose_only"
    PARTIALLY_SUPPORTED = "partially_supported"
    ROUTE_RESOLVED = "route_resolved"
    EVIDENCE_SUPPORTED = "evidence_supported"


@dataclass(slots=True)
class AppliedEvidenceLink:
    case_id: str
    fact_id: str
    relation: str
    confidence: EvidenceConfidence
    summary: str
    applied_fields: dict[str, Any] = field(default_factory=dict)
    match_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AppliedEvidenceLink":
        return cls(
            case_id=str(payload["case_id"]),
            fact_id=str(payload["fact_id"]),
            relation=str(payload["relation"]),
            confidence=EvidenceConfidence(str(payload["confidence"])),
            summary=str(payload.get("summary", "")),
            applied_fields=dict(payload.get("applied_fields") or {}),
            match_reasons=[str(item) for item in payload.get("match_reasons", [])],
        )


@dataclass(slots=True)
class UnappliedEvidenceReason:
    fact_id: str
    reason_code: str
    message: str
    candidate_case_ids: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "UnappliedEvidenceReason":
        return cls(
            fact_id=str(payload["fact_id"]),
            reason_code=str(payload["reason_code"]),
            message=str(payload["message"]),
            candidate_case_ids=[str(item) for item in payload.get("candidate_case_ids", [])],
            details=dict(payload.get("details") or {}),
        )


@dataclass(slots=True)
class CaseEnrichment:
    case_id: str
    readiness_before: TestCaseReadiness
    readiness_after: TestCaseReadiness
    applied_evidence: list[AppliedEvidenceLink] = field(default_factory=list)
    resolved_open_questions: list[str] = field(default_factory=list)
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CaseEnrichment":
        return cls(
            case_id=str(payload["case_id"]),
            readiness_before=TestCaseReadiness(str(payload["readiness_before"])),
            readiness_after=TestCaseReadiness(str(payload["readiness_after"])),
            applied_evidence=[
                AppliedEvidenceLink.from_dict(item) for item in payload.get("applied_evidence", [])
            ],
            resolved_open_questions=[
                str(item) for item in payload.get("resolved_open_questions", [])
            ],
            diagnostics=[GenerationDiagnostic.from_dict(item) for item in payload.get("diagnostics", [])],
        )


@dataclass(slots=True)
class EnrichedTestPlanResult:
    enriched_plan: NormalizedTestPlan
    case_enrichments: list[CaseEnrichment] = field(default_factory=list)
    applied_evidence: list[AppliedEvidenceLink] = field(default_factory=list)
    unapplied_evidence: list[UnappliedEvidenceReason] = field(default_factory=list)
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)
    traceability_links: list[TraceabilityLink] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EnrichedTestPlanResult":
        return cls(
            enriched_plan=NormalizedTestPlan.from_dict(dict(payload["enriched_plan"])),
            case_enrichments=[
                CaseEnrichment.from_dict(item) for item in payload.get("case_enrichments", [])
            ],
            applied_evidence=[
                AppliedEvidenceLink.from_dict(item) for item in payload.get("applied_evidence", [])
            ],
            unapplied_evidence=[
                UnappliedEvidenceReason.from_dict(item)
                for item in payload.get("unapplied_evidence", [])
            ],
            diagnostics=[GenerationDiagnostic.from_dict(item) for item in payload.get("diagnostics", [])],
            traceability_links=[
                TraceabilityLink.from_dict(item) for item in payload.get("traceability_links", [])
            ],
        )
