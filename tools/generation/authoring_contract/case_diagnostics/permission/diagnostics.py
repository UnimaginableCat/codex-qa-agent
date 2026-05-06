"""Permission diagnostics orchestration for compact authoring cases."""

from __future__ import annotations

from tools.generation.domain.models import GenerationDiagnostic

from .actor_binding import _actor_bound_permission_setup_diagnostics
from .negative_cases import _negative_permission_case_state_setup_diagnostics
from .state_contract import (
    _normalized_permission_states,
    _permission_prerequisite_metadata_diagnostics,
    _permission_required_state_setup_diagnostics,
)
from ...models import AuthoringCase, AuthoringPlan


def _permission_state_contract_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    """Verify permission preconditions, setup effects, and actor identity bindings."""

    required_states = _normalized_permission_states(case.required_permission_state)
    diagnostics: list[GenerationDiagnostic] = []
    diagnostics.extend(
        _permission_prerequisite_metadata_diagnostics(
            case,
            case_ref,
            index=index,
            has_required_states=bool(required_states),
        )
    )
    diagnostics.extend(
        _negative_permission_case_state_setup_diagnostics(
            authoring_plan,
            case,
            case_ref,
            index=index,
            has_required_states=bool(required_states),
        )
    )
    diagnostics.extend(
        _actor_bound_permission_setup_diagnostics(
            authoring_plan,
            case,
            case_ref,
            index=index,
        )
    )
    diagnostics.extend(
        _permission_required_state_setup_diagnostics(
            authoring_plan,
            case,
            case_ref,
            index=index,
            required_states=required_states,
        )
    )
    return diagnostics
