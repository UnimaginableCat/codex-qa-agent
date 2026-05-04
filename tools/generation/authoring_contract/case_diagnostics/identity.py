"""Identity-resolution diagnostics for compact authoring plans."""

from __future__ import annotations

import re
from typing import Any

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic
from tools.scenario_runner.domain.models import ScenarioVariableDefinition, ScenarioVariableSource
from tools.scenario_runner.parsing.variables.validation import build_variable_definition

from .policy import contract_mode, plan_contract_section, policy_bool
from ..diagnostics import authoring_diagnostic
from ..helpers import _VARIABLE_NAME_PATTERN
from ..models import AuthoringPlan

_DEFAULT_ENV_IDENTITY_PATTERNS = (
    r"(?:^|_)(?:company_)?member_guid$",
    r"(?:^|_)user_guid$",
)


def _env_backed_identity_guid_diagnostics(
    authoring_plan: AuthoringPlan,
    source_ref: str,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    policy = _identity_resolution_policy(authoring_plan)
    diagnostics.extend(_identity_resolution_policy_diagnostics(policy, source_ref))
    seen: set[tuple[str, str | None, str]] = set()
    for field_path, entries in _scenario_variable_entries_with_paths(authoring_plan):
        for entry_index, entry in enumerate(entries):
            variable_name, definition = _scenario_variable_definition_from_entry(entry)
            if variable_name is None or definition is None or definition.source != ScenarioVariableSource.ENV:
                continue
            env_name = definition.env_name
            identity_match = _env_identity_match(variable_name, env_name, policy)
            if identity_match is None:
                continue
            key = (variable_name, env_name, field_path)
            if key in seen:
                continue
            seen.add(key)
            disallowed = policy["env_backed_role_identity"] == "disallow"
            diagnostics.append(
                authoring_diagnostic(
                    (
                        "authoring_env_backed_role_identity_disallowed"
                        if disallowed
                        else "authoring_env_backed_role_identity_guid"
                    ),
                    (
                        "Role/user identity GUIDs should usually be discovered by setup API/DB steps and captured "
                        "into variables instead of required as manual env inputs."
                    ),
                    severity=DiagnosticSeverity.ERROR if disallowed else DiagnosticSeverity.WARNING,
                    source_ref=source_ref,
                    details={
                        "field": f"{field_path}[{entry_index}]",
                        "variable": variable_name,
                        "env_name": env_name,
                        "policy_source": identity_match,
                        "suggestion": (
                            "Keep actor login/password in env, then capture company_member_guid/user_guid from a "
                            "permissions API response or read-only DB lookup in workflow setup."
                        ),
                    },
                )
            )
    return diagnostics


def _identity_resolution_policy_diagnostics(
    policy: dict[str, Any],
    source_ref: str,
) -> list[GenerationDiagnostic]:
    if not policy["allow_env_identity_variables"] or policy["justification"]:
        return []
    return [
        authoring_diagnostic(
            "authoring_identity_resolution_allow_without_justification",
            (
                "metadata.identity_resolution.allow_env_identity_variables relaxes identity discovery policy, "
                "but no justification explains why env-backed role/user GUIDs are unavoidable."
            ),
            severity=DiagnosticSeverity.WARNING,
            source_ref=source_ref,
            details={
                "allow_env_identity_variables": sorted(policy["allow_env_identity_variables"]),
                "suggestion": (
                    "Prefer setup discovery through API/DB. If env identity fixtures are truly required, add "
                    "metadata.identity_resolution.justification with the concrete reason and fixture ownership."
                ),
            },
        )
    ]


def _scenario_variable_entries_with_paths(authoring_plan: AuthoringPlan) -> list[tuple[str, list[str]]]:
    entries: list[tuple[str, list[str]]] = [("defaults.scenario_variables", list(authoring_plan.defaults.scenario_variables))]
    for case_index, case in enumerate(authoring_plan.cases, start=1):
        if case.scenario_variables:
            entries.append((f"cases[{case_index}].scenario_variables", list(case.scenario_variables)))
    return entries


def _scenario_variable_definition_from_entry(
    entry: str,
) -> tuple[str | None, ScenarioVariableDefinition | None]:
    if "=" not in entry:
        return None, None
    variable_name, raw_value = entry.split("=", 1)
    variable_name = variable_name.strip()
    if not variable_name or not _VARIABLE_NAME_PATTERN.fullmatch(variable_name):
        return None, None
    try:
        return variable_name, build_variable_definition(variable_name, raw_value.strip())
    except Exception:
        return variable_name, None


def _identity_resolution_policy(authoring_plan: AuthoringPlan) -> dict[str, Any]:
    raw_policy = authoring_plan.metadata.get("identity_resolution")
    policy = dict(raw_policy) if isinstance(raw_policy, dict) else {}
    identity_contract = plan_contract_section(authoring_plan, "identity")
    return {
        "discourage_env_identity": _string_set(policy.get("discourage_env_identity")),
        "allow_env_identity_variables": _string_set(policy.get("allow_env_identity_variables")),
        "stable_env_fixtures": _string_set(policy.get("stable_env_fixtures")),
        "env_identity_name_patterns": _string_list(policy.get("env_identity_name_patterns")),
        "disable_default_env_identity_patterns": policy_bool(policy.get("disable_default_env_identity_patterns")),
        "justification": str(policy.get("justification") or "").strip(),
        "env_backed_role_identity": contract_mode(
            identity_contract.get("env_backed_role_identity"),
            default="warn",
        ),
    }


def _env_identity_match(
    variable_name: str,
    env_name: str | None,
    policy: dict[str, Any],
) -> str | None:
    values = [variable_name, env_name or ""]
    if _any_policy_name_match(values, policy["allow_env_identity_variables"]) or _any_policy_name_match(
        values,
        policy["stable_env_fixtures"],
    ):
        return None
    if _any_policy_name_match(values, policy["discourage_env_identity"]):
        return "metadata.identity_resolution.discourage_env_identity"

    for pattern in policy["env_identity_name_patterns"]:
        if _any_regex_match(values, pattern):
            return "metadata.identity_resolution.env_identity_name_patterns"

    if not policy["disable_default_env_identity_patterns"]:
        for pattern in _DEFAULT_ENV_IDENTITY_PATTERNS:
            if _any_regex_match(values, pattern):
                return "default_env_identity_name_patterns"
    return None


def _any_policy_name_match(values: list[str], names: set[str]) -> bool:
    normalized_values = {_normalize_policy_name(value) for value in values if value and value.strip()}
    return any(_normalize_policy_name(name) in normalized_values for name in names)


def _any_regex_match(values: list[str], pattern: str) -> bool:
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return False
    return any(compiled.search(value.strip()) for value in values if value and value.strip())


def _normalize_policy_name(value: str) -> str:
    return value.strip().lower()


def _string_set(value: Any) -> set[str]:
    return set(_string_list(value))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if str(item).strip()]
    return []
