"""Deterministic evidence-to-plan enrichment services."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from tools.generation.domain.models import (
    DiagnosticSeverity,
    GenerationDiagnostic,
    NormalizedTestPlan,
    PlannedTestCase,
    TraceabilityLink,
)
from tools.generation.evidence.models import (
    EvidenceConfidence,
    GenerationEvidenceBundle,
    GenerationEvidenceFact,
)

from .models import (
    AppliedEvidenceLink,
    CaseEnrichment,
    EnrichedTestPlanResult,
    TestCaseReadiness,
    UnappliedEvidenceReason,
)


class TestPlanEnricher(Protocol):
    """Contract for applying external evidence to a normalized test plan."""

    def enrich(
        self,
        plan: NormalizedTestPlan,
        evidence_bundle: GenerationEvidenceBundle,
    ) -> EnrichedTestPlanResult:
        """Return an auditable enriched plan result."""
        ...


@dataclass(slots=True)
class EvidenceToPlanEnricher:
    """Apply explicit API endpoint evidence to relevant planned cases."""

    min_match_score: int = 2

    def enrich(
        self,
        plan: NormalizedTestPlan,
        evidence_bundle: GenerationEvidenceBundle,
    ) -> EnrichedTestPlanResult:
        enriched_plan = NormalizedTestPlan.from_dict(plan.to_dict())
        diagnostics: list[GenerationDiagnostic] = []
        case_enrichments: list[CaseEnrichment] = []
        applied_evidence: list[AppliedEvidenceLink] = []
        unapplied_evidence: list[UnappliedEvidenceReason] = []
        traceability_links: list[TraceabilityLink] = []
        applied_fact_ids: set[str] = set()
        ambiguous_fact_ids: set[str] = set()

        for test_case in enriched_plan.test_cases:
            readiness_before = _case_readiness(test_case)
            candidates = self._rank_candidates(test_case, evidence_bundle.facts)
            top_score = candidates[0][1] if candidates else 0
            top_candidates = [
                (fact, score)
                for fact, score in candidates
                if score == top_score and score >= self.min_match_score
            ]

            case_diagnostics: list[GenerationDiagnostic] = []
            case_applied: list[AppliedEvidenceLink] = []
            resolved_questions: list[str] = []

            if len(top_candidates) > 1:
                candidate_ids = [fact.fact_id for fact, _ in top_candidates]
                ambiguous_fact_ids.update(candidate_ids)
                diagnostic = GenerationDiagnostic(
                    code="ambiguous_evidence_match",
                    message="Multiple evidence facts matched the planned case with the same score.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=test_case.case_id,
                    details={"candidate_fact_ids": candidate_ids},
                )
                case_diagnostics.append(diagnostic)
                diagnostics.append(diagnostic)
            elif len(top_candidates) == 1:
                fact, _score = top_candidates[0]
                conflict = _method_conflict(test_case, fact)
                if conflict:
                    diagnostic = GenerationDiagnostic(
                        code="evidence_conflicts_with_case_action",
                        message="Evidence HTTP method conflicts with action implied by the planned case.",
                        severity=DiagnosticSeverity.WARNING,
                        source_ref=test_case.case_id,
                        details={"fact_id": fact.fact_id, "expected_methods": sorted(conflict)},
                    )
                    case_diagnostics.append(diagnostic)
                    diagnostics.append(diagnostic)
                elif fact.confidence == EvidenceConfidence.WEAK_INFERENCE:
                    unapplied_evidence.append(
                        UnappliedEvidenceReason(
                            fact_id=fact.fact_id,
                            reason_code="low_confidence_evidence",
                            message="Weak inference evidence was not applied to the canonical plan.",
                            candidate_case_ids=[test_case.case_id],
                        )
                    )
                else:
                    link = _build_applied_link(test_case, fact)
                    case_applied.append(link)
                    applied_evidence.append(link)
                    applied_fact_ids.add(fact.fact_id)
                    resolved_questions = _resolve_open_questions(test_case, fact)
                    _apply_evidence_to_case(test_case, fact, link, resolved_questions)
                    traceability_links.append(
                        TraceabilityLink(
                            source_ref=f"evidence:{fact.fact_id}",
                            target_ref=test_case.case_id,
                            relation="evidence_supports_case",
                            metadata={
                                "confidence": fact.confidence.value,
                                "fact_type": fact.fact_type,
                            },
                        )
                    )

            readiness_after = _case_readiness(test_case)
            case_enrichments.append(
                CaseEnrichment(
                    case_id=test_case.case_id,
                    readiness_before=readiness_before,
                    readiness_after=readiness_after,
                    applied_evidence=case_applied,
                    resolved_open_questions=resolved_questions,
                    diagnostics=case_diagnostics,
                )
            )

        for fact in evidence_bundle.facts:
            if fact.fact_id in applied_fact_ids:
                continue
            if fact.fact_id in ambiguous_fact_ids:
                unapplied_evidence.append(
                    UnappliedEvidenceReason(
                        fact_id=fact.fact_id,
                        reason_code="ambiguous_match",
                        message="Evidence matched multiple candidates or tied with another fact.",
                    )
                )
                continue
            if fact.confidence == EvidenceConfidence.WEAK_INFERENCE:
                if not any(reason.fact_id == fact.fact_id for reason in unapplied_evidence):
                    unapplied_evidence.append(
                        UnappliedEvidenceReason(
                            fact_id=fact.fact_id,
                            reason_code="low_confidence_evidence",
                            message="Weak inference evidence was not applied to the canonical plan.",
                        )
                    )
                continue
            unapplied_evidence.append(
                UnappliedEvidenceReason(
                    fact_id=fact.fact_id,
                    reason_code="no_relevant_case",
                    message="No planned test case matched this evidence strongly enough.",
                )
            )

        enriched_plan.metadata = {
            **enriched_plan.metadata,
            "enrichment": {
                "stage": "evidence-to-plan-v1",
                "evidence_bundle_id": evidence_bundle.bundle_id,
                "applied_evidence_count": len(applied_evidence),
                "unapplied_evidence_count": len(unapplied_evidence),
            },
        }
        return EnrichedTestPlanResult(
            enriched_plan=enriched_plan,
            case_enrichments=case_enrichments,
            applied_evidence=applied_evidence,
            unapplied_evidence=unapplied_evidence,
            diagnostics=diagnostics,
            traceability_links=traceability_links,
        )

    def _rank_candidates(
        self,
        test_case: PlannedTestCase,
        facts: list[GenerationEvidenceFact],
    ) -> list[tuple[GenerationEvidenceFact, int]]:
        scored = [(fact, _match_score(test_case, fact)) for fact in facts if fact.fact_type == "api_endpoint"]
        return sorted(scored, key=lambda item: (-item[1], item[0].fact_id))


def _build_applied_link(test_case: PlannedTestCase, fact: GenerationEvidenceFact) -> AppliedEvidenceLink:
    applied_fields = {
        "endpoint_path": fact.payload.get("endpoint_path"),
        "http_method": fact.payload.get("http_method"),
        "handler_name": fact.payload.get("handler_name"),
        "framework_hint": fact.payload.get("framework_hint"),
        "provenance": fact.provenance.to_dict(),
    }
    return AppliedEvidenceLink(
        case_id=test_case.case_id,
        fact_id=fact.fact_id,
        relation="evidence_supports_case",
        confidence=fact.confidence,
        summary=fact.summary,
        applied_fields={key: value for key, value in applied_fields.items() if value not in (None, "")},
    )


def _apply_evidence_to_case(
    test_case: PlannedTestCase,
    fact: GenerationEvidenceFact,
    link: AppliedEvidenceLink,
    resolved_questions: list[str],
) -> None:
    evidence_hints = list(test_case.metadata.get("evidence_hints", []))
    evidence_hints.append(link.to_dict())
    test_case.metadata = {
        **test_case.metadata,
        "evidence_hints": evidence_hints,
        "readiness": _readiness_from_fact(fact).value,
    }
    if "evidence-supported" not in test_case.tags:
        test_case.tags.append("evidence-supported")
    if resolved_questions:
        test_case.metadata["resolved_open_questions"] = resolved_questions
        test_case.open_questions = [
            question for question in test_case.open_questions if question not in resolved_questions
        ]


def _match_score(test_case: PlannedTestCase, fact: GenerationEvidenceFact) -> int:
    if fact.confidence == EvidenceConfidence.WEAK_INFERENCE:
        return 0
    case_terms = _case_terms(test_case)
    fact_terms = _fact_terms(fact)
    entity_overlap = case_terms & fact_terms
    if not entity_overlap:
        return 0

    score = min(len(entity_overlap), 3)
    method = str(fact.payload.get("http_method") or "").upper()
    case_methods = _case_action_methods(test_case)
    if method and method in case_methods:
        score += 3

    handler_name = str(fact.payload.get("handler_name") or "")
    handler_terms = _split_identifier(handler_name)
    if case_terms & handler_terms:
        score += 1
    return max(score, 0)


def _method_conflict(test_case: PlannedTestCase, fact: GenerationEvidenceFact) -> set[str]:
    method = str(fact.payload.get("http_method") or "").upper()
    case_methods = _case_action_methods(test_case)
    if method and case_methods and method not in case_methods:
        return case_methods
    return set()


def _case_action_methods(test_case: PlannedTestCase) -> set[str]:
    text = _case_text(test_case).lower()
    result: set[str] = set()
    action_map = {
        "create": "POST",
        "creation": "POST",
        "создан": "POST",
        "get": "GET",
        "fetch": "GET",
        "list": "GET",
        "read": "GET",
        "получ": "GET",
        "patch": "PATCH",
        "update": "PATCH",
        "change": "PATCH",
        "delete": "DELETE",
        "remove": "DELETE",
    }
    for marker, method in action_map.items():
        if marker in text:
            result.add(method)
    return result


def _case_readiness(test_case: PlannedTestCase) -> TestCaseReadiness:
    readiness = str(test_case.metadata.get("readiness", ""))
    if readiness in {item.value for item in TestCaseReadiness}:
        return TestCaseReadiness(readiness)
    if test_case.metadata.get("evidence_hints"):
        return TestCaseReadiness.EVIDENCE_SUPPORTED
    if test_case.open_questions:
        return TestCaseReadiness.NEEDS_CLARIFICATION
    return TestCaseReadiness.PROSE_ONLY


def _readiness_from_fact(fact: GenerationEvidenceFact) -> TestCaseReadiness:
    if fact.confidence == EvidenceConfidence.EXPLICIT and fact.payload.get("http_method"):
        return TestCaseReadiness.EVIDENCE_SUPPORTED
    return TestCaseReadiness.PARTIALLY_SUPPORTED


def _resolve_open_questions(test_case: PlannedTestCase, fact: GenerationEvidenceFact) -> list[str]:
    if not fact.payload.get("endpoint_path") or not fact.payload.get("http_method"):
        return []
    return [
        question
        for question in test_case.open_questions
        if any(marker in question.lower() for marker in ("api", "endpoint", "executable detail"))
    ]


def _case_terms(test_case: PlannedTestCase) -> set[str]:
    terms = _tokenize(_case_text(test_case))
    normalized = set(terms)
    for term in terms:
        if term.endswith("s") and len(term) > 3:
            normalized.add(term[:-1])
        else:
            normalized.add(term + "s")
    return normalized - _STOP_TERMS


def _fact_terms(fact: GenerationEvidenceFact) -> set[str]:
    values = [
        str(fact.payload.get("endpoint_path") or ""),
        str(fact.payload.get("handler_name") or ""),
        fact.summary,
        " ".join(fact.related_entities),
        " ".join(fact.related_interfaces),
    ]
    terms = set()
    for value in values:
        terms.update(_tokenize(value))
        terms.update(_split_identifier(value))
    normalized = set(terms)
    for term in terms:
        if term.endswith("s") and len(term) > 3:
            normalized.add(term[:-1])
        else:
            normalized.add(term + "s")
    return normalized - _STOP_TERMS


def _case_text(test_case: PlannedTestCase) -> str:
    return " ".join(
        [
            test_case.title,
            test_case.objective,
            " ".join(test_case.steps),
            " ".join(test_case.expected_results),
        ]
    )


def _tokenize(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", value)
        if len(token) >= 3
    }


def _split_identifier(value: str) -> set[str]:
    cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    return _tokenize(cleaned.replace("_", " ").replace("-", " ").replace("/", " "))


_STOP_TERMS = {
    "api",
    "endpoint",
    "request",
    "response",
    "http",
    "path",
    "handler",
    "verify",
    "system",
    "behavior",
    "matches",
    "requested",
    "outcome",
    "described",
    "source",
    "prose",
    "get",
    "gets",
    "post",
    "posts",
    "put",
    "puts",
    "patch",
    "patches",
    "delete",
    "deletes",
    "list",
    "lists",
    "create",
    "creates",
    "update",
    "updates",
    "read",
    "reads",
}
