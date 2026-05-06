"""Permission-state contract diagnostics for compact authoring cases."""

from __future__ import annotations

import re
from typing import Any

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic

from .policy import case_contract_section, plan_contract_section, policy_bool
from ..diagnostics import authoring_diagnostic
from ..helpers import _declared_variable_names
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
    prerequisite_diagnostics.extend(
        _actor_bound_permission_setup_diagnostics(
            authoring_plan,
            case,
            case_ref,
            index=index,
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
            "state": _permission_state_value(item),
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
            "state": _permission_state_value(item),
            "actor": str(item.get("actor") or "").strip(),
            "subject": str(
                item.get("subject")
                or item.get("subject_variable")
                or item.get("principal")
                or item.get("principal_variable")
                or item.get("captured_variable")
                or ""
            ).strip(),
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


def _permission_state_value(item: dict[str, Any]) -> str:
    for key in ("state", "value"):
        if key in item and item.get(key) is not None:
            return str(item.get(key)).strip().lower()
    return ""


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
    if not _looks_like_permission_negative_or_default_case(authoring_plan, case):
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


def _actor_bound_permission_setup_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    execute_actor = _effective_execute_actor(authoring_plan, case).lower()
    if not execute_actor:
        return []
    if _has_actor_identity_binding_contract(authoring_plan, case, execute_actor):
        return []

    for setup_step in case.setup:
        entity = authoring_plan.entities.get(setup_step.use_entity.strip())
        if entity is None:
            continue
        operation = entity.operations.get(setup_step.operation.strip())
        if operation is None:
            continue
        needs_binding, identity_fields = _operation_requires_actor_identity_binding(
            operation,
            execute_actor,
            declared_variable_names=_declared_variable_names(authoring_plan, case),
        )
        if not needs_binding:
            continue
        return [
            authoring_diagnostic(
                "authoring_permission_actor_identity_binding_required",
                (
                    "Workflow grants or revokes a permission for a discovered principal identity and then "
                    f"executes as actor `{execute_actor}`, but it does not prove that the discovered identity "
                    "belongs to that actor profile. Capturing the first principal from a list can grant a "
                    "different account and make the gated action fail for the actor under test."
                ),
                source_ref=case_ref,
                details={
                    "case_index": index,
                    "actor": execute_actor,
                    "identity_fields": identity_fields,
                    "setup_entity": setup_step.use_entity,
                    "setup_operation": setup_step.operation,
                    "suggestion": (
                        "Bind the identity explicitly, for example capture the current actor principal id/guid, "
                        "use an env-backed actor-owned identity with identity_resolution justification, or add "
                        "metadata.identity_binding proving the setup subject matches the execute actor."
                    ),
                },
            )
        ]
    return []


def _effective_execute_actor(authoring_plan: AuthoringPlan, case: AuthoringCase) -> str:
    if case.execute is not None and case.execute.actor:
        return case.execute.actor
    default_actor = case.metadata.get("default_actor")
    if default_actor is not None:
        return str(default_actor)
    return authoring_plan.defaults.actor


def _has_actor_identity_binding_contract(authoring_plan: AuthoringPlan, case: AuthoringCase, actor: str) -> bool:
    if _has_structured_identity_binding_contract(case.metadata, actor):
        return True
    metadata_text = _flatten_metadata_text(case.metadata).lower()
    actor = actor.lower()
    if _identity_binding_text_is_strong(metadata_text, actor):
        return True
    if _has_structured_identity_binding_contract(authoring_plan.metadata, actor):
        return True
    plan_metadata_text = _flatten_metadata_text(authoring_plan.metadata).lower()
    return _identity_binding_text_is_strong(plan_metadata_text, actor)


def _has_structured_identity_binding_contract(metadata: dict[str, Any], actor: str) -> bool:
    for key in (
        "actor_identity_binding",
        "identity_binding",
        "subject_identity_binding",
        "principal_identity_binding",
        "actor_principal_binding",
    ):
        value = metadata.get(key)
        if _identity_binding_value_is_strong(value, actor):
            return True
    identity_resolution = metadata.get("identity_resolution")
    if isinstance(identity_resolution, dict):
        for key in ("actor_binding", "subject_binding", "principal_binding", "actor_identity_binding"):
            value = identity_resolution.get(key)
            if _identity_binding_value_is_strong(value, actor):
                return True
    return False


def _identity_binding_value_is_strong(value: Any, actor: str) -> bool:
    if value in (None, False, "", [], {}):
        return False
    if isinstance(value, dict):
        text = _flatten_metadata_text(value).lower()
        has_actor = _metadata_value_mentions_actor(value, actor)
        has_subject = any(
            key in value
            for key in (
                "subject",
                "subject_variable",
                "principal",
                "principal_variable",
                "captured_variable",
                "member_guid",
                "user_guid",
                "company_member_guid",
            )
        ) or _mentions_principal_identity(text)
        has_evidence = any(
            key in value
            for key in (
                "evidence",
                "source",
                "source_ref",
                "verified_by",
                "setup",
                "capture_source",
                "env_var",
            )
        )
        evidence_is_strong = _identity_binding_text_is_strong(text, actor)
        if has_evidence and not evidence_is_strong:
            return False
        return has_actor and has_subject and has_evidence
    if isinstance(value, (list, tuple, set)):
        return any(_identity_binding_value_is_strong(item, actor) for item in value)
    return _identity_binding_text_is_strong(str(value).lower(), actor)


def _metadata_value_mentions_actor(value: dict[str, Any], actor: str) -> bool:
    actor = actor.strip().lower()
    if not actor:
        return False
    for key in ("actor", "role", "persona", "actor_profile", "execute_actor"):
        candidate = value.get(key)
        if candidate is not None and str(candidate).strip().lower() == actor:
            return True
    return actor in _flatten_metadata_text(value).lower()


def _identity_binding_text_is_strong(text: str, actor: str) -> bool:
    normalized = str(text or "").lower()
    actor = actor.lower()
    if not normalized or not actor:
        return False
    weak_list_capture = any(
        token in normalized
        for token in (
            "first ",
            ".0.",
            "[0]",
            "partner_permissions",
            "management list",
            "first returned",
            "first row",
        )
    )
    strong_current_actor_source = any(
        token in normalized
        for token in (
            "current_actor",
            "current actor",
            "execute_actor",
            "execute actor",
            "actor_under_test",
            "current_user.company_member_guid",
            "current_user.guid",
            "current_user.id",
        )
    )
    actor_owned_env_context = "env" in normalized
    actor_owned_env = bool(
        re.search(rf"\benv:{re.escape(actor)}_[a-z0-9_]*(?:member|user|principal|actor)_(?:id|guid|uuid)\b", normalized)
        or re.search(rf"\b[a-z0-9_]+__{re.escape(actor)}\b", normalized)
        or (
            actor_owned_env_context
            and re.search(
                rf"\b{re.escape(actor)}_[a-z0-9_]*(?:member|user|principal|actor)_(?:id|guid|uuid)\b",
                normalized,
            )
        )
    )
    explicit_binding_token = any(
        token in normalized
        for token in (
            "actor_identity_binding",
            "subject_identity_binding",
            "principal_identity_binding",
            "actor_principal_binding",
            "actor-scoped env",
            "actor scoped env",
        )
    )
    if weak_list_capture and not (strong_current_actor_source or actor_owned_env):
        return False
    return (strong_current_actor_source or actor_owned_env or explicit_binding_token) and _mentions_principal_identity(
        normalized
    )


def _mentions_principal_identity(text: str) -> bool:
    return bool(re.search(_PRINCIPAL_IDENTITY_FIELD_PATTERN, text, flags=re.IGNORECASE))


def _operation_requires_actor_identity_binding(
    operation: AuthoringEntityOperation,
    actor: str,
    *,
    declared_variable_names: set[str],
) -> tuple[bool, list[str]]:
    actor = actor.lower()
    identity_fields = _discovered_identity_fields(operation.to_dict())
    if not identity_fields:
        return False, []
    for effect in _operation_permission_effects(operation):
        effect_actor = effect.get("actor", "").lower()
        subject = effect.get("subject", "").lower()
        if _permission_effect_targets_execute_actor(effect_actor, subject, actor):
            return True, identity_fields
    return False, []


def _permission_effect_targets_execute_actor(effect_actor: str, subject: str, actor: str) -> bool:
    normalized_actor = effect_actor.strip().lower()
    if normalized_actor and normalized_actor in {actor, "execute_actor", "current_actor", "actor_under_test"}:
        return True
    return _permission_subject_targets_execute_actor(subject, actor)


def _permission_subject_targets_execute_actor(subject: str, actor: str) -> bool:
    normalized_subject = subject.strip().lower()
    if not normalized_subject:
        return False
    if normalized_subject == actor:
        return True
    if normalized_subject in {"execute_actor", "current_actor", "current_user", "actor_under_test"}:
        return True
    if _is_principal_identity_field(normalized_subject):
        return True
    if _permission_subject_is_identity_placeholder(normalized_subject):
        return True
    return normalized_subject in {f"{{{{{actor}}}}}", f"${{{actor}}}", f"env:{actor.upper()}"}


def _permission_subject_is_identity_placeholder(subject: str) -> bool:
    placeholder_match = re.fullmatch(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", subject)
    if placeholder_match is None:
        placeholder_match = re.fullmatch(r"\$\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}", subject)
    if placeholder_match is None:
        return False
    return _is_principal_identity_field(placeholder_match.group(1))


def _discovered_identity_fields(value: Any) -> list[str]:
    fields: set[str] = set()
    _collect_discovered_identity_fields(value, fields)
    return sorted(fields)


def _collect_discovered_identity_fields(value: Any, fields: set[str]) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        for nested in value.values():
            _collect_discovered_identity_fields(nested, fields)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_discovered_identity_fields(item, fields)
        return

    text = str(value)
    if "env:" in text.lower():
        return
    for match in re.finditer(
        _PRINCIPAL_IDENTITY_FIELD_PATTERN,
        text,
        re.IGNORECASE,
    ):
        fields.add(match.group(0))


_PRINCIPAL_IDENTITY_FIELD_PATTERN = (
    r"\b(?:(?:[a-z0-9]+)_)?(?:company_)?"
    r"(?:member|user|actor|principal|subject|account|employee|contact)_(?:id|guid|uuid)\b"
)


def _is_principal_identity_field(value: str) -> bool:
    return bool(re.fullmatch(_PRINCIPAL_IDENTITY_FIELD_PATTERN, value, flags=re.IGNORECASE))


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
        value_text = _flatten_metadata_text(case.metadata.get(key)).lower()
        if _baseline_contract_text_is_strong(value_text, case_ids={item.id for item in authoring_plan.cases}):
            return True
    return False


def _baseline_contract_text_is_strong(text: str, *, case_ids: set[str]) -> bool:
    normalized = str(text or "").lower()
    if not normalized:
        return False
    if re.search(r"\b(?:covered by|see|from|covered in|checked in|verified in)\s+(?:case|scenario)\b", normalized):
        return False
    if any(case_id and case_id.lower() != normalized and case_id.lower() in normalized for case_id in case_ids):
        return False
    return any(
        token in normalized
        for token in (
            "setup verifies",
            "setup checks",
            "preflight setup",
            "this case verifies",
            "this case checks",
            "current effective permissions",
            "effective permissions checked",
            "override row checked",
            "baseline read step",
            "baseline setup",
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


def _looks_like_permission_negative_or_default_case(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    checks = [] if case.oracle is None else [str(item) for item in case.oracle.business_checks]
    structured_claim = _permission_coverage_claim(case)
    text = _permission_case_text(case, checks)
    if _looks_like_payload_validation_case(case, text):
        return False
    actor_text = _case_actor_text(authoring_plan, case).lower()
    claim_text = _flatten_metadata_text(structured_claim).lower() if structured_claim is not None else ""
    has_actor_context = bool(actor_text.strip())
    has_permission_context = _mentions_permission_context(text) or _mentions_permission_context(claim_text)
    has_denial_or_default_text = _mentions_denial_or_default(text) or _mentions_denial_or_default(claim_text)
    has_false_permission_assertion = _mentions_false_permission_assertion(text) or _mentions_false_permission_assertion(
        claim_text
    )

    if structured_claim is not None and (has_denial_or_default_text or has_false_permission_assertion):
        return True
    if case.oracle is not None and case.oracle.status_code == 403 and (has_actor_context or has_permission_context):
        return True
    if has_actor_context and has_denial_or_default_text:
        return True
    return has_actor_context and has_false_permission_assertion


def _looks_like_payload_validation_case(case: AuthoringCase, text: str) -> bool:
    if case.oracle is None or case.oracle.status_code != 400:
        return False
    return any(
        token in text
        for token in (
            "duplicate",
            "validation",
            "payload",
            "serializer",
            "bad request",
            "invalid request",
            "malformed",
            "schema",
        )
    )


def _permission_case_text(case: AuthoringCase, checks: list[str]) -> str:
    route_text = ""
    execute_text = ""
    if case.execute is not None:
        route_text = "" if case.execute.route is None else f"{case.execute.route.method} {case.execute.route.path}"
        execute_text = _flatten_metadata_text(
            {
                "headers": case.execute.headers,
                "params": case.execute.params,
                "body": case.execute.body,
                "auth_strategy": case.execute.auth_strategy,
            }
        )
    return " ".join(
        [
            case.id,
            case.title,
            case.objective,
            " ".join(case.tags),
            " ".join(checks),
            route_text,
            execute_text,
        ]
    ).lower()


def _case_actor_text(authoring_plan: AuthoringPlan, case: AuthoringCase) -> str:
    actor_parts: list[str] = []
    if authoring_plan.defaults.actor:
        actor_parts.append(authoring_plan.defaults.actor)
    default_actor = case.metadata.get("default_actor")
    if default_actor is not None:
        actor_parts.append(str(default_actor))
    for key in ("actor", "role", "persona"):
        value = case.metadata.get(key)
        if value is not None:
            actor_parts.append(str(value))
    if case.execute is not None and case.execute.actor:
        actor_parts.append(case.execute.actor)
    actor_parts.extend(step.actor for step in case.setup if step.actor)
    return " ".join(actor_parts)


def _permission_coverage_claim(case: AuthoringCase) -> dict[str, Any] | None:
    coverage_claims = case.metadata.get("coverage_claims")
    if not isinstance(coverage_claims, dict):
        return None
    permission_claim = coverage_claims.get("permissions") or coverage_claims.get("permission")
    if not isinstance(permission_claim, dict) or not permission_claim:
        return None
    return dict(permission_claim)


def _mentions_denial_or_default(text: str) -> bool:
    return any(
        token in text
        for token in (
            "without",
            "default",
            "denied",
            "deny",
            "cannot",
            "forbidden",
            "lacks",
            "no override",
            "negative",
            "not allowed",
            "disallow",
            "rejected",
            "blocked",
            "absent",
        )
    )


def _mentions_false_permission_assertion(text: str) -> bool:
    return any(
        token in text
        for token in (
            "can_edit` = `false",
            "can_create` = `false",
            "can_manage_permissions` = `false",
            "can_edit: false",
            "can_create: false",
            "can_manage_permissions: false",
            "can_edit false",
            "can_create false",
            "can_manage_permissions false",
            "edit_denied",
            "create_denied",
            "manage_denied",
        )
    )


def _mentions_permission_context(text: str) -> bool:
    return any(
        token in text
        for token in (
            "permission",
            "permissions",
            "can_edit",
            "can_create",
            "can_manage",
            "override",
            "access",
        )
    )


def _flatten_metadata_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten_metadata_text(nested)}" for key, nested in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_metadata_text(item) for item in value)
    return str(value)
