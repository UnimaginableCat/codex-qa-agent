"""Deterministic evidence-to-plan enrichment services."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from tools.generation.domain.models import (
    DiagnosticSeverity,
    GapCategory,
    GenerationDiagnostic,
    NormalizedTestPlan,
    PlannedCaseSupport,
    PlannedCaseGap,
    PlannedTestCase,
    RouteSupportHint,
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
    CoverageCaseAssessment,
    CoverageFactAssessment,
    CoverageAssessmentResult,
    CoverageSuggestedCase,
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

    min_match_score: int = 3

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
        fact_candidate_case_ids: dict[str, list[str]] = {
            fact.fact_id: [] for fact in evidence_bundle.facts if fact.fact_type == "api_endpoint"
        }
        unapplied_fact_ids: set[str] = set()

        for test_case in enriched_plan.test_cases:
            readiness_before = _case_readiness(test_case)
            candidates = self._rank_candidates(test_case, evidence_bundle.facts)
            for candidate in candidates:
                if candidate.score < self.min_match_score:
                    continue
                fact_candidate_case_ids.setdefault(candidate.fact.fact_id, [])
                if test_case.case_id not in fact_candidate_case_ids[candidate.fact.fact_id]:
                    fact_candidate_case_ids[candidate.fact.fact_id].append(test_case.case_id)

            top_score = candidates[0].score if candidates else 0
            top_candidates = [
                candidate
                for candidate in candidates
                if candidate.score == top_score and candidate.score >= self.min_match_score
            ]

            case_diagnostics: list[GenerationDiagnostic] = []
            case_applied: list[AppliedEvidenceLink] = []
            resolved_questions: list[str] = []
            resolved_gaps: list[GapCategory] = []

            if len(top_candidates) > 1:
                candidate_ids = [candidate.fact.fact_id for candidate in top_candidates]
                ambiguous_fact_ids.update(candidate_ids)
                diagnostic = GenerationDiagnostic(
                    code="case_match_ambiguous",
                    message="Multiple evidence facts matched the planned case with the same deterministic score.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=test_case.case_id,
                    details={"candidate_fact_ids": candidate_ids},
                )
                legacy_diagnostic = GenerationDiagnostic(
                    code="ambiguous_evidence_match",
                    message="Multiple evidence facts matched the planned case with the same score.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=test_case.case_id,
                    details={"candidate_fact_ids": candidate_ids},
                )
                case_diagnostics.append(diagnostic)
                case_diagnostics.append(legacy_diagnostic)
                diagnostics.append(diagnostic)
                diagnostics.append(legacy_diagnostic)
            elif len(top_candidates) == 1:
                candidate = top_candidates[0]
                fact = candidate.fact
                planned_route_conflict = _planned_route_conflict(test_case, fact)
                conflict = _method_conflict(test_case, fact)
                if planned_route_conflict is not None:
                    diagnostic = GenerationDiagnostic(
                        code="planned_route_conflicts_with_evidence",
                        message="Agent-authored planned route conflicts with extracted route evidence.",
                        severity=DiagnosticSeverity.WARNING,
                        source_ref=test_case.case_id,
                        details={"fact_id": fact.fact_id, **planned_route_conflict},
                    )
                    case_diagnostics.append(diagnostic)
                    diagnostics.append(diagnostic)
                    unapplied_evidence.append(
                        UnappliedEvidenceReason(
                            fact_id=fact.fact_id,
                            reason_code="planned_route_conflict",
                            message="Evidence route conflicts with the agent-authored planned route.",
                            candidate_case_ids=[test_case.case_id],
                            details=planned_route_conflict,
                        )
                    )
                    unapplied_fact_ids.add(fact.fact_id)
                elif conflict:
                    diagnostic = GenerationDiagnostic(
                        code="evidence_conflicts_with_case_action",
                        message="Evidence HTTP method conflicts with action implied by the planned case.",
                        severity=DiagnosticSeverity.WARNING,
                        source_ref=test_case.case_id,
                        details={"fact_id": fact.fact_id, "expected_methods": sorted(conflict)},
                    )
                    case_diagnostics.append(diagnostic)
                    diagnostics.append(diagnostic)
                    unapplied_evidence.append(
                        UnappliedEvidenceReason(
                            fact_id=fact.fact_id,
                            reason_code="conflicting_case_action",
                            message="Evidence route conflicts with the case action implied by prose.",
                            candidate_case_ids=[test_case.case_id],
                            details={"expected_methods": sorted(conflict)},
                        )
                    )
                    unapplied_fact_ids.add(fact.fact_id)
                elif fact.confidence == EvidenceConfidence.WEAK_INFERENCE:
                    diagnostic = GenerationDiagnostic(
                        code="route_fact_not_applied_due_to_low_confidence",
                        message="Route evidence was not applied because its confidence is too low.",
                        severity=DiagnosticSeverity.WARNING,
                        source_ref=test_case.case_id,
                        details={"fact_id": fact.fact_id},
                    )
                    case_diagnostics.append(diagnostic)
                    diagnostics.append(diagnostic)
                    unapplied_evidence.append(
                        UnappliedEvidenceReason(
                            fact_id=fact.fact_id,
                            reason_code="low_confidence_evidence",
                            message="Weak inference evidence was not applied to the canonical plan.",
                            candidate_case_ids=[test_case.case_id],
                        )
                    )
                    unapplied_fact_ids.add(fact.fact_id)
                else:
                    link = _build_applied_link(test_case, fact, candidate.match_reasons)
                    case_applied.append(link)
                    applied_evidence.append(link)
                    applied_fact_ids.add(fact.fact_id)
                    resolved_gaps = _resolve_case_gaps(test_case, fact)
                    resolved_questions = _resolve_open_questions(test_case, resolved_gaps)
                    _apply_evidence_to_case(test_case, fact, link, resolved_questions, resolved_gaps)
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
            candidate_case_ids = fact_candidate_case_ids.get(fact.fact_id, [])
            if fact.fact_id in ambiguous_fact_ids:
                diagnostics.append(
                    GenerationDiagnostic(
                        code="case_match_ambiguous",
                        message="Extracted route fact was not applied because the target case match was ambiguous.",
                        severity=DiagnosticSeverity.WARNING,
                        source_ref=fact.fact_id,
                        details={"candidate_case_ids": candidate_case_ids},
                    )
                )
                unapplied_evidence.append(
                    UnappliedEvidenceReason(
                        fact_id=fact.fact_id,
                        reason_code="ambiguous_match",
                        message="Evidence matched multiple candidates or tied with another fact.",
                        candidate_case_ids=candidate_case_ids,
                    )
                )
                continue
            if fact.fact_id in unapplied_fact_ids:
                continue
            if fact.confidence == EvidenceConfidence.WEAK_INFERENCE:
                if not any(reason.fact_id == fact.fact_id for reason in unapplied_evidence):
                    diagnostics.append(
                        GenerationDiagnostic(
                            code="route_fact_not_applied_due_to_low_confidence",
                            message="Extracted route fact was left unapplied because it is weak inference only.",
                            severity=DiagnosticSeverity.WARNING,
                            source_ref=fact.fact_id,
                            details={"candidate_case_ids": candidate_case_ids},
                        )
                    )
                    unapplied_evidence.append(
                        UnappliedEvidenceReason(
                            fact_id=fact.fact_id,
                            reason_code="low_confidence_evidence",
                            message="Weak inference evidence was not applied to the canonical plan.",
                            candidate_case_ids=candidate_case_ids,
                        )
                    )
                continue
            if len(candidate_case_ids) > 1:
                diagnostics.append(
                    GenerationDiagnostic(
                        code="multiple_candidate_cases",
                        message="Extracted route fact matched multiple candidate cases and was not force-applied.",
                        severity=DiagnosticSeverity.WARNING,
                        source_ref=fact.fact_id,
                        details={"candidate_case_ids": candidate_case_ids},
                    )
                )
                unapplied_evidence.append(
                    UnappliedEvidenceReason(
                        fact_id=fact.fact_id,
                        reason_code="multiple_candidate_cases",
                        message="Evidence matched multiple candidate cases and was not force-applied.",
                        candidate_case_ids=candidate_case_ids,
                    )
                )
                continue
            diagnostics.append(
                GenerationDiagnostic(
                    code="extracted_fact_unmatched",
                    message="Extracted route fact was not applied to any planned case.",
                    severity=DiagnosticSeverity.INFO,
                    source_ref=fact.fact_id,
                    details={"candidate_case_ids": candidate_case_ids},
                )
            )
            unapplied_evidence.append(
                UnappliedEvidenceReason(
                    fact_id=fact.fact_id,
                    reason_code="no_relevant_case",
                    message="No planned test case matched this evidence strongly enough.",
                    candidate_case_ids=candidate_case_ids,
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
    ) -> list["MatchCandidate"]:
        scored = [_match_candidate(test_case, fact) for fact in facts if fact.fact_type == "api_endpoint"]
        return sorted(scored, key=lambda item: (-item.score, item.fact.fact_id))


@dataclass(slots=True)
class TestPlanCoverageAnalyzer:
    """Project explicit code facts into a simple authored-plan coverage view."""

    min_match_score: int = 3

    def assess(
        self,
        plan: NormalizedTestPlan,
        evidence_bundle: GenerationEvidenceBundle,
    ) -> CoverageAssessmentResult:
        api_cases = [case for case in plan.test_cases if _is_api_case(case)]
        strong_facts = [
            fact
            for fact in evidence_bundle.facts
            if fact.fact_type == "api_endpoint" and fact.confidence != EvidenceConfidence.WEAK_INFERENCE
        ]
        weak_fact_ids = [
            fact.fact_id
            for fact in evidence_bundle.facts
            if fact.fact_type == "api_endpoint" and fact.confidence == EvidenceConfidence.WEAK_INFERENCE
        ]

        covered_case_ids: list[str] = []
        uncovered_case_ids: list[str] = []
        covered_fact_ids: set[str] = set()
        ambiguous_case_ids: list[str] = []
        duplicated_fact_ids: list[str] = []
        case_assessments: list[CoverageCaseAssessment] = []
        fact_assessments: list[CoverageFactAssessment] = []
        diagnostics: list[GenerationDiagnostic] = []
        fact_to_case_ids: dict[str, list[str]] = {fact.fact_id: [] for fact in strong_facts}

        for test_case in api_cases:
            candidates = [
                candidate
                for candidate in (_match_candidate(test_case, fact) for fact in strong_facts)
                if candidate.score >= self.min_match_score and _coverage_candidate_supported(test_case, candidate)
            ]
            if not candidates:
                uncovered_case_ids.append(test_case.case_id)
                case_assessments.append(
                    CoverageCaseAssessment(
                        case_id=test_case.case_id,
                        title=test_case.title,
                        status="uncovered",
                        planned_http_method=(
                            ""
                            if test_case.planned_route is None
                            else test_case.planned_route.http_method
                        ),
                        planned_endpoint_path=(
                            ""
                            if test_case.planned_route is None
                            else test_case.planned_route.endpoint_path
                        ),
                    )
                )
                diagnostics.append(
                    GenerationDiagnostic(
                        code="api_case_not_covered_by_evidence",
                        message="No extracted API endpoint fact matched this planned API case strongly enough.",
                        severity=DiagnosticSeverity.WARNING,
                        source_ref=test_case.case_id,
                    )
                )
                continue
            covered_case_ids.append(test_case.case_id)
            matched_fact_ids = [candidate.fact.fact_id for candidate in candidates]
            covered_fact_ids.update(matched_fact_ids)
            for fact_id in matched_fact_ids:
                fact_to_case_ids.setdefault(fact_id, [])
                if test_case.case_id not in fact_to_case_ids[fact_id]:
                    fact_to_case_ids[fact_id].append(test_case.case_id)
            if len(matched_fact_ids) > 1:
                ambiguous_case_ids.append(test_case.case_id)
                diagnostics.append(
                    GenerationDiagnostic(
                        code="api_case_matches_multiple_endpoint_facts",
                        message="Planned API case matches multiple extracted endpoint facts and may be too broad.",
                        severity=DiagnosticSeverity.WARNING,
                        source_ref=test_case.case_id,
                        details={"candidate_fact_ids": matched_fact_ids},
                    )
                )
            case_assessments.append(
                CoverageCaseAssessment(
                    case_id=test_case.case_id,
                    title=test_case.title,
                    matched_fact_ids=matched_fact_ids,
                    status="ambiguous" if len(matched_fact_ids) > 1 else "covered",
                    planned_http_method=(
                        ""
                        if test_case.planned_route is None
                        else test_case.planned_route.http_method
                    ),
                    planned_endpoint_path=(
                        ""
                        if test_case.planned_route is None
                        else test_case.planned_route.endpoint_path
                    ),
                )
            )

        uncovered_fact_ids: list[str] = []
        for fact in strong_facts:
            matched_case_ids = fact_to_case_ids.get(fact.fact_id, [])
            fact_assessments.append(
                CoverageFactAssessment(
                    fact_id=fact.fact_id,
                    endpoint_path=str(fact.payload.get("endpoint_path") or ""),
                    http_method=str(fact.payload.get("http_method") or "").upper(),
                    handler_name=str(fact.payload.get("handler_name") or ""),
                    controller_name=str(fact.payload.get("controller_name") or ""),
                    matched_case_ids=matched_case_ids,
                    status=(
                        "uncovered"
                        if not matched_case_ids
                        else "duplicated"
                        if len(matched_case_ids) > 1
                        else "covered"
                    ),
                    suggested_case=None if matched_case_ids else _suggest_case_for_fact(fact),
                )
            )
            if fact.fact_id in covered_fact_ids:
                if len(matched_case_ids) > 1:
                    duplicated_fact_ids.append(fact.fact_id)
                    diagnostics.append(
                        GenerationDiagnostic(
                            code="api_endpoint_fact_matched_by_multiple_cases",
                            message="Extracted API endpoint fact is covered by multiple planned cases and may indicate overlap.",
                            severity=DiagnosticSeverity.WARNING,
                            source_ref=fact.fact_id,
                            details={"candidate_case_ids": matched_case_ids},
                        )
                    )
                continue
            uncovered_fact_ids.append(fact.fact_id)
            diagnostics.append(
                GenerationDiagnostic(
                    code="api_endpoint_fact_not_covered_by_plan",
                    message="Extracted API endpoint fact is not covered by any authored planned case.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=fact.fact_id,
                    details={
                        "endpoint_path": str(fact.payload.get("endpoint_path") or ""),
                        "http_method": str(fact.payload.get("http_method") or "").upper(),
                        "handler_name": str(fact.payload.get("handler_name") or ""),
                        "controller_name": str(fact.payload.get("controller_name") or ""),
                        "suggested_case": _suggest_case_for_fact(fact).to_dict(),
                    },
                )
            )

        return CoverageAssessmentResult(
            api_case_count=len(api_cases),
            api_fact_count=len(strong_facts),
            covered_case_ids=covered_case_ids,
            uncovered_case_ids=uncovered_case_ids,
            covered_fact_ids=sorted(covered_fact_ids),
            uncovered_fact_ids=uncovered_fact_ids,
            ambiguous_case_ids=ambiguous_case_ids,
            duplicated_fact_ids=duplicated_fact_ids,
            weak_fact_ids=weak_fact_ids,
            case_assessments=case_assessments,
            fact_assessments=fact_assessments,
            diagnostics=diagnostics,
        )


@dataclass(slots=True)
class MatchCandidate:
    fact: GenerationEvidenceFact
    score: int
    match_reasons: list[str] = field(default_factory=list)


def _build_applied_link(
    test_case: PlannedTestCase,
    fact: GenerationEvidenceFact,
    match_reasons: list[str],
) -> AppliedEvidenceLink:
    applied_fields = {
        "endpoint_path": fact.payload.get("endpoint_path"),
        "http_method": fact.payload.get("http_method"),
        "handler_name": fact.payload.get("handler_name"),
        "controller_name": fact.payload.get("controller_name"),
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
        match_reasons=match_reasons,
    )


def _is_api_case(test_case: PlannedTestCase) -> bool:
    kind = str(test_case.metadata.get("kind") or "").strip().lower()
    return kind == "api" or test_case.planned_route is not None


def _apply_evidence_to_case(
    test_case: PlannedTestCase,
    fact: GenerationEvidenceFact,
    link: AppliedEvidenceLink,
    resolved_questions: list[str],
    resolved_gaps: list[GapCategory],
) -> None:
    evidence_hints = list(test_case.metadata.get("evidence_hints", []))
    evidence_hints.append(link.to_dict())
    route_hints = list(test_case.metadata.get("route_hints", []))
    route_hint = RouteSupportHint(
        fact_id=link.fact_id,
        endpoint_path=str(link.applied_fields.get("endpoint_path") or ""),
        http_method=str(link.applied_fields.get("http_method") or ""),
        confidence=link.confidence.value,
        handler_name=str(link.applied_fields.get("handler_name") or ""),
        controller_name=str(link.applied_fields.get("controller_name") or ""),
        framework_hint=str(link.applied_fields.get("framework_hint") or ""),
        match_reasons=list(link.match_reasons),
        route_source="route_hints",
    )
    route_hints.append(route_hint.to_dict())
    readiness = _readiness_from_fact(fact, resolved_gaps, test_case.gaps, resolved_questions, test_case.open_questions)
    support = test_case.support or PlannedCaseSupport()
    support.readiness = readiness.value
    support.route_hints = [*support.route_hints, route_hint]
    test_case.metadata = {
        **test_case.metadata,
        "evidence_hints": evidence_hints,
        "route_hints": route_hints,
        "readiness": readiness.value,
    }
    test_case.support = support
    readiness_tag = "route-resolved" if readiness == TestCaseReadiness.ROUTE_RESOLVED else "evidence-supported"
    if readiness_tag not in test_case.tags:
        test_case.tags.append(readiness_tag)
    if resolved_questions:
        test_case.metadata["resolved_open_questions"] = resolved_questions
        test_case.open_questions = [
            question for question in test_case.open_questions if question not in resolved_questions
        ]
    if resolved_gaps:
        test_case.metadata["resolved_gaps"] = [gap.value for gap in resolved_gaps]
        test_case.gaps = [gap for gap in test_case.gaps if gap.category not in resolved_gaps]


def _match_candidate(test_case: PlannedTestCase, fact: GenerationEvidenceFact) -> MatchCandidate:
    if fact.confidence == EvidenceConfidence.WEAK_INFERENCE:
        return MatchCandidate(fact=fact, score=0)
    planned_route_candidate = _planned_route_candidate(test_case, fact)
    if planned_route_candidate is not None and planned_route_candidate.score > 0:
        return planned_route_candidate
    case_terms = _case_terms(test_case)
    fact_terms = _fact_terms(fact)
    entity_overlap = case_terms & fact_terms
    case_actions = _case_actions(test_case)
    fact_actions = _fact_actions(fact)
    action_overlap = case_actions & fact_actions
    if not entity_overlap and not action_overlap:
        return MatchCandidate(fact=fact, score=0)
    if not entity_overlap and not (action_overlap & {"authenticate"}):
        return MatchCandidate(fact=fact, score=0)

    score = min(len(entity_overlap) * 2, 4)
    match_reasons: list[str] = []
    if entity_overlap:
        match_reasons.append("entity_overlap:" + ",".join(sorted(entity_overlap)))

    if action_overlap:
        action_score = 5 if "revoke_all" in action_overlap else 4
        score += action_score
        match_reasons.append("action_overlap:" + ",".join(sorted(action_overlap)))

    method = str(fact.payload.get("http_method") or "").upper()
    case_methods = _case_action_methods(test_case)
    if method and method in case_methods:
        score += 2
        match_reasons.append(f"http_method:{method}")

    handler_name = str(fact.payload.get("handler_name") or "")
    controller_name = str(fact.payload.get("controller_name") or "")
    handler_terms = _split_identifier(handler_name)
    controller_terms = _split_identifier(controller_name)
    if case_terms & handler_terms:
        score += 1
        match_reasons.append("handler_overlap:" + ",".join(sorted(case_terms & handler_terms)))
    if case_terms & controller_terms:
        score += 1
        match_reasons.append("controller_overlap:" + ",".join(sorted(case_terms & controller_terms)))

    endpoint_path = str(fact.payload.get("endpoint_path") or "")
    if "get" in case_actions and _path_has_identifier(endpoint_path):
        score += 2
        match_reasons.append("path_has_identifier")
    if "list" in case_actions and not _path_has_identifier(endpoint_path):
        score += 2
        match_reasons.append("collection_route")
    if "revoke_all" in case_actions and _fact_targets_all(fact):
        score += 3
        match_reasons.append("targets_all_entities")
    if "revoke" in case_actions and "revoke_all" not in case_actions and _path_has_identifier(endpoint_path):
        score += 1
        match_reasons.append("single_resource_route")
    if _case_mentions_identifier(test_case) and _path_has_identifier(endpoint_path):
        score += 1
        match_reasons.append("case_mentions_identifier")

    return MatchCandidate(fact=fact, score=max(score, 0), match_reasons=match_reasons)


def _planned_route_candidate(
    test_case: PlannedTestCase,
    fact: GenerationEvidenceFact,
) -> MatchCandidate | None:
    planned_route = test_case.planned_route
    if planned_route is None:
        return None
    planned_method = planned_route.http_method.strip().upper()
    planned_path = planned_route.endpoint_path.strip()
    if not planned_method or not planned_path:
        return MatchCandidate(fact=fact, score=0)

    fact_method = str(fact.payload.get("http_method") or "").upper()
    fact_path = str(fact.payload.get("endpoint_path") or "")
    if not fact_method or not fact_path:
        return MatchCandidate(fact=fact, score=0)

    exact_path = _normalize_route_path(planned_path) == _normalize_route_path(fact_path)
    route_family_match = _same_route_family(planned_path, fact_path)
    match_reasons: list[str] = []

    if exact_path and fact_method == planned_method:
        match_reasons.append("planned_route_exact")
        return MatchCandidate(fact=fact, score=100, match_reasons=match_reasons)

    if route_family_match and fact_method == planned_method:
        match_reasons.append("planned_route_family_match")
        return MatchCandidate(fact=fact, score=80, match_reasons=match_reasons)

    if exact_path and fact_method != planned_method:
        match_reasons.append("planned_route_method_conflict")
        return MatchCandidate(fact=fact, score=15, match_reasons=match_reasons)

    return MatchCandidate(fact=fact, score=0)


def _method_conflict(test_case: PlannedTestCase, fact: GenerationEvidenceFact) -> set[str]:
    method = str(fact.payload.get("http_method") or "").upper()
    case_methods = _case_action_methods(test_case)
    if method and case_methods and method not in case_methods:
        return case_methods
    return set()


def _planned_route_conflict(
    test_case: PlannedTestCase,
    fact: GenerationEvidenceFact,
) -> dict[str, str] | None:
    planned_route = test_case.planned_route
    if planned_route is None:
        return None
    planned_method = planned_route.http_method.strip().upper()
    planned_path = planned_route.endpoint_path.strip()
    fact_method = str(fact.payload.get("http_method") or "").upper()
    fact_path = str(fact.payload.get("endpoint_path") or "")
    if not planned_method or not planned_path or not fact_method or not fact_path:
        return None
    if planned_method == fact_method and _same_route_family(planned_path, fact_path):
        return None
    return {
        "planned_http_method": planned_method,
        "planned_endpoint_path": planned_path,
        "evidence_http_method": fact_method,
        "evidence_endpoint_path": fact_path,
    }


def _coverage_candidate_supported(
    test_case: PlannedTestCase,
    candidate: MatchCandidate,
) -> bool:
    fact = candidate.fact
    if _planned_route_conflict(test_case, fact) is not None:
        return False
    if _method_conflict(test_case, fact):
        return False
    if any(
        reason in {"planned_route_exact", "planned_route_family_match"}
        for reason in candidate.match_reasons
    ):
        return True
    return any(
        reason.startswith("action_overlap:") or reason.startswith("http_method:")
        for reason in candidate.match_reasons
    )


def _suggest_case_for_fact(fact: GenerationEvidenceFact) -> CoverageSuggestedCase:
    method = str(fact.payload.get("http_method") or "").upper()
    endpoint_path = str(fact.payload.get("endpoint_path") or "")
    resource_label = _suggested_resource_label(fact)
    return CoverageSuggestedCase(
        title=_suggested_case_title(method, endpoint_path, resource_label),
        objective=_suggested_case_objective(method, endpoint_path, resource_label),
        http_method=method,
        endpoint_path=endpoint_path,
    )


def _suggested_resource_label(fact: GenerationEvidenceFact) -> str:
    segments = [
        segment
        for segment in str(fact.payload.get("endpoint_path") or "").strip("/").split("/")
        if segment and not segment.startswith("{")
    ]
    ignored = {"api", "internal", "v1", "v2", "v3"}
    candidates = [segment for segment in segments if segment.lower() not in ignored]
    if candidates:
        label = candidates[-1]
    else:
        handler_terms = _split_identifier(str(fact.payload.get("handler_name") or ""))
        controller_terms = _split_identifier(str(fact.payload.get("controller_name") or ""))
        combined = [term for term in sorted(handler_terms | controller_terms) if term not in ignored]
        label = combined[0] if combined else "resource"
    return label[:-1] if label.endswith("s") and len(label) > 3 else label


def _suggested_case_title(method: str, endpoint_path: str, resource_label: str) -> str:
    resource = resource_label.replace("-", " ")
    if method == "GET" and _path_has_identifier(endpoint_path):
        return f"Get {resource} by id happy path"
    if method == "GET":
        return f"List {resource}s happy path"
    if method == "POST":
        return f"Create {resource} happy path"
    if method in {"PUT", "PATCH"}:
        return f"Update {resource} happy path"
    if method == "DELETE":
        return f"Delete {resource} happy path"
    return f"Cover {resource} endpoint behavior"


def _suggested_case_objective(method: str, endpoint_path: str, resource_label: str) -> str:
    resource = resource_label.replace("-", " ")
    if method == "GET" and _path_has_identifier(endpoint_path):
        return f"Verify an existing {resource} can be retrieved by identifier."
    if method == "GET":
        return f"Verify the {resource} collection can be listed successfully."
    if method == "POST":
        return f"Verify a new {resource} can be created with a valid request."
    if method in {"PUT", "PATCH"}:
        return f"Verify an existing {resource} can be updated with a valid request."
    if method == "DELETE":
        return f"Verify an existing {resource} can be deleted successfully."
    return f"Verify the {resource} endpoint matches its externally visible contract."


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


def _case_actions(test_case: PlannedTestCase) -> set[str]:
    text = _case_text(test_case).lower()
    actions: set[str] = set()
    phrase_markers = {
        "authenticate": ("authenticate", "authentication", "login", "sign in", "auth"),
        "revoke_all": ("revoke all", "invalidate all", "revoke-all", "revoke_all"),
    }
    token_markers = {
        "list": {"list", "browse"},
        "get": {"get", "fetch", "read", "detail", "details"},
        "create": {"create", "add", "register"},
        "update": {"update", "patch", "modify", "change"},
        "delete": {"delete", "remove"},
        "revoke": {"revoke", "invalidate"},
    }
    for action, markers in phrase_markers.items():
        if any(marker in text for marker in markers):
            actions.add(action)
    tokens = _tokenize(text)
    for action, markers in token_markers.items():
        if tokens & markers:
            actions.add(action)
    if "by id" in text or "missing entity" in text or "nonexistent id" in text:
        actions.add("get")
    return actions


def _case_readiness(test_case: PlannedTestCase) -> TestCaseReadiness:
    if test_case.support is not None and test_case.support.readiness in {item.value for item in TestCaseReadiness}:
        return TestCaseReadiness(test_case.support.readiness)
    readiness = str(test_case.metadata.get("readiness", ""))
    if readiness in {item.value for item in TestCaseReadiness}:
        return TestCaseReadiness(readiness)
    if test_case.metadata.get("evidence_hints"):
        return TestCaseReadiness.EVIDENCE_SUPPORTED
    if test_case.gaps:
        return TestCaseReadiness.NEEDS_CLARIFICATION
    if test_case.open_questions:
        return TestCaseReadiness.NEEDS_CLARIFICATION
    return TestCaseReadiness.PROSE_ONLY


def _readiness_from_fact(
    fact: GenerationEvidenceFact,
    resolved_gaps: list[GapCategory],
    current_gaps: list[PlannedCaseGap],
    resolved_questions: list[str],
    current_open_questions: list[str],
) -> TestCaseReadiness:
    if fact.confidence == EvidenceConfidence.EXPLICIT and fact.payload.get("http_method"):
        remaining_gaps = [
            gap for gap in current_gaps if gap.category not in resolved_gaps
        ]
        if remaining_gaps:
            return TestCaseReadiness.ROUTE_RESOLVED
        remaining_questions = [
            question for question in current_open_questions if question not in resolved_questions
        ]
        if remaining_questions:
            return TestCaseReadiness.ROUTE_RESOLVED
        return TestCaseReadiness.EVIDENCE_SUPPORTED
    return TestCaseReadiness.PARTIALLY_SUPPORTED


def _resolve_case_gaps(test_case: PlannedTestCase, fact: GenerationEvidenceFact) -> list[GapCategory]:
    if not fact.payload.get("endpoint_path") or not fact.payload.get("http_method"):
        return []
    resolved = [
        gap.category
        for gap in test_case.gaps
        if gap.category in {GapCategory.ENDPOINT_DETAIL, GapCategory.EXECUTABLE_DETAIL}
    ]
    if resolved:
        return resolved
    inferred = {
        _question_gap_category(question)
        for question in test_case.open_questions
    }
    return [
        category
        for category in (GapCategory.ENDPOINT_DETAIL, GapCategory.EXECUTABLE_DETAIL)
        if category in inferred
    ]


def _resolve_open_questions(test_case: PlannedTestCase, resolved_gaps: list[GapCategory]) -> list[str]:
    if not resolved_gaps:
        return []
    gap_set = set(resolved_gaps)
    gap_messages = {
        gap.message
        for gap in test_case.gaps
        if gap.category in gap_set
    }
    return [
        question
        for question in test_case.open_questions
        if _question_gap_category(question) in gap_set or question in gap_messages
    ]


def _question_gap_category(question: str) -> GapCategory:
    normalized = question.lower()
    if any(marker in normalized for marker in ("endpoint", "api endpoint", "which endpoint")):
        return GapCategory.ENDPOINT_DETAIL
    if any(marker in normalized for marker in ("executable detail", "concrete api", "ui action", "data setup", "db check")):
        return GapCategory.EXECUTABLE_DETAIL
    if any(marker in normalized for marker in ("auth", "authorization", "credentials")):
        return GapCategory.AUTH_STRATEGY
    if any(marker in normalized for marker in ("environment", "env")):
        return GapCategory.ENVIRONMENT
    return GapCategory.UNKNOWN


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
        str(fact.payload.get("controller_name") or ""),
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


def _fact_actions(fact: GenerationEvidenceFact) -> set[str]:
    method = str(fact.payload.get("http_method") or "").upper()
    endpoint_path = str(fact.payload.get("endpoint_path") or "")
    path_terms = _tokenize(endpoint_path.replace("{", " ").replace("}", " "))
    identifier_terms = _split_identifier(str(fact.payload.get("handler_name") or ""))
    identifier_terms.update(_split_identifier(str(fact.payload.get("controller_name") or "")))
    identifier_terms.update(path_terms)
    combined_text = " ".join(
        [
            str(fact.payload.get("handler_name") or ""),
            str(fact.payload.get("controller_name") or ""),
            endpoint_path,
        ]
    ).lower()

    actions: set[str] = set()
    if any(marker in combined_text for marker in ("authenticate", "authentication", "login", "auth")):
        actions.add("authenticate")
    if any(marker in combined_text for marker in ("revoke all", "invalidate all", "revoke-all", "revoke_all")):
        actions.add("revoke_all")
    if identifier_terms & {"revoke", "invalidate"}:
        actions.add("revoke")
    if identifier_terms & {"create", "add", "register"}:
        actions.add("create")
    if identifier_terms & {"update", "patch", "modify", "change"}:
        actions.add("update")
    if identifier_terms & {"delete", "remove"}:
        actions.add("delete")
    if identifier_terms & {"list", "browse"}:
        actions.add("list")
    if identifier_terms & {"get", "fetch", "read"}:
        actions.add("get")
    if "all" in identifier_terms and "revoke" in actions:
        actions.add("revoke_all")

    if method == "GET":
        actions.add("get" if _path_has_identifier(endpoint_path) else "list")
    elif method == "POST":
        if "authenticate" not in actions and "revoke" not in actions and "revoke_all" not in actions:
            actions.add("create")
    elif method in {"PATCH", "PUT"}:
        actions.add("update")
    elif method == "DELETE":
        if "revoke" not in actions:
            actions.add("delete")
    return actions


def _path_has_identifier(path: str) -> bool:
    return bool(re.search(r"\{[^}]+\}", path))


def _normalize_route_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path.strip())


def _same_route_family(left: str, right: str) -> bool:
    left_segments = [_normalize_route_segment(segment) for segment in left.strip("/").split("/") if segment]
    right_segments = [_normalize_route_segment(segment) for segment in right.strip("/").split("/") if segment]
    return left_segments == right_segments


def _normalize_route_segment(segment: str) -> str:
    return "{}" if re.fullmatch(r"\{[^}]+\}", segment) else segment


def _fact_targets_all(fact: GenerationEvidenceFact) -> bool:
    values = " ".join(
        [
            str(fact.payload.get("endpoint_path") or ""),
            str(fact.payload.get("handler_name") or ""),
            str(fact.payload.get("controller_name") or ""),
        ]
    ).lower()
    return "all" in _tokenize(values) or "revoke-all" in values or "revoke_all" in values


def _case_mentions_identifier(test_case: PlannedTestCase) -> bool:
    text = _case_text(test_case).lower()
    return any(marker in text for marker in (" by id", " id", "identifier", "missing entity", "nonexistent"))


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
