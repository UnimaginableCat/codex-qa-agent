"""Behavior-evidence diagnostics for risky authored oracles."""

from __future__ import annotations

import re
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic

from ..diagnostics import authoring_diagnostic
from ..models import AuthoringCase, AuthoringEntityOperation, AuthoringPlan


def _behavior_evidence_diagnostics(
    *,
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
) -> list[GenerationDiagnostic]:
    risky_claims = _risky_behavior_claims(case)
    if not risky_claims and not _behavior_evidence_required_by_contract(authoring_plan, case):
        return []

    execute_operation = _matching_execute_operation(authoring_plan, case)
    evidence_items = _behavior_evidence_items(authoring_plan, case, execute_operation)
    if not evidence_items:
        return [
            authoring_diagnostic(
                "authoring_behavior_evidence_required",
                (
                    "Case oracle asserts route-specific business behavior, but no structured behavior_evidence "
                    "proves the expectation for the executed flow. Add implementation or test evidence tied to "
                    "the same route/state_change before promotion."
                ),
                source_ref=case_ref,
                details={
                    "risky_claims": risky_claims,
                    "state_change": str(case.state_change or ""),
                    "route": _case_route_details(case),
                },
            )
        ]

    valid_items = [
        item
        for item in evidence_items
        if _behavior_evidence_is_usable(item, case=case, implicit_operation=execute_operation)
    ]
    if valid_items:
        return []

    return [
        authoring_diagnostic(
            "authoring_behavior_evidence_mismatch",
            (
                "Case has behavior_evidence, but it does not match the executed route/state_change or appears "
                "to prove a different flow. Do not use update-service/test evidence as the oracle for a create "
                "flow, or vice versa."
            ),
            source_ref=case_ref,
            details={
                "risky_claims": risky_claims,
                "state_change": str(case.state_change or ""),
                "route": _case_route_details(case),
                "evidence": [_summarize_evidence_item(item) for item in evidence_items],
            },
        )
    ]


_RISKY_BEHAVIOR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bomitt(?:ed|ing|s)?\b", re.IGNORECASE),
    re.compile(r"\bdefaults?\b", re.IGNORECASE),
    re.compile(r"\bdoes\s+not\s+apply\b", re.IGNORECASE),
    re.compile(r"\bnot\s+appl(?:y|ied|ies)\b", re.IGNORECASE),
    re.compile(r"\bpreserv(?:e|es|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bremap(?:s|ped|ping)?\b", re.IGNORECASE),
    re.compile(r"\bclear(?:s|ed|ing)?\b.*\bdefaults?\b", re.IGNORECASE),
)


def _risky_behavior_claims(case: AuthoringCase) -> list[str]:
    texts: list[tuple[str, str]] = [
        ("case_id", case.id),
        ("title", case.title),
        ("objective", case.objective),
    ]
    if case.oracle is not None:
        texts.extend(("business_check", item) for item in case.oracle.business_checks)
        if case.oracle.persisted_state is not None:
            texts.append(("persisted_state", case.oracle.persisted_state.operation))
    texts.extend(_metadata_text_items(case.metadata))

    claims: list[str] = []
    for source, text in texts:
        normalized = str(text or "").strip()
        if not normalized:
            continue
        if any(pattern.search(normalized) for pattern in _RISKY_BEHAVIOR_PATTERNS):
            claims.append(f"{source}: {normalized}")
    return claims


def _metadata_text_items(value: Any, *, prefix: str = "metadata") -> list[tuple[str, str]]:
    if value is None:
        return []
    if isinstance(value, str):
        return [(prefix, value)]
    if isinstance(value, dict):
        items: list[tuple[str, str]] = []
        for key, nested in value.items():
            normalized_key = str(key)
            if normalized_key in {
                "default_actor",
                "default_environment",
                "default_auth",
                "non_blocking_notes",
                "request_body_evidence",
                "response_body_evidence",
            }:
                continue
            items.extend(_metadata_text_items(nested, prefix=f"{prefix}.{normalized_key}"))
        return items
    if isinstance(value, (list, tuple, set)):
        items: list[tuple[str, str]] = []
        for index, nested in enumerate(value):
            items.extend(_metadata_text_items(nested, prefix=f"{prefix}[{index}]"))
        return items
    return []


def _behavior_evidence_required_by_contract(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    return _metadata_contract_bool(authoring_plan.metadata, "behavior", "evidence_required") or _metadata_contract_bool(
        case.metadata,
        "behavior",
        "evidence_required",
    )


def _metadata_contract_bool(metadata: dict[str, Any], section: str, key: str) -> bool:
    contracts = metadata.get("contracts")
    if not isinstance(contracts, dict):
        return False
    contract_section = contracts.get(section)
    if not isinstance(contract_section, dict):
        return False
    return str(contract_section.get(key) or "").strip().lower() in {"1", "true", "yes", "required"}


def _behavior_evidence_items(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    execute_operation: AuthoringEntityOperation | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for source_name, value in (
        ("case.metadata.behavior_evidence", case.metadata.get("behavior_evidence")),
        ("case.metadata.expected_behavior_evidence", case.metadata.get("expected_behavior_evidence")),
        ("case.oracle.behavior_evidence", None if case.oracle is None else case.oracle.behavior_evidence),
        ("execute_operation.behavior_evidence", None if execute_operation is None else execute_operation.behavior_evidence),
        (
            "persisted_operation.behavior_evidence",
            _persisted_operation_behavior_evidence(authoring_plan, case),
        ),
    ):
        items.extend(_normalize_evidence_items(value, source_name=source_name))
    return items


def _persisted_operation_behavior_evidence(authoring_plan: AuthoringPlan, case: AuthoringCase) -> Any:
    if case.oracle is None or case.oracle.persisted_state is None:
        return None
    state_ref = case.oracle.persisted_state
    entity_spec = authoring_plan.entities.get(state_ref.entity.strip())
    if entity_spec is None:
        return None
    operation = entity_spec.operations.get(state_ref.operation.strip())
    if operation is None:
        return None
    return operation.behavior_evidence


def _normalize_evidence_items(value: Any, *, source_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[dict[str, Any]] = []
        for item in value:
            items.extend(_normalize_evidence_items(item, source_name=source_name))
        return items
    if isinstance(value, dict):
        normalized = dict(value)
        normalized["_evidence_source"] = source_name
        return [normalized]
    text = str(value or "").strip()
    if not text:
        return []
    return [{"evidence": text, "_evidence_source": source_name}]


def _behavior_evidence_is_usable(
    item: dict[str, Any],
    *,
    case: AuthoringCase,
    implicit_operation: AuthoringEntityOperation | None,
) -> bool:
    if not _has_source_and_evidence_text(item):
        return False
    if not _evidence_route_matches_case(item, case=case, implicit_operation=implicit_operation):
        return False
    if _evidence_conflicts_with_state_change(item, state_change=str(case.state_change or "")):
        return False
    return True


def _has_source_and_evidence_text(item: dict[str, Any]) -> bool:
    source_ref = str(item.get("source_ref") or item.get("source") or "").strip()
    evidence_text = _evidence_text(item)
    return bool(source_ref and evidence_text)


def _evidence_text(item: dict[str, Any]) -> str:
    values = [
        item.get("evidence"),
        item.get("behavior"),
        item.get("behavior_source"),
        item.get("implementation"),
        item.get("test_evidence"),
        item.get("notes"),
    ]
    return " ".join(str(value or "").strip() for value in values if str(value or "").strip())


def _evidence_route_matches_case(
    item: dict[str, Any],
    *,
    case: AuthoringCase,
    implicit_operation: AuthoringEntityOperation | None,
) -> bool:
    case_method = "" if case.execute is None or case.execute.route is None else case.execute.route.method.strip().upper()
    case_path = "" if case.execute is None or case.execute.route is None else case.execute.route.path.strip()
    route = item.get("route")
    if isinstance(route, dict):
        evidence_method = str(route.get("method") or "").strip().upper()
        evidence_path = str(route.get("path") or "").strip()
        if evidence_method and case_method and evidence_method != case_method:
            return False
        if evidence_path and case_path and evidence_path != case_path:
            return False
    elif item.get("_evidence_source") == "execute_operation.behavior_evidence":
        if implicit_operation is None or implicit_operation.route is None:
            return False
        if case_method and implicit_operation.route.method.strip().upper() != case_method:
            return False
        if case_path and implicit_operation.route.path.strip() != case_path:
            return False
    return True


_STATE_ACTION_ALIASES = {
    "create": {"create", "created", "creation", "creating"},
    "update": {"update", "updated", "updating", "replace", "replaced"},
    "mutate": {"mutate", "mutation", "duplicate", "duplicated", "copy", "copied"},
    "delete": {"delete", "deleted", "deletion", "remove", "removed"},
}


def _evidence_conflicts_with_state_change(item: dict[str, Any], *, state_change: str) -> bool:
    normalized_state = str(state_change or "").strip().lower()
    if normalized_state not in _STATE_ACTION_ALIASES:
        return False
    declared_state = str(
        item.get("state_change")
        or item.get("flow")
        or item.get("operation")
        or item.get("applies_to")
        or "",
    ).strip().lower()
    evidence_text = " ".join(
        (
            declared_state,
            str(item.get("source_ref") or item.get("source") or ""),
            _evidence_text(item),
        )
    ).lower()
    matching_tokens = _STATE_ACTION_ALIASES[normalized_state]
    conflicting_tokens = set().union(
        *(
            tokens
            for state, tokens in _STATE_ACTION_ALIASES.items()
            if state != normalized_state
        )
    )
    has_match = any(re.search(rf"\b{re.escape(token)}\b", evidence_text) for token in matching_tokens)
    has_conflict = any(re.search(rf"\b{re.escape(token)}\b", evidence_text) for token in conflicting_tokens)
    return has_conflict and not has_match


def _matching_execute_operation(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
) -> AuthoringEntityOperation | None:
    if case.execute is None or case.execute.route is None:
        return None
    method = case.execute.route.method.strip().upper()
    path = case.execute.route.path.strip()
    for entity_spec in authoring_plan.entities.values():
        for operation in entity_spec.operations.values():
            if operation.route is None:
                continue
            if operation.route.method.strip().upper() == method and operation.route.path.strip() == path:
                return operation
    return None


def _case_route_details(case: AuthoringCase) -> dict[str, str]:
    if case.execute is None or case.execute.route is None:
        return {}
    return {
        "method": case.execute.route.method,
        "path": case.execute.route.path,
    }


def _summarize_evidence_item(item: dict[str, Any]) -> dict[str, str]:
    route = item.get("route") if isinstance(item.get("route"), dict) else {}
    return {
        "source": str(item.get("_evidence_source") or ""),
        "source_ref": str(item.get("source_ref") or item.get("source") or ""),
        "route_method": str(route.get("method") or ""),
        "route_path": str(route.get("path") or ""),
        "state_change": str(item.get("state_change") or item.get("flow") or item.get("operation") or ""),
        "evidence": _evidence_text(item),
    }
