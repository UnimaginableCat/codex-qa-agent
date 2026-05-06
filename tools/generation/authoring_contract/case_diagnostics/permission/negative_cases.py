"""Permission denial/default-case diagnostics."""

from __future__ import annotations

from typing import Any

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic

from .state_contract import _setup_permission_state_effects
from ..policy import case_contract_section, plan_contract_section, policy_bool
from ...diagnostics import authoring_diagnostic
from ...models import AuthoringCase, AuthoringPlan


def _negative_permission_case_state_setup_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
    has_required_states: bool,
) -> list[GenerationDiagnostic]:
    if has_required_states:
        return []
    if _has_permission_fixture_contract(case):
        return _negative_permission_fixture_baseline_diagnostics(
            authoring_plan,
            case,
            case_ref,
            index=index,
        )
    if _has_permission_baseline_setup(authoring_plan, case):
        return []
    if not _has_structured_negative_permission_claim(case):
        return []

    strict = _negative_permission_state_setup_required(authoring_plan, case)
    return [
        authoring_diagnostic(
            (
                "authoring_permission_negative_case_state_setup_required"
                if strict
                else "authoring_permission_negative_case_state_setup_unresolved"
            ),
            (
                "Permission negative/default case assumes an actor lacks can_edit/can_create or receives a denial, "
                "but it does not establish that permission state through setup or a typed required_permission_state. "
                "Stable QA fixtures can drift and turn the expected denial into a granted action."
            ),
            severity=DiagnosticSeverity.ERROR if strict else DiagnosticSeverity.WARNING,
            source_ref=case_ref,
            details={
                "case_index": index,
                "suggestion": (
                    "Use a self-contained workflow that revokes/resets the relevant permission before the negative "
                    "action, or document a stable fixture contract in metadata and keep required_permission_state "
                    "aligned with setup permission_state_effects."
                ),
            },
        )
    ]


def _negative_permission_fixture_baseline_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    if _has_permission_baseline_contract(authoring_plan, case) or _has_permission_baseline_setup(authoring_plan, case):
        return []
    strict = _negative_permission_baseline_required(authoring_plan, case)
    return [
        authoring_diagnostic(
            (
                "authoring_permission_negative_case_baseline_check_required"
                if strict
                else "authoring_permission_negative_case_baseline_check_unresolved"
            ),
            (
                "Permission negative/default case documents a stable permission fixture, but does not verify the "
                "current effective permission baseline before executing the denial/default assertion. Previous "
                "runs may have already granted can_edit or can_create on the shared fixture."
            ),
            severity=DiagnosticSeverity.ERROR if strict else DiagnosticSeverity.WARNING,
            source_ref=case_ref,
            details={
                "case_index": index,
                "suggestion": (
                    "Add a setup step that reads effective permissions or the override row and asserts the expected "
                    "false/absent state, or reset/revoke the permission in setup before the negative action."
                ),
            },
        )
    ]


def _negative_permission_state_setup_required(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    plan_contract = plan_contract_section(authoring_plan, "permissions")
    if plan_contract.get("negative_cases_require_state_setup") is not None:
        return policy_bool(plan_contract.get("negative_cases_require_state_setup"))
    case_contract = case_contract_section(case, "permissions")
    return policy_bool(case_contract.get("negative_cases_require_state_setup"))


def _negative_permission_baseline_required(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    plan_contract = plan_contract_section(authoring_plan, "permissions")
    if plan_contract.get("negative_cases_require_baseline_check") is not None:
        return policy_bool(plan_contract.get("negative_cases_require_baseline_check"))
    case_contract = case_contract_section(case, "permissions")
    return policy_bool(case_contract.get("negative_cases_require_baseline_check"))


def _has_permission_fixture_contract(case: AuthoringCase) -> bool:
    return any(
        bool(case.metadata.get(key))
        for key in (
            "stable_permission_fixture",
            "permission_fixture_contract",
            "known_no_override_fixture",
            "fixture_has_can_edit_false",
            "fixture_has_can_create_false",
        )
    )


def _has_permission_baseline_contract(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    for key in (
        "baseline_checked",
        "permission_baseline_checked",
        "effective_permissions_checked",
        "current_permissions_checked",
        "preflight_permission_check",
    ):
        if key not in case.metadata:
            continue
        if _baseline_contract_is_structured(case.metadata.get(key), case_ids={item.id for item in authoring_plan.cases}):
            return True
    return False


def _baseline_contract_is_structured(value: Any, *, case_ids: set[str]) -> bool:
    if value in (None, False, "", [], {}):
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_baseline_contract_is_structured(item, case_ids=case_ids) for item in value)
    if not isinstance(value, dict):
        return False

    reference_text = _flatten_metadata_text(
        {
            key: nested
            for key, nested in value.items()
            if key in {"case", "case_id", "scenario", "scenario_id", "covered_by", "verified_in", "checked_in"}
        }
    ).lower()
    if any(case_id and case_id.lower() in reference_text for case_id in case_ids):
        return False

    verified = any(
        policy_bool(value.get(key))
        for key in ("verified", "checked", "baseline_checked", "effective_permissions_checked")
    )
    evidence = any(
        bool(value.get(key))
        for key in (
            "setup_operation",
            "setup_step",
            "source_ref",
            "assertion",
            "assertions",
            "query",
            "route",
            "operation",
        )
    )
    expected_state = _flatten_metadata_text(
        value.get("expected_state")
        or value.get("expected_states")
        or value.get("expected_permission_state")
        or value.get("expected_permissions")
    ).lower()
    checks_false_or_absent = any(token in expected_state for token in ("false", "absent", "none", "denied"))
    return verified and evidence and checks_false_or_absent


def _has_permission_baseline_setup(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    for effect in _setup_permission_state_effects(authoring_plan, case):
        mode = effect.get("mode", "")
        state = effect.get("state", "")
        if mode in {"verify", "baseline", "assert", "read", "check"} and state in {"false", "absent", "none"}:
            return True
    for setup_step in case.setup:
        operation_name = setup_step.operation.strip().lower()
        if any(token in operation_name for token in ("verify", "baseline", "check", "read", "get")) and any(
            token in operation_name for token in ("permission", "can_edit", "can_create", "override")
        ):
            return True
    return False


def _has_structured_negative_permission_claim(case: AuthoringCase) -> bool:
    return any(_claim_is_negative_or_default(claim) for claim in _permission_coverage_claims(case))


def _claim_is_negative_or_default(claim: dict[str, Any]) -> bool:
    if any(
        policy_bool(claim.get(key))
        for key in ("requires_state_setup", "requires_baseline", "requires_permission_state_setup")
    ):
        return True

    expected_result = _flatten_metadata_text(claim.get("expected_result") or claim.get("result")).lower()
    expected_state = _flatten_metadata_text(
        claim.get("expected_state") or claim.get("state") or claim.get("expected_permission_state")
    ).lower()
    return any(
        token in expected_result
        for token in ("403", "denied", "deny", "forbidden", "blocked", "rejected", "hidden", "not_allowed")
    ) or any(token in expected_state for token in ("false", "absent", "none", "default_denied", "denied"))


def _permission_coverage_claims(case: AuthoringCase) -> list[dict[str, Any]]:
    coverage_claims = case.metadata.get("coverage_claims")
    if not isinstance(coverage_claims, dict):
        return []
    permission_claim = coverage_claims.get("permissions") or coverage_claims.get("permission")
    if isinstance(permission_claim, dict) and permission_claim:
        return [dict(permission_claim)]
    if isinstance(permission_claim, list):
        return [dict(item) for item in permission_claim if isinstance(item, dict) and item]
    return []


def _flatten_metadata_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten_metadata_text(nested)}" for key, nested in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_metadata_text(item) for item in value)
    return str(value)
