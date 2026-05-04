"""Shared policy helpers for authoring case diagnostics."""

from __future__ import annotations

from typing import Any

from tools.generation.domain.models import DiagnosticSeverity

from ..models import AuthoringCase, AuthoringPlan


def contract_mode(value: Any, *, default: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"disallow", "deny", "error", "block", "blocked", "strict"}:
        return "disallow"
    if normalized in {"allow", "ignore", "off", "false"}:
        return "allow"
    return default


def heuristic_or_strict_severity(strict: bool) -> DiagnosticSeverity:
    return DiagnosticSeverity.ERROR if strict else DiagnosticSeverity.WARNING


def policy_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, int | float):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on", "enable", "enabled", "strict", "require", "required"}:
        return True
    if normalized in {"", "0", "false", "no", "n", "off", "disable", "disabled", "allow", "ignore"}:
        return False
    return default


def plan_contract_section(authoring_plan: AuthoringPlan, section: str) -> dict[str, Any]:
    contracts = authoring_plan.metadata.get("contracts")
    if not isinstance(contracts, dict):
        return {}
    section_value = contracts.get(section)
    return dict(section_value) if isinstance(section_value, dict) else {}


def case_contract_section(case: AuthoringCase, section: str) -> dict[str, Any]:
    contracts = case.metadata.get("contracts")
    if not isinstance(contracts, dict):
        return {}
    section_value = contracts.get(section)
    return dict(section_value) if isinstance(section_value, dict) else {}
