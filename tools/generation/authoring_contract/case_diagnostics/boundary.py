"""Boundary-prose diagnostics for compact authoring cases."""

from __future__ import annotations

import re
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic

from .policy import case_contract_section, heuristic_or_strict_severity, plan_contract_section
from ..diagnostics import authoring_diagnostic
from ..helpers import _extract_placeholders, _normalize_case_field_name, _numeric_path_parts
from ..models import AuthoringCase, AuthoringPlan

_STRING_LENGTH_OVERFLOW_PATTERN = re.compile(
    r"\b(?:longer than|more than|over|above)\s+(\d+)\s+characters?\b",
    re.IGNORECASE,
)
_NUMERIC_GREATER_THAN_PATTERN = re.compile(
    r"\b(?P<field>[A-Za-z_][A-Za-z0-9_-]*)\s+(?:greater than|more than|over|above)\s+(?P<threshold>-?\d+)\b",
    re.IGNORECASE,
)
_NEGATIVE_FIELD_PATTERN = re.compile(
    r"\bnegative\s+(?P<field>[A-Za-z_][A-Za-z0-9_-]*)\b",
    re.IGNORECASE,
)
_ZERO_FIELD_PATTERN = re.compile(
    r"\bzero\s+(?P<field>[A-Za-z_][A-Za-z0-9_-]*)\b",
    re.IGNORECASE,
)


def _boundary_case_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if case.execute is None:
        return diagnostics
    case_text = " ".join(part.strip() for part in (case.title, case.objective) if part and part.strip())
    if not case_text:
        return diagnostics
    strict = _boundary_literals_required(authoring_plan, case)
    diagnostics.extend(_string_boundary_diagnostics(case.execute.body, case_text, case_ref, index=index, strict=strict))
    diagnostics.extend(
        _numeric_boundary_diagnostics(case.execute.params, case.execute.body, case_text, case_ref, index=index, strict=strict)
    )
    return diagnostics


def _string_length_overflow_threshold(value: str) -> int | None:
    match = _STRING_LENGTH_OVERFLOW_PATTERN.search(value)
    if match is None:
        return None
    return int(match.group(1))


def _collect_string_literals(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        collected: list[str] = []
        for nested_value in value.values():
            collected.extend(_collect_string_literals(nested_value))
        return collected
    if isinstance(value, (list, tuple, set)):
        collected: list[str] = []
        for nested_value in value:
            collected.extend(_collect_string_literals(nested_value))
        return collected
    return []


def _string_boundary_diagnostics(
    body: Any,
    case_text: str,
    case_ref: str,
    *,
    index: int,
    strict: bool,
) -> list[GenerationDiagnostic]:
    threshold = _string_length_overflow_threshold(case_text)
    if threshold is None:
        return []
    string_lengths = [
        len(value)
        for value in _collect_string_literals(body)
        if value and not _extract_placeholders(value)
    ]
    if not string_lengths:
        return []
    actual_max_length = max(string_lengths)
    if actual_max_length > threshold:
        return []
    return [
        authoring_diagnostic(
            _boundary_mismatch_code(strict),
            (
                "Case text indicates a string-overflow boundary, but the authored request body does not exceed it. "
                "Use a literal longer than the stated threshold."
            ),
            severity=heuristic_or_strict_severity(strict),
            source_ref=case_ref,
            details={
                "case_index": index,
                "threshold": threshold,
                "actual_max_length": actual_max_length,
            },
        )
    ]


def _numeric_boundary_diagnostics(
    params: dict[str, Any],
    body: Any,
    case_text: str,
    case_ref: str,
    *,
    index: int,
    strict: bool,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    numeric_literals = [
        (path, value)
        for path, value in _collect_numeric_literals({"params": params, "body": body})
        if not _numeric_path_has_placeholder(path)
    ]
    if not numeric_literals:
        return diagnostics

    for match in _NUMERIC_GREATER_THAN_PATTERN.finditer(case_text):
        field_name = match.group("field")
        threshold = int(match.group("threshold"))
        diagnostics.extend(
            _numeric_case_boundary_mismatch_diagnostics(
                numeric_literals,
                field_name=field_name,
                case_ref=case_ref,
                case_index=index,
                predicate=lambda value, limit=threshold: value > limit,
                message=(
                    "Case text indicates a numeric overflow boundary, but the authored value does not exceed it. "
                    "Use a literal greater than the stated threshold."
                ),
                details={"threshold": threshold, "field": field_name, "rule": "greater_than"},
                strict=strict,
            )
        )

    for match in _NEGATIVE_FIELD_PATTERN.finditer(case_text):
        field_name = match.group("field")
        diagnostics.extend(
            _numeric_case_boundary_mismatch_diagnostics(
                numeric_literals,
                field_name=field_name,
                case_ref=case_ref,
                case_index=index,
                predicate=lambda value: value < 0,
                message=(
                    "Case text indicates a negative numeric boundary, but the authored value is not negative. "
                    "Use a negative literal for the stated field."
                ),
                details={"field": field_name, "rule": "negative"},
                strict=strict,
            )
        )

    for match in _ZERO_FIELD_PATTERN.finditer(case_text):
        field_name = match.group("field")
        diagnostics.extend(
            _numeric_case_boundary_mismatch_diagnostics(
                numeric_literals,
                field_name=field_name,
                case_ref=case_ref,
                case_index=index,
                predicate=lambda value: value == 0,
                message=(
                    "Case text indicates a zero-value boundary, but the authored value is not zero. "
                    "Use zero for the stated field."
                ),
                details={"field": field_name, "rule": "zero"},
                strict=strict,
            )
        )

    return diagnostics


def _numeric_case_boundary_mismatch_diagnostics(
    numeric_literals: list[tuple[str, int | float]],
    *,
    field_name: str,
    case_ref: str,
    case_index: int,
    predicate: Any,
    message: str,
    details: dict[str, Any],
    strict: bool,
) -> list[GenerationDiagnostic]:
    relevant_literals = _relevant_numeric_literals(numeric_literals, field_name)
    if not relevant_literals:
        return [
            authoring_diagnostic(
                _boundary_mismatch_code(strict),
                "Case text indicates a numeric boundary, but no authored numeric literal was found for the stated field.",
                severity=heuristic_or_strict_severity(strict),
                source_ref=case_ref,
                details={**details, "case_index": case_index, "actual_values": []},
            )
        ]
    if any(predicate(value) for _, value in relevant_literals):
        return []
    return [
        authoring_diagnostic(
            _boundary_mismatch_code(strict),
            message,
            severity=heuristic_or_strict_severity(strict),
            source_ref=case_ref,
            details={
                **details,
                "case_index": case_index,
                "actual_values": [value for _, value in relevant_literals],
            },
        )
    ]


def _boundary_literals_required(authoring_plan: AuthoringPlan, case: AuthoringCase) -> bool:
    plan_boundary_contract = plan_contract_section(authoring_plan, "boundary")
    if plan_boundary_contract.get("require_literal_boundary_match") is not None:
        return bool(plan_boundary_contract.get("require_literal_boundary_match"))
    boundary_contract = case_contract_section(case, "boundary")
    return bool(boundary_contract.get("require_literal_boundary_match"))


def _boundary_mismatch_code(strict: bool) -> str:
    return "authoring_case_boundary_contract_mismatch" if strict else "authoring_case_boundary_mismatch"


def _collect_numeric_literals(value: Any, *, path: str = "") -> list[tuple[str, int | float]]:
    if value is None:
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [(path, value)]
    if isinstance(value, str):
        return []
    if isinstance(value, dict):
        collected: list[tuple[str, int | float]] = []
        for key, nested_value in value.items():
            nested_path = f"{path}.{key}" if path else str(key)
            collected.extend(_collect_numeric_literals(nested_value, path=nested_path))
        return collected
    if isinstance(value, (list, tuple, set)):
        collected: list[tuple[str, int | float]] = []
        for index, nested_value in enumerate(value):
            nested_path = f"{path}[{index}]" if path else f"[{index}]"
            collected.extend(_collect_numeric_literals(nested_value, path=nested_path))
        return collected
    return []


def _relevant_numeric_literals(
    numeric_literals: list[tuple[str, int | float]],
    field_name: str,
) -> list[tuple[str, int | float]]:
    normalized_field = _normalize_case_field_name(field_name)
    relevant = [
        (path, value)
        for path, value in numeric_literals
        if normalized_field in {_normalize_case_field_name(part) for part in _numeric_path_parts(path)}
    ]
    if relevant:
        return relevant
    return numeric_literals


def _numeric_path_has_placeholder(path: str) -> bool:
    return bool(_extract_placeholders(path))
