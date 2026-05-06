"""Typed required-permission-state diagnostics."""

from __future__ import annotations

from typing import Any

from tools.generation.domain.models import GenerationDiagnostic

from .effects import _operation_permission_effects, _permission_key, _permission_state_value
from ...diagnostics import authoring_diagnostic
from ...models import AuthoringCase, AuthoringPlan


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


def _permission_required_state_setup_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
    required_states: list[dict[str, str]],
) -> list[GenerationDiagnostic]:
    if not required_states:
        return []

    diagnostics: list[GenerationDiagnostic] = []
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
