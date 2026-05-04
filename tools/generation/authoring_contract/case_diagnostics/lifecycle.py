"""Lifecycle and same-state diagnostics for compact authoring workflows."""

from __future__ import annotations

from typing import Any

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic

from .policy import case_contract_section, heuristic_or_strict_severity
from ..diagnostics import authoring_diagnostic
from ..models import AuthoringCase, AuthoringSetupStep, _maybe_int

_SUPPORTED_SAME_STATE_BEHAVIORS = {"reject", "idempotent_success"}


def _workflow_setup_state_mismatch_diagnostics(
    *,
    case: AuthoringCase,
    case_ref: str,
) -> list[GenerationDiagnostic]:
    if case.kind.strip().lower() != "workflow" or not case.setup or case.execute is None or case.execute.route is None:
        return []
    actual_state = _infer_setup_state(case.setup)
    if actual_state is None:
        return []
    expected_state = _expected_precondition_state(case)
    if expected_state is None or expected_state == actual_state:
        return []
    return [
        authoring_diagnostic(
            "authoring_workflow_setup_state_mismatch",
            (
                "Workflow setup appears to leave the entity in a different lifecycle state than the case objective "
                "or execute route expects. This often produces the wrong HTTP status at execution time."
            ),
            severity=DiagnosticSeverity.WARNING,
            source_ref=case_ref,
            details={
                "expected_state": expected_state,
                "actual_state": actual_state,
                "setup_operations": [step.operation for step in case.setup],
                "route_path": case.execute.route.path,
            },
        )
    ]


def _workflow_same_state_contract_warning(
    *,
    case: AuthoringCase,
    case_ref: str,
) -> list[GenerationDiagnostic]:
    if case.kind.strip().lower() != "workflow" or not case.setup or case.execute is None or case.execute.route is None:
        return []
    actual_state = _infer_setup_state(case.setup)
    target_state = _inferred_route_target_state(case.execute.route.path)
    if actual_state is None or target_state is None or actual_state != target_state:
        return []
    return [
        authoring_diagnostic(
            "authoring_same_state_lifecycle_contract_unconfirmed",
            (
                "Workflow case appears to invoke a lifecycle command when the entity is already in the target state. "
                "Do not assume rejection or idempotent success from route names alone; confirm same-state behavior in "
                "code/tests and record it explicitly in operation-inventory.yaml."
            ),
            severity=DiagnosticSeverity.WARNING,
            source_ref=case_ref,
            details={
                "actual_state": actual_state,
                "target_state": target_state,
                "route_path": case.execute.route.path,
                "setup_operations": [step.operation for step in case.setup],
            },
        )
    ]


def _infer_setup_state(setup_steps: list[AuthoringSetupStep]) -> str | None:
    state: str | None = None
    for step in setup_steps:
        hinted_state = _operation_state_hint(step.operation)
        if hinted_state is not None:
            state = hinted_state
    return state


def _operation_state_hint(operation_name: str) -> str | None:
    normalized = operation_name.strip().lower()
    if not normalized:
        return None
    if "archive" in normalized:
        return "archived"
    if "suspend" in normalized:
        return "suspended"
    if "activate" in normalized:
        return "active"
    if "create" in normalized:
        return "active"
    return None


def _expected_precondition_state(case: AuthoringCase) -> str | None:
    route_path = "" if case.execute is None or case.execute.route is None else case.execute.route.path.strip().lower()
    expected_status = case.oracle.status_code if case.oracle is not None else None
    if route_path.endswith("/activate") and isinstance(expected_status, int) and 200 <= expected_status < 300:
        return "suspended"
    if route_path.endswith("/suspend") and isinstance(expected_status, int) and 200 <= expected_status < 300:
        return "active"
    case_text = " ".join(part.strip().lower() for part in (case.title, case.objective) if part and part.strip())
    if "archived user" in case_text or "for archived user" in case_text:
        return "archived"
    if "suspended user" in case_text or "already suspended" in case_text:
        return "suspended"
    if "active user" in case_text or "already active" in case_text:
        return "active"
    return None


def _inferred_route_target_state(route_path: str) -> str | None:
    normalized_path = route_path.strip().lower()
    if normalized_path.endswith("/activate"):
        return "active"
    if normalized_path.endswith("/suspend"):
        return "suspended"
    if normalized_path.endswith("/archive"):
        return "archived"
    return None


def _same_state_inventory_contract_diagnostics(
    *,
    case: AuthoringCase,
    case_ref: str,
    route_spec: dict[str, Any],
    route_key: tuple[str, str],
    actual_state: str | None,
) -> list[GenerationDiagnostic]:
    if actual_state is None or case.oracle is None or not isinstance(case.oracle.status_code, int):
        return []

    explicit_target_state = _normalized_inventory_state(route_spec.get("target_state"))
    inferred_target_state = _inferred_route_target_state(route_key[1])
    target_state = explicit_target_state or inferred_target_state
    if target_state is None or actual_state != target_state:
        return []

    details = {
        "route_path": route_key[1],
        "actual_state": actual_state,
        "target_state": target_state,
        "setup_operations": [step.operation for step in case.setup],
    }
    missing_fields: list[str] = []
    if explicit_target_state is None:
        missing_fields.append("target_state")

    same_state_behavior = _normalized_inventory_same_state_behavior(route_spec.get("same_state_behavior"))
    same_state_status = _maybe_int(route_spec.get("same_state_status"))
    if same_state_behavior is None:
        missing_fields.append("same_state_behavior")
    if same_state_status is None:
        missing_fields.append("same_state_status")
    if missing_fields:
        strict = _same_state_inventory_contract_required(case, route_spec)
        return [
            authoring_diagnostic(
                (
                    "authoring_stage_inventory_same_state_behavior_required"
                    if strict
                    else "authoring_stage_inventory_same_state_behavior_unconfirmed"
                ),
                (
                    "Same-state lifecycle case is authored, but operation-inventory.yaml does not fully document the "
                    "route contract for reissuing the command on an entity already in the target state."
                ),
                severity=heuristic_or_strict_severity(strict),
                source_ref=case_ref,
                details={**details, "missing_fields": missing_fields},
            )
        ]

    if case.oracle.status_code != same_state_status:
        return [
            authoring_diagnostic(
                "authoring_stage_inventory_same_state_mismatch",
                (
                    "Authoring case HTTP status for a same-state lifecycle command does not match the explicit "
                    "same-state contract recorded in operation-inventory.yaml."
                ),
                source_ref=case_ref,
                details={
                    **details,
                    "same_state_behavior": same_state_behavior,
                    "authored_status": case.oracle.status_code,
                    "inventory_same_state_status": same_state_status,
                },
            )
        ]
    if same_state_behavior == "idempotent_success" and case.oracle.persisted_state is None:
        return [
            authoring_diagnostic(
                "authoring_stage_inventory_idempotency_persistence_missing",
                (
                    "Same-state lifecycle case is documented as idempotent_success, but the authoring case does not "
                    "verify persisted state after reissuing the command."
                ),
                source_ref=case_ref,
                details={
                    **details,
                    "same_state_behavior": same_state_behavior,
                    "same_state_status": same_state_status,
                },
            )
        ]
    return []


def _same_state_inventory_contract_required(case: AuthoringCase, route_spec: dict[str, Any]) -> bool:
    if route_spec.get("same_state_contract_required") is not None:
        return bool(route_spec.get("same_state_contract_required"))
    lifecycle_contract = case_contract_section(case, "lifecycle")
    return bool(lifecycle_contract.get("same_state_requires_inventory_contract"))


def _is_same_state_inventory_case(
    *,
    route_spec: dict[str, Any],
    route_key: tuple[str, str],
    actual_state: str | None,
) -> bool:
    if actual_state is None:
        return False
    target_state = _normalized_inventory_state(route_spec.get("target_state")) or _inferred_route_target_state(route_key[1])
    return target_state is not None and actual_state == target_state


def _normalized_inventory_same_state_behavior(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in _SUPPORTED_SAME_STATE_BEHAVIORS:
        return normalized
    return None


def _normalized_inventory_state(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None
