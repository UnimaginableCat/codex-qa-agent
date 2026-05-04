"""Visibility-claim diagnostics for compact authoring cases."""

from __future__ import annotations

import re

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
    case_text = " ".join(
        str(part or "").strip()
        for part in (case.id, case.title, case.objective, " ".join(case.tags))
        if str(part or "").strip()
    )
    if not case_text or _VISIBILITY_CLAIM_PATTERN.search(case_text) is None:
        return []
    checks = [] if case.oracle is None else [str(item) for item in case.oracle.business_checks]
    if any(_VISIBILITY_ASSERTION_PATTERN.search(check) for check in checks):
        return []
    if case.oracle is not None and case.oracle.persisted_state is not None:
        return []
    strict = _visibility_assertions_required(authoring_plan, case)
    return [
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
    ]


def _visibility_assertions_required(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    plan_coverage_contract = plan_contract_section(authoring_plan, "coverage")
    if plan_coverage_contract.get("visibility_claims_require_field_assertions") is not None:
        return policy_bool(plan_coverage_contract.get("visibility_claims_require_field_assertions"))
    coverage_contract = case_contract_section(case, "coverage")
    return policy_bool(coverage_contract.get("visibility_claims_require_field_assertions"))
