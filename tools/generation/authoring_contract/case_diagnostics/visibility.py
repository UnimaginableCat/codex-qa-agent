"""Visibility-claim diagnostics for compact authoring cases."""

from __future__ import annotations

import re
from typing import Any

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic

from .policy import case_contract_section, plan_contract_section, policy_bool
from ..diagnostics import authoring_diagnostic
from ..models import AuthoringCase, AuthoringPlan

_VISIBILITY_CLAIM_PATTERN = re.compile(
    r"\b(?:mask|masked|masking|leak|leaks|visibility|visible|can_view_price|can_view_cost|cost_price|selling price)\b",
    re.IGNORECASE,
)
_VISIBILITY_ASSERTION_PATTERN = re.compile(
    r"(?:response\s+)?`?(?:price|cost_price|can_view_price|can_view_cost)`?\s*(?:=|!=|is null|is not null)|"
    r"response contains field `(?:price|cost_price|can_view_price|can_view_cost)`",
    re.IGNORECASE,
)


def _visibility_claim_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    case_text = " ".join(
        str(part or "").strip()
        for part in (case.id, case.title, case.objective, " ".join(case.tags))
        if str(part or "").strip()
    )
    if not case_text or _VISIBILITY_CLAIM_PATTERN.search(case_text) is None:
        return []
    checks = [] if case.oracle is None else [str(item) for item in case.oracle.business_checks]
    has_visibility_assertion = any(_VISIBILITY_ASSERTION_PATTERN.search(check) for check in checks)
    if not has_visibility_assertion and not (case.oracle is not None and case.oracle.persisted_state is not None):
        strict = _visibility_assertions_required(authoring_plan, case)
        diagnostics.append(
            authoring_diagnostic(
                (
                    "authoring_visibility_claim_missing_required_assertion"
                    if strict
                    else "authoring_visibility_claim_without_field_assertion"
                ),
                (
                    "Case objective/tags claim price/cost visibility, masking, or leak prevention, but the oracle "
                    "does not assert the relevant price/cost field behavior."
                ),
                severity=DiagnosticSeverity.ERROR if strict else DiagnosticSeverity.WARNING,
                source_ref=case_ref,
                details={
                    "case_index": index,
                    "business_checks": checks,
                    "suggestion": (
                        "Add a supported field assertion such as response `cost_price` = `null`, use a DB/content "
                        "verification that proves the claim, or narrow the objective to a binary/download smoke check."
                    ),
                },
            )
        )
    diagnostics.extend(
        _collection_visibility_data_setup_diagnostics(
            authoring_plan=authoring_plan,
            case=case,
            case_ref=case_ref,
            index=index,
            checks=checks,
            has_visibility_assertion=has_visibility_assertion,
        )
    )
    return diagnostics


def _visibility_assertions_required(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    plan_coverage_contract = plan_contract_section(authoring_plan, "coverage")
    if plan_coverage_contract.get("visibility_claims_require_field_assertions") is not None:
        return policy_bool(plan_coverage_contract.get("visibility_claims_require_field_assertions"))
    coverage_contract = case_contract_section(case, "coverage")
    return policy_bool(coverage_contract.get("visibility_claims_require_field_assertions"))


def _collection_visibility_data_setup_diagnostics(
    *,
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    index: int,
    checks: list[str],
    has_visibility_assertion: bool,
) -> list[GenerationDiagnostic]:
    if not has_visibility_assertion:
        return []
    route_path = "" if case.execute is None or case.execute.route is None else case.execute.route.path
    if not _is_search_or_collection_route(route_path, case):
        return []
    if case.setup:
        return []
    if _has_collection_data_contract(case):
        return []

    strict = _collection_visibility_data_setup_required(authoring_plan, case)
    return [
        authoring_diagnostic(
            (
                "authoring_collection_visibility_data_setup_required"
                if strict
                else "authoring_collection_visibility_data_setup_unresolved"
            ),
            (
                "Search or collection visibility case asserts price/cost masking but does not define setup or "
                "metadata proving a non-empty result set. The case can pass HTTP 200 with an empty collection and "
                "never exercise the masking assertion."
            ),
            severity=DiagnosticSeverity.ERROR if strict else DiagnosticSeverity.WARNING,
            source_ref=case_ref,
            details={
                "case_index": index,
                "route_path": route_path,
                "business_checks": checks,
                "suggestion": (
                    "Create or discover matching data in setup, use a stable non_empty_fixture contract, or make "
                    "the oracle explicitly handle empty search results as fixture BLOCKED rather than product FAIL."
                ),
            },
        )
    ]


def _collection_visibility_data_setup_required(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    plan_coverage_contract = plan_contract_section(authoring_plan, "coverage")
    if plan_coverage_contract.get("collection_visibility_requires_data_setup") is not None:
        return policy_bool(plan_coverage_contract.get("collection_visibility_requires_data_setup"))
    coverage_contract = case_contract_section(case, "coverage")
    return policy_bool(coverage_contract.get("collection_visibility_requires_data_setup"))


def _is_search_or_collection_route(route_path: str, case: AuthoringCase) -> bool:
    text = " ".join(
        [
            route_path,
            case.id,
            case.title,
            case.objective,
            " ".join(case.tags),
        ]
    ).lower()
    return any(token in text for token in ("/search", " search ", " search-", "results", "collection"))


def _has_collection_data_contract(case: AuthoringCase) -> bool:
    metadata_text = _flatten_metadata_text(case.metadata).lower()
    open_question_text = " ".join(case.open_questions).lower()
    combined = f"{metadata_text} {open_question_text}"
    if any(token in combined for token in ("non_empty_fixture", "non-empty fixture", "nonempty fixture")):
        return True
    if any(token in combined for token in ("seeded search", "seeded result", "stable fixture", "fixture_result")):
        return True
    return False


def _flatten_metadata_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten_metadata_text(nested)}" for key, nested in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_metadata_text(item) for item in value)
    return str(value)
