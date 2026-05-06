"""Visibility-claim diagnostics for compact authoring cases."""

from __future__ import annotations

import re
from typing import Any

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic

from .policy import case_contract_section, plan_contract_section, policy_bool
from ..diagnostics import authoring_diagnostic
from ..models import AuthoringCase, AuthoringPlan

_VISIBILITY_CLAIM_PATTERN = re.compile(
    r"\b(?:mask|masks|masked|masking|leak|leaks|visibility|visible|can_view_price|can_view_cost|price|cost_price|selling price)\b",
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
    diagnostics.extend(
        _root_visibility_field_assertion_diagnostics(
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
    if _setup_proves_collection_data(authoring_plan, case):
        return []
    if _has_collection_data_contract(case):
        return []
    if _oracle_proves_non_empty_collection(checks):
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


def _root_visibility_field_assertion_diagnostics(
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
    root_assertions = [check for check in checks if _asserts_root_price_or_cost_field(check)]
    if not root_assertions:
        return []
    if _has_root_visibility_path_evidence(case):
        return []

    strict = _root_visibility_path_evidence_required(authoring_plan, case)
    return [
        authoring_diagnostic(
            (
                "authoring_visibility_root_field_assertion_requires_path_evidence"
                if strict
                else "authoring_visibility_root_field_assertion_without_path_evidence"
            ),
            (
                "Visibility case asserts root-level price/cost_price. Nested price-list responses often expose "
                "these fields under positions, categories, templates, or items, so root-level assertions need "
                "explicit response-shape evidence."
            ),
            severity=DiagnosticSeverity.ERROR if strict else DiagnosticSeverity.WARNING,
            source_ref=case_ref,
            details={
                "case_index": index,
                "root_assertions": root_assertions,
                "suggestion": (
                    "Use an exact nested response path such as response `categories.0.positions.0.cost_price` = "
                    "`null`, or add metadata.root_visibility_fields_confirmed with source evidence proving the "
                    "field really exists at response root."
                ),
            },
        )
    ]


def _asserts_root_price_or_cost_field(check: str) -> bool:
    normalized = str(check or "").strip()
    root_patterns = (
        r"^response\s+`?(?:price|cost_price)`?\s*(?:=|!=|is null|is not null)(?:\s|$)",
        r"^response\s+contains\s+field\s+`(?:price|cost_price)`\s*$",
    )
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in root_patterns)


def _root_visibility_path_evidence_required(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    plan_coverage_contract = plan_contract_section(authoring_plan, "coverage")
    if plan_coverage_contract.get("root_visibility_assertions_require_path_evidence") is not None:
        return policy_bool(plan_coverage_contract.get("root_visibility_assertions_require_path_evidence"))
    coverage_contract = case_contract_section(case, "coverage")
    return policy_bool(coverage_contract.get("root_visibility_assertions_require_path_evidence"))


def _has_root_visibility_path_evidence(case: AuthoringCase) -> bool:
    metadata_text = _flatten_metadata_text(case.metadata).lower()
    return any(
        token in metadata_text
        for token in (
            "root_visibility_fields_confirmed",
            "response_shape_evidence",
            "exact_response_path_evidence",
            "root price field",
            "root cost_price field",
        )
    )


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


def _oracle_proves_non_empty_collection(checks: list[str]) -> bool:
    combined = " ".join(checks).lower()
    non_empty_patterns = (
        r"\bat least one\b",
        r"\bone or more\b",
        r"\bnon[-_ ]?empty\b",
        r"\bnot empty\b",
        r"\blength\s*>\s*0\b",
        r"\blength\s*>=\s*[1-9]\d*\b",
        r"\bcount\s*>\s*0\b",
        r"\bcount\s*>=\s*[1-9]\d*\b",
        r"\bsize\s*>\s*0\b",
        r"\bsize\s*>=\s*[1-9]\d*\b",
        r"\bitems?\s*>\s*0\b",
        r"\bitems?\s*>=\s*[1-9]\d*\b",
        r"\bresults?\s*>\s*0\b",
        r"\bresults?\s*>=\s*[1-9]\d*\b",
    )
    if any(re.search(pattern, combined) for pattern in non_empty_patterns):
        return True
    indexed_result_patterns = (
        r"response\s+contains\s+field\s+`[^`]*(?:\.0|\[0\])",
        r"response\s+`[^`]*(?:\.0|\[0\])[^`]*`\s+exists",
        r"response\s+`[^`]*(?:\.0|\[0\])[^`]*`\s+is\s+not\s+null",
    )
    return any(re.search(pattern, combined) for pattern in indexed_result_patterns)


def _setup_proves_collection_data(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    for setup_step in case.setup:
        entity = authoring_plan.entities.get(setup_step.use_entity.strip())
        if entity is None:
            continue
        operation = entity.operations.get(setup_step.operation.strip())
        if operation is None:
            continue
        if _operation_proves_collection_data(setup_step.use_entity, setup_step.operation, operation.to_dict()):
            return True
    return False


def _operation_proves_collection_data(entity_name: str, operation_name: str, payload: dict[str, Any]) -> bool:
    route_payload = payload.get("route")
    route_text = _flatten_metadata_text(route_payload) if isinstance(route_payload, dict) else ""
    text = " ".join(
        [
            entity_name,
            operation_name,
            route_text,
            _flatten_metadata_text(payload.get("request_body")),
            _flatten_metadata_text(payload.get("captures") or payload.get("capture")),
            _flatten_metadata_text(payload.get("expected_outcomes")),
        ]
    ).lower()
    if any(token in text for token in ("non_empty_fixture", "non-empty fixture", "nonempty fixture")):
        return True
    if any(token in text for token in ("seeded search", "seeded result", "fixture_result")):
        return True
    blocked_setup_tokens = (
        "permission",
        "auth",
        "credential",
        "token",
        "login",
        "session",
        "role",
        "access",
        "grant",
        "revoke",
        "member",
    )
    if any(token in text for token in blocked_setup_tokens):
        return False
    data_verbs = ("create", "seed", "ensure", "discover", "find", "prepare", "provision", "index")
    if not any(token in text for token in data_verbs):
        return False
    captures = payload.get("captures")
    if not isinstance(captures, list):
        captures = payload.get("capture")
    capture_text = " ".join(str(item) for item in captures or [])
    if re.search(r"->\s*[A-Za-z_][A-Za-z0-9_]*(?:_id|_guid)\b", capture_text):
        return True
    expected_outcomes = " ".join(str(item) for item in payload.get("expected_outcomes") or []).lower()
    return "one row exists" in expected_outcomes or "response contains field `id`" in expected_outcomes


def _flatten_metadata_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten_metadata_text(nested)}" for key, nested in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_metadata_text(item) for item in value)
    return str(value)
