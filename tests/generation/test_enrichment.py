from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation.domain.models import NormalizedTestPlan, PlannedTestCase
from tools.generation.enrichment import EnrichedTestPlanResult, EvidenceToPlanEnricher, TestCaseReadiness
from tools.generation.evidence.models import (
    EvidenceConfidence,
    EvidenceProvenance,
    GenerationEvidenceBundle,
    GenerationEvidenceFact,
)


class EvidenceToPlanEnricherTests(unittest.TestCase):
    def test_applies_relevant_endpoint_evidence_to_case(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Create user",
                    objective="Verify create user.",
                    open_questions=[
                        "Which concrete API, UI action, data setup, or DB check should validate this case?"
                    ],
                )
            ]
        )
        bundle = _bundle([_endpoint_fact("fact-create-user", "/users", "POST", "create_user")])

        result = EvidenceToPlanEnricher().enrich(plan, bundle)
        enriched_case = result.enriched_plan.test_cases[0]

        self.assertEqual(result.applied_evidence[0].fact_id, "fact-create-user")
        self.assertEqual(result.case_enrichments[0].readiness_before, TestCaseReadiness.NEEDS_CLARIFICATION)
        self.assertEqual(result.case_enrichments[0].readiness_after, TestCaseReadiness.EVIDENCE_SUPPORTED)
        self.assertEqual(enriched_case.open_questions, [])
        self.assertEqual(enriched_case.metadata["readiness"], "evidence_supported")
        self.assertEqual(enriched_case.metadata["evidence_hints"][0]["applied_fields"]["endpoint_path"], "/users")
        self.assertEqual(enriched_case.metadata["route_hints"][0]["endpoint_path"], "/users")
        self.assertTrue(result.applied_evidence[0].match_reasons)
        self.assertEqual(result.traceability_links[0].source_ref, "evidence:fact-create-user")
        self.assertEqual(result.traceability_links[0].target_ref, "tc-001")

    def test_leaves_irrelevant_evidence_unapplied(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Create price list",
                    objective="Verify create price list.",
                )
            ]
        )
        bundle = _bundle([_endpoint_fact("fact-users", "/users", "POST", "create_user")])

        result = EvidenceToPlanEnricher().enrich(plan, bundle)

        self.assertEqual(result.applied_evidence, [])
        self.assertEqual(result.unapplied_evidence[0].reason_code, "no_relevant_case")
        self.assertNotIn("evidence_hints", result.enriched_plan.test_cases[0].metadata)

    def test_ambiguous_evidence_match_produces_diagnostic(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="User API",
                    objective="Verify user API behavior.",
                )
            ]
        )
        bundle = _bundle(
            [
                _endpoint_fact("fact-users-get", "/users", "GET", "get_users"),
                _endpoint_fact("fact-users-post", "/users", "POST", "create_users"),
            ]
        )

        result = EvidenceToPlanEnricher().enrich(plan, bundle)

        self.assertEqual(result.applied_evidence, [])
        self.assertTrue(any(diagnostic.code == "ambiguous_evidence_match" for diagnostic in result.diagnostics))
        self.assertEqual(
            {reason.reason_code for reason in result.unapplied_evidence},
            {"ambiguous_match"},
        )

    def test_low_confidence_evidence_is_not_applied_to_canonical_plan(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Create user",
                    objective="Verify create user.",
                )
            ]
        )
        bundle = _bundle(
            [
                _endpoint_fact(
                    "fact-weak",
                    "/users",
                    "POST",
                    "create_user",
                    confidence=EvidenceConfidence.WEAK_INFERENCE,
                )
            ]
        )

        result = EvidenceToPlanEnricher().enrich(plan, bundle)

        self.assertEqual(result.applied_evidence, [])
        self.assertEqual(result.unapplied_evidence[0].reason_code, "low_confidence_evidence")
        self.assertNotIn("evidence_hints", result.enriched_plan.test_cases[0].metadata)

    def test_conflicting_method_produces_diagnostic_without_applying_fact(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Create user",
                    objective="Verify create user.",
                )
            ]
        )
        bundle = _bundle([_endpoint_fact("fact-users-get", "/users", "GET", "get_user")])

        result = EvidenceToPlanEnricher().enrich(plan, bundle)

        self.assertEqual(result.applied_evidence, [])
        self.assertTrue(
            any(diagnostic.code == "evidence_conflicts_with_case_action" for diagnostic in result.diagnostics)
        )

    def test_enrichment_result_round_trips_through_dict(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Create user",
                    objective="Verify create user.",
                )
            ]
        )
        bundle = _bundle([_endpoint_fact("fact-create-user", "/users", "POST", "create_user")])
        result = EvidenceToPlanEnricher().enrich(plan, bundle)

        restored = EnrichedTestPlanResult.from_dict(result.to_dict())

        self.assertEqual(restored.enriched_plan.plan_id, "plan-users")
        self.assertEqual(restored.applied_evidence[0].confidence, EvidenceConfidence.EXPLICIT)
        self.assertEqual(restored.case_enrichments[0].readiness_after, TestCaseReadiness.EVIDENCE_SUPPORTED)

    def test_java_spring_authenticate_case_matches_authenticate_route(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Authenticate session",
                    objective="Verify authenticate session endpoint.",
                )
            ]
        )
        bundle = _bundle(
            [
                _endpoint_fact(
                    "fact-authenticate",
                    "/api/sessions/authenticate",
                    "POST",
                    "authenticateSession",
                    controller="SessionController",
                    framework_hint="spring_post_mapping",
                    source_kind="java_spring_annotations",
                )
            ]
        )

        result = EvidenceToPlanEnricher().enrich(plan, bundle)

        self.assertEqual(result.applied_evidence[0].fact_id, "fact-authenticate")
        self.assertIn("action_overlap:authenticate", result.applied_evidence[0].match_reasons)
        self.assertEqual(
            result.enriched_plan.test_cases[0].metadata["route_hints"][0]["controller_name"],
            "SessionController",
        )

    def test_java_spring_list_and_get_session_routes_match_distinct_cases(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-list",
                    title="List sessions",
                    objective="Verify list sessions endpoint.",
                ),
                PlannedTestCase(
                    case_id="tc-get",
                    title="Get session by id",
                    objective="Verify get session details by id.",
                ),
            ]
        )
        bundle = _bundle(
            [
                _endpoint_fact(
                    "fact-list",
                    "/api/sessions",
                    "GET",
                    "listSessions",
                    controller="SessionController",
                    framework_hint="spring_get_mapping",
                    source_kind="java_spring_annotations",
                ),
                _endpoint_fact(
                    "fact-get",
                    "/api/sessions/{id}",
                    "GET",
                    "getSession",
                    controller="SessionController",
                    framework_hint="spring_get_mapping",
                    source_kind="java_spring_annotations",
                ),
            ]
        )

        result = EvidenceToPlanEnricher().enrich(plan, bundle)

        self.assertEqual(len(result.applied_evidence), 2)
        route_hints = {
            case.case_id: case.metadata["route_hints"][0]["endpoint_path"]
            for case in result.enriched_plan.test_cases
        }
        self.assertEqual(route_hints["tc-list"], "/api/sessions")
        self.assertEqual(route_hints["tc-get"], "/api/sessions/{id}")

    def test_java_spring_revoke_one_and_revoke_all_routes_match_distinct_cases(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-revoke-one",
                    title="Revoke one session",
                    objective="Verify revoke session endpoint for one session.",
                ),
                PlannedTestCase(
                    case_id="tc-revoke-all",
                    title="Revoke all sessions",
                    objective="Verify revoke all sessions endpoint.",
                ),
            ]
        )
        bundle = _bundle(
            [
                _endpoint_fact(
                    "fact-revoke-one",
                    "/api/sessions/{id}/revoke",
                    "POST",
                    "revokeSession",
                    controller="SessionController",
                    framework_hint="spring_post_mapping",
                    source_kind="java_spring_annotations",
                ),
                _endpoint_fact(
                    "fact-revoke-all",
                    "/api/sessions/revoke-all",
                    "POST",
                    "revokeAllSessions",
                    controller="SessionController",
                    framework_hint="spring_post_mapping",
                    source_kind="java_spring_annotations",
                ),
            ]
        )

        result = EvidenceToPlanEnricher().enrich(plan, bundle)

        self.assertEqual(len(result.applied_evidence), 2)
        route_hints = {
            case.case_id: case.metadata["route_hints"][0]["endpoint_path"]
            for case in result.enriched_plan.test_cases
        }
        self.assertEqual(route_hints["tc-revoke-one"], "/api/sessions/{id}/revoke")
        self.assertEqual(route_hints["tc-revoke-all"], "/api/sessions/revoke-all")
        self.assertIn(
            "targets_all_entities",
            result.enriched_plan.test_cases[1].metadata["route_hints"][0]["match_reasons"],
        )

    def test_extracted_route_fact_without_matching_case_emits_unmatched_diagnostic(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Create user",
                    objective="Verify create user.",
                )
            ]
        )
        bundle = _bundle(
            [
                _endpoint_fact(
                    "fact-sessions-list",
                    "/api/sessions",
                    "GET",
                    "listSessions",
                    controller="SessionController",
                    framework_hint="spring_get_mapping",
                    source_kind="java_spring_annotations",
                )
            ]
        )

        result = EvidenceToPlanEnricher().enrich(plan, bundle)

        self.assertEqual(result.applied_evidence, [])
        self.assertTrue(any(d.code == "extracted_fact_unmatched" for d in result.diagnostics))
        self.assertEqual(result.unapplied_evidence[0].reason_code, "no_relevant_case")

    def test_ambiguous_java_route_match_emits_case_ambiguity_diagnostic(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Session API",
                    objective="Verify session API endpoints.",
                )
            ]
        )
        bundle = _bundle(
            [
                _endpoint_fact(
                    "fact-list",
                    "/api/sessions",
                    "GET",
                    "listSessions",
                    controller="SessionController",
                    framework_hint="spring_get_mapping",
                    source_kind="java_spring_annotations",
                ),
                _endpoint_fact(
                    "fact-create",
                    "/api/sessions",
                    "POST",
                    "createSession",
                    controller="SessionController",
                    framework_hint="spring_post_mapping",
                    source_kind="java_spring_annotations",
                ),
            ]
        )

        result = EvidenceToPlanEnricher().enrich(plan, bundle)

        self.assertEqual(result.applied_evidence, [])
        self.assertTrue(any(d.code == "case_match_ambiguous" for d in result.diagnostics))
        self.assertEqual({reason.reason_code for reason in result.unapplied_evidence}, {"ambiguous_match"})

    def test_route_resolved_readiness_is_used_when_non_route_questions_remain(self) -> None:
        plan = _plan(
            [
                PlannedTestCase(
                    case_id="tc-001",
                    title="Get session by id",
                    objective="Verify get session details by id.",
                    open_questions=[
                        "Which concrete API endpoint should validate this case?",
                        "Which authorization model should be used?",
                    ],
                )
            ]
        )
        bundle = _bundle(
            [
                _endpoint_fact(
                    "fact-get",
                    "/api/sessions/{id}",
                    "GET",
                    "getSession",
                    controller="SessionController",
                    framework_hint="spring_get_mapping",
                    source_kind="java_spring_annotations",
                )
            ]
        )

        result = EvidenceToPlanEnricher().enrich(plan, bundle)

        enriched_case = result.enriched_plan.test_cases[0]
        self.assertEqual(result.case_enrichments[0].readiness_after, TestCaseReadiness.ROUTE_RESOLVED)
        self.assertEqual(enriched_case.metadata["readiness"], "route_resolved")
        self.assertEqual(enriched_case.open_questions, ["Which authorization model should be used?"])


def _plan(cases: list[PlannedTestCase]) -> NormalizedTestPlan:
    return NormalizedTestPlan(
        plan_id="plan-users",
        source_id="users",
        project="code/demo",
        title="Users",
        test_cases=cases,
    )


def _bundle(facts: list[GenerationEvidenceFact]) -> GenerationEvidenceBundle:
    return GenerationEvidenceBundle(
        bundle_id="evidence-api",
        target_project="code/demo",
        scope="api",
        facts=facts,
        created_at="2026-04-23T08:00:00+00:00",
    )


def _endpoint_fact(
    fact_id: str,
    path: str,
    method: str,
    handler: str,
    *,
    confidence: EvidenceConfidence = EvidenceConfidence.EXPLICIT,
    controller: str | None = None,
    framework_hint: str = "method_decorator",
    source_kind: str = "python_ast",
) -> GenerationEvidenceFact:
    return GenerationEvidenceFact(
        fact_id=fact_id,
        fact_type="api_endpoint",
        summary=f"{method} {path} handled by {handler}",
        payload={
            "endpoint_path": path,
            "http_method": method,
            "handler_name": handler,
            "framework_hint": framework_hint,
            "controller_name": controller,
        },
        provenance=EvidenceProvenance(
            source_kind=source_kind,
            file_path=Path("app/api.py"),
            symbol=handler,
            line_range=(1, 2),
        ),
        confidence=confidence,
        related_interfaces=[path],
    )


if __name__ == "__main__":
    unittest.main()
