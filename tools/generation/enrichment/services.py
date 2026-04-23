"""Deterministic evidence-to-plan enrichment services."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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


def _apply_evidence_to_case(
    test_case: PlannedTestCase,
    fact: GenerationEvidenceFact,
    link: AppliedEvidenceLink,
    resolved_questions: list[str],
) -> None:
    evidence_hints = list(test_case.metadata.get("evidence_hints", []))
    evidence_hints.append(link.to_dict())
    route_hints = list(test_case.metadata.get("route_hints", []))
    route_hints.append(
        {
            "fact_id": link.fact_id,
            "confidence": link.confidence.value,
            "match_reasons": list(link.match_reasons),
            **link.applied_fields,
        }
    )
    readiness = _readiness_from_fact(fact, resolved_questions, test_case.open_questions)
    test_case.metadata = {
        **test_case.metadata,
        "evidence_hints": evidence_hints,
        "route_hints": route_hints,
        "readiness": readiness.value,
    }
    readiness_tag = "route-resolved" if readiness == TestCaseReadiness.ROUTE_RESOLVED else "evidence-supported"
    if readiness_tag not in test_case.tags:
        test_case.tags.append(readiness_tag)
    if resolved_questions:
        test_case.metadata["resolved_open_questions"] = resolved_questions
        test_case.open_questions = [
            question for question in test_case.open_questions if question not in resolved_questions
        ]


def _match_candidate(test_case: PlannedTestCase, fact: GenerationEvidenceFact) -> MatchCandidate:
    if fact.confidence == EvidenceConfidence.WEAK_INFERENCE:
        return MatchCandidate(fact=fact, score=0)
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
    readiness = str(test_case.metadata.get("readiness", ""))
    if readiness in {item.value for item in TestCaseReadiness}:
        return TestCaseReadiness(readiness)
    if test_case.metadata.get("evidence_hints"):
        return TestCaseReadiness.EVIDENCE_SUPPORTED
    if test_case.open_questions:
        return TestCaseReadiness.NEEDS_CLARIFICATION
    return TestCaseReadiness.PROSE_ONLY


def _readiness_from_fact(
    fact: GenerationEvidenceFact,
    resolved_questions: list[str],
    current_open_questions: list[str],
) -> TestCaseReadiness:
    if fact.confidence == EvidenceConfidence.EXPLICIT and fact.payload.get("http_method"):
        remaining_questions = [
            question for question in current_open_questions if question not in resolved_questions
        ]
        if remaining_questions:
            return TestCaseReadiness.ROUTE_RESOLVED
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
