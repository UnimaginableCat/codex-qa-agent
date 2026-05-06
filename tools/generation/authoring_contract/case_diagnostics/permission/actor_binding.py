"""Actor/principal binding diagnostics for permission setup workflows."""

from __future__ import annotations

import re
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic

from .effects import _operation_permission_effects
from ...diagnostics import authoring_diagnostic
from ...models import AuthoringCase, AuthoringEntityOperation, AuthoringPlan


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

    for setup_step in case.setup:
        entity = authoring_plan.entities.get(setup_step.use_entity.strip())
        if entity is None:
            continue
        operation = entity.operations.get(setup_step.operation.strip())
        if operation is None:
            continue
        needs_binding, identity_fields, subject_fields = _operation_requires_actor_identity_binding(operation, execute_actor)
        if not needs_binding:
            continue
        if _has_actor_identity_binding_contract(authoring_plan, case, execute_actor, subject_fields):
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
                    "subject_fields": subject_fields,
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


def _operation_requires_actor_identity_binding(
    operation: AuthoringEntityOperation,
    actor: str,
) -> tuple[bool, list[str], list[str]]:
    actor = actor.lower()
    identity_fields = _discovered_identity_fields(operation.to_dict())
    if not identity_fields:
        return False, [], []
    for effect in _operation_permission_effects(operation):
        effect_actor = effect.get("actor", "").lower()
        subject = effect.get("subject", "").lower()
        if _permission_effect_targets_execute_actor(effect_actor, subject, actor):
            subject_fields = _effect_subject_identity_fields(effect, identity_fields)
            return True, identity_fields, subject_fields
    return False, [], []


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


def _has_actor_identity_binding_contract(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    actor: str,
    subject_fields: list[str],
) -> bool:
    normalized_subjects = _normalize_identity_field_set(subject_fields)
    if _has_structured_identity_binding_contract(case.metadata, actor, normalized_subjects):
        return True
    metadata_text = _flatten_metadata_text(case.metadata).lower()
    actor = actor.lower()
    if _identity_binding_text_is_strong(metadata_text, actor) and _identity_binding_text_matches_subject(
        metadata_text,
        normalized_subjects,
    ):
        return True
    if _has_structured_identity_binding_contract(authoring_plan.metadata, actor, normalized_subjects):
        return True
    plan_metadata_text = _flatten_metadata_text(authoring_plan.metadata).lower()
    return _identity_binding_text_is_strong(plan_metadata_text, actor) and _identity_binding_text_matches_subject(
        plan_metadata_text,
        normalized_subjects,
    )


def _has_structured_identity_binding_contract(
    metadata: dict[str, Any],
    actor: str,
    subject_fields: set[str],
) -> bool:
    for key in (
        "actor_identity_binding",
        "identity_binding",
        "subject_identity_binding",
        "principal_identity_binding",
        "actor_principal_binding",
    ):
        value = metadata.get(key)
        if _identity_binding_value_is_strong(value, actor, subject_fields):
            return True
    identity_resolution = metadata.get("identity_resolution")
    if isinstance(identity_resolution, dict):
        for key in ("actor_binding", "subject_binding", "principal_binding", "actor_identity_binding"):
            value = identity_resolution.get(key)
            if _identity_binding_value_is_strong(value, actor, subject_fields):
                return True
    return False


def _identity_binding_value_is_strong(value: Any, actor: str, subject_fields: set[str]) -> bool:
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
        subject_matches = _identity_binding_value_matches_subject(value, text, subject_fields)
        return has_actor and has_subject and has_evidence and subject_matches
    if isinstance(value, (list, tuple, set)):
        return any(_identity_binding_value_is_strong(item, actor, subject_fields) for item in value)
    text = str(value).lower()
    return _identity_binding_text_is_strong(text, actor) and _identity_binding_text_matches_subject(text, subject_fields)


def _identity_binding_value_matches_subject(value: dict[str, Any], text: str, subject_fields: set[str]) -> bool:
    if not subject_fields:
        return True
    binding_subjects: set[str] = set()
    for key in (
        "subject",
        "subject_variable",
        "principal",
        "principal_variable",
        "captured_variable",
        "member_guid",
        "user_guid",
        "company_member_guid",
        "env_var",
    ):
        if key in value:
            binding_subjects.update(_identity_fields_from_text(str(value.get(key) or "")))
    return bool(binding_subjects & subject_fields) or _identity_binding_text_matches_subject(text, subject_fields)


def _identity_binding_text_matches_subject(text: str, subject_fields: set[str]) -> bool:
    if not subject_fields:
        return True
    mentioned_subjects = _normalize_identity_field_set(_identity_fields_from_text(text))
    return bool(mentioned_subjects & subject_fields)


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


def _effect_subject_identity_fields(effect: dict[str, str], fallback_identity_fields: list[str]) -> list[str]:
    subject = effect.get("subject", "")
    subject_fields = _identity_fields_from_text(subject)
    if subject_fields:
        return sorted(_normalize_identity_field_set(subject_fields))
    return sorted(_normalize_identity_field_set(fallback_identity_fields))


def _permission_subject_is_identity_placeholder(subject: str) -> bool:
    placeholder_match = re.fullmatch(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", subject)
    if placeholder_match is None:
        placeholder_match = re.fullmatch(r"\$\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}", subject)
    if placeholder_match is None:
        return False
    return _is_principal_identity_field(placeholder_match.group(1))


def _identity_fields_from_text(text: str) -> list[str]:
    value = str(text or "")
    fields = [match.group(0) for match in re.finditer(_PRINCIPAL_IDENTITY_FIELD_PATTERN, value, re.IGNORECASE)]
    placeholder_match = re.fullmatch(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", value.strip())
    if placeholder_match is not None and _is_principal_identity_field(placeholder_match.group(1)):
        fields.append(placeholder_match.group(1))
    return sorted(_normalize_identity_field_set(fields))


def _normalize_identity_field_set(fields: list[str] | set[str]) -> set[str]:
    return {_normalize_identity_field(field) for field in fields if _normalize_identity_field(field)}


def _normalize_identity_field(field: str) -> str:
    normalized = str(field or "").strip().lower()
    if normalized.startswith("env:"):
        normalized = normalized[4:]
    normalized = normalized.strip("{}$ ")
    return normalized


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


def _mentions_principal_identity(text: str) -> bool:
    return bool(re.search(_PRINCIPAL_IDENTITY_FIELD_PATTERN, text, flags=re.IGNORECASE))


_PRINCIPAL_IDENTITY_FIELD_PATTERN = (
    r"\b(?:(?:[a-z0-9]+)_)?(?:company_)?"
    r"(?:member|user|actor|principal|subject|account|employee|contact)_(?:id|guid|uuid)\b"
)


def _is_principal_identity_field(value: str) -> bool:
    return bool(re.fullmatch(_PRINCIPAL_IDENTITY_FIELD_PATTERN, value, flags=re.IGNORECASE))


def _flatten_metadata_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten_metadata_text(nested)}" for key, nested in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_metadata_text(item) for item in value)
    return str(value)
