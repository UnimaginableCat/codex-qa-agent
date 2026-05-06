"""Permission-state contract diagnostics for compact authoring cases."""

from __future__ import annotations

from typing import Any

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic

from .policy import case_contract_section, plan_contract_section, policy_bool
from ..diagnostics import authoring_diagnostic
from ..models import AuthoringCase, AuthoringEntityOperation, AuthoringPlan


def _permission_state_contract_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    """Verify explicit required permission states are established by setup operations."""

    required_states = _normalized_permission_states(case.required_permission_state)
    prerequisite_diagnostics = _permission_prerequisite_metadata_diagnostics(
        case,
        case_ref,
        index=index,
        has_required_states=bool(required_states),
    )
    prerequisite_diagnostics.extend(
        _negative_permission_case_state_setup_diagnostics(
            authoring_plan,
            case,
            case_ref,
            index=index,
            has_required_states=bool(required_states),
        )
    )
    if not required_states:
        return prerequisite_diagnostics

    diagnostics: list[GenerationDiagnostic] = prerequisite_diagnostics
    setup_effects = _setup_permission_state_effects(authoring_plan, case)
    setup_keys = {effect["key"] for effect in setup_effects}

    if case.kind.strip().lower() != "workflow":
        diagnostics.append(
            authoring_diagnostic(
                "authoring_permission_state_setup_required",
                "Case declares required_permission_state, so it must be authored as a workflow with setup steps.",
                source_ref=case_ref,
                details={
                    "case_index": index,
                    "required_permission_state": required_states,
                    "kind": case.kind,
                },
            )
        )

    for required_state in required_states:
        matching_effect = _find_matching_permission_effect(required_state, setup_effects)
        if matching_effect is not None:
            continue
        diagnostics.append(
            authoring_diagnostic(
                "authoring_permission_state_setup_required",
                (
                    "Case declares required_permission_state, but setup does not include a matching "
                    "permission_state_effect. Establish the permission/right/access state before executing "
                    "the gated action."
                ),
                source_ref=case_ref,
                details={
                    "case_index": index,
                    "required_permission_state": required_state,
                    "setup_permission_state_keys": sorted(setup_keys),
                    "suggestion": (
                        "Add a setup entity operation with permission_state_effects containing the same key "
                        "and final state, usually after resetting or updating the relevant permission."
                    ),
                },
            )
        )
    return diagnostics


def _normalized_permission_states(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    states: list[dict[str, str]] = []
    for item in items:
        key = _permission_key(item)
        if not key:
            continue
        normalized = {
            "key": key,
            "state": str(item.get("state") or item.get("value") or "").strip().lower(),
            "subject": str(item.get("subject") or "").strip(),
            "resource": str(item.get("resource") or "").strip(),
        }
        states.append({field: value for field, value in normalized.items() if value})
    return states


def _setup_permission_state_effects(authoring_plan: AuthoringPlan, case: AuthoringCase) -> list[dict[str, str]]:
    effects: list[dict[str, str]] = []
    for setup_step in case.setup:
        entity = authoring_plan.entities.get(setup_step.use_entity.strip())
        if entity is None:
            continue
        operation = entity.operations.get(setup_step.operation.strip())
        if operation is None:
            continue
        effects.extend(_operation_permission_effects(operation))
    return effects


def _operation_permission_effects(operation: AuthoringEntityOperation) -> list[dict[str, str]]:
    effects: list[dict[str, str]] = []
    for item in operation.permission_state_effects:
        key = _permission_key(item)
        if not key:
            continue
        effect = {
            "key": key,
            "state": str(item.get("state") or item.get("value") or "").strip().lower(),
            "subject": str(item.get("subject") or "").strip(),
            "resource": str(item.get("resource") or "").strip(),
            "mode": str(item.get("mode") or item.get("action") or "").strip().lower(),
        }
        effects.append({field: value for field, value in effect.items() if value})
    return effects


def _find_matching_permission_effect(
    required_state: dict[str, str],
    effects: list[dict[str, str]],
) -> dict[str, str] | None:
    for effect in effects:
        if effect.get("key") != required_state.get("key"):
            continue
        if not _field_matches(required_state, effect, "subject"):
            continue
        if not _field_matches(required_state, effect, "resource"):
            continue
        required_value = required_state.get("state")
        effect_value = effect.get("state")
        if required_value and effect_value and required_value != effect_value:
            continue
        if required_value and not effect_value:
            continue
        return effect
    return None


def _field_matches(required_state: dict[str, str], effect: dict[str, str], field: str) -> bool:
    required_value = required_state.get(field)
    effect_value = effect.get(field)
    return not required_value or required_value == effect_value


def _permission_key(item: dict[str, Any]) -> str:
    return str(item.get("key") or item.get("permission") or item.get("name") or "").strip()


def _permission_prerequisite_metadata_diagnostics(
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
    has_required_states: bool,
) -> list[GenerationDiagnostic]:
    prerequisite_keys = [
        key
        for key in case.metadata
        if str(key).strip().lower()
        in {
            "prerequisite_permission",
            "prerequisite_permissions",
            "permission_prerequisite",
            "permission_precondition",
            "required_permission",
            "required_permissions",
        }
    ]
    if not prerequisite_keys or has_required_states:
        return []
    return [
        authoring_diagnostic(
            "authoring_permission_prerequisite_requires_required_state",
            (
                "Case metadata declares a permission prerequisite, but required_permission_state is empty. "
                "Represent permission-gated preconditions as typed required_permission_state plus setup "
                "permission_state_effects, or mark the case deferred/open instead of relying on prose metadata."
            ),
            source_ref=case_ref,
            details={
                "case_index": index,
                "metadata_keys": sorted(prerequisite_keys),
            },
        )
    ]


def _negative_permission_case_state_setup_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
    has_required_states: bool,
) -> list[GenerationDiagnostic]:
    if not _looks_like_permission_negative_or_default_case(case):
        return []
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
    if _has_permission_baseline_contract(case) or _has_permission_baseline_setup(authoring_plan, case):
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
    metadata_text = " ".join(
        f"{key} {value}" for key, value in case.metadata.items()
    ).lower()
    return any(
        token in metadata_text
        for token in (
            "stable_permission_fixture",
            "permission_fixture_contract",
            "known_no_override_fixture",
            "fixture_has_can_edit_false",
            "fixture_has_can_create_false",
        )
    )


def _has_permission_baseline_contract(case: AuthoringCase) -> bool:
    metadata_text = " ".join(
        f"{key} {value}" for key, value in case.metadata.items()
    ).lower()
    return any(
        token in metadata_text
        for token in (
            "baseline_checked",
            "permission_baseline_checked",
            "effective_permissions_checked",
            "current_permissions_checked",
            "preflight_permission_check",
        )
    )


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


def _looks_like_permission_negative_or_default_case(case: AuthoringCase) -> bool:
    checks = [] if case.oracle is None else [str(item) for item in case.oracle.business_checks]
    text = " ".join(
        [
            case.id,
            case.title,
            case.objective,
            " ".join(case.tags),
            " ".join(checks),
        ]
    ).lower()
    if not any(token in text for token in ("partner", "member", "customer", "contractor", "actor")):
        return False
    if any(token in text for token in ("without", "default", "denied", "cannot", "lacks", "no override")):
        return True
    if case.oracle is not None and case.oracle.status_code == 403:
        return True
    return any(
        token in text
        for token in (
            "can_edit` = `false",
            "can_create` = `false",
            "can_manage_permissions` = `false",
        )
    )
