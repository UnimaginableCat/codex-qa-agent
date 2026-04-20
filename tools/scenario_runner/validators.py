"""Declarative expectation validators for scenario runner steps."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from tools.common.errors import ValidationError
from tools.common.statuses import StepStatus

from .models import ExpectationCheckResult, ScenarioStep, ScenarioStepType

_HTTP_EXPECTATION_RE = re.compile(r"^\s*HTTP\s+(\d{3})(?:\s+or\s+HTTP\s+(\d{3}))?\s*$", re.IGNORECASE)
_RESPONSE_CONTAINS_FIELD_RE = re.compile(r"^\s*response\s+contains\s+field\s+(.+?)\s*$", re.IGNORECASE)
_RESPONSE_EQUALS_RE = re.compile(r"^\s*response\s+(.+?)\s*=\s*(.+?)\s*$", re.IGNORECASE)
_RESPONSE_NOT_NULL_RE = re.compile(r"^\s*response\s+(.+?)\s+is\s+not\s+null\s*$", re.IGNORECASE)
_ARRAY_CONTAINS_RE = re.compile(
    r"^\s*array\s+contains\s+item\s+with\s+(.+?)\s*=\s*(.+?)\s*$",
    re.IGNORECASE,
)
_DB_EQUALS_RE = re.compile(r"^\s*(.+?)\s*=\s*(.+?)\s*$", re.IGNORECASE)
_DB_IS_NULL_RE = re.compile(r"^\s*(.+?)\s+is\s+null\s*$", re.IGNORECASE)
_DB_IS_NOT_NULL_RE = re.compile(r"^\s*(.+?)\s+is\s+not\s+null\s*$", re.IGNORECASE)
_DB_STARTS_WITH_RE = re.compile(r"^\s*(.+?)\s+starts\s+with\s+(.+?)\s*$", re.IGNORECASE)
_VALIDATION_STATUS_PRIORITY = {
    StepStatus.PASS: 0,
    StepStatus.FAIL: 1,
    StepStatus.BLOCKED: 2,
    StepStatus.ERROR: 3,
}


class ExpectationValidationError(ValidationError):
    """Raised when an expectation rule is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class _PathLookupResult:
    exists: bool
    value: Any = None
    detail: str = ""


class ScenarioStepValidator:
    """Validates parsed expectation strings against structured tool payloads."""

    def validate(self, step: ScenarioStep, tool_payload: dict[str, Any]) -> list[ExpectationCheckResult]:
        expectations = self._expectations(step)
        if not expectations:
            return []

        if step.step_type == ScenarioStepType.API:
            return [self._validate_api_expectation(expectation, tool_payload) for expectation in expectations]
        return [self._validate_db_expectation(expectation, tool_payload) for expectation in expectations]

    @staticmethod
    def final_status(expectation_results: list[ExpectationCheckResult]) -> StepStatus:
        if not expectation_results:
            return StepStatus.PASS
        return max((result.status for result in expectation_results), key=_VALIDATION_STATUS_PRIORITY.__getitem__)

    def _validate_api_expectation(
        self,
        expectation: str,
        tool_payload: dict[str, Any],
    ) -> ExpectationCheckResult:
        response = tool_payload.get("response")
        response_body = response.get("body") if isinstance(response, dict) else None
        http_status = response.get("http_status") if isinstance(response, dict) else None
        normalized_expectation = self._normalize_keyword(expectation)

        if match := _HTTP_EXPECTATION_RE.fullmatch(expectation):
            allowed_statuses = [int(match.group(1))]
            if match.group(2):
                allowed_statuses.append(int(match.group(2)))
            passed = http_status in allowed_statuses
            detail = f"Actual HTTP status: {http_status}"
            return self._result(expectation, passed, detail)

        if normalized_expectation == "response json exists":
            passed = isinstance(response_body, (dict, list))
            detail = f"Actual response body type: {type(response_body).__name__}"
            return self._result(expectation, passed, detail)

        if normalized_expectation == "response json is an array":
            passed = isinstance(response_body, list)
            detail = f"Actual response body type: {type(response_body).__name__}"
            return self._result(expectation, passed, detail)

        if match := _RESPONSE_CONTAINS_FIELD_RE.fullmatch(expectation):
            field_path = self._parse_field_path(match.group(1))
            lookup = self._try_get_path(response_body, field_path)
            return self._result(
                expectation,
                lookup.exists,
                f"Field path: {field_path}. {lookup.detail}",
            )

        if match := _RESPONSE_EQUALS_RE.fullmatch(expectation):
            field_path = self._parse_field_path(match.group(1))
            expected_value = self._parse_literal(match.group(2))
            lookup = self._try_get_path(response_body, field_path)
            return self._result(
                expectation,
                lookup.exists and self._values_equal(lookup.value, expected_value),
                f"Expected value: {expected_value!r}. Actual value: {lookup.value!r}. {lookup.detail}",
            )

        if match := _RESPONSE_NOT_NULL_RE.fullmatch(expectation):
            field_path = self._parse_field_path(match.group(1))
            lookup = self._try_get_path(response_body, field_path)
            return self._result(
                expectation,
                lookup.exists and lookup.value is not None,
                f"Actual value: {lookup.value!r}. {lookup.detail}",
            )

        if match := _ARRAY_CONTAINS_RE.fullmatch(expectation):
            field_path = self._parse_field_path(match.group(1))
            expected_value = self._parse_literal(match.group(2))
            if not isinstance(response_body, list):
                return self._result(
                    expectation,
                    False,
                    f"Actual response body type: {type(response_body).__name__}",
                )
            passed = False
            last_detail = "Array is empty."
            for item in response_body:
                lookup = self._try_get_path(item, field_path)
                last_detail = lookup.detail
                if lookup.exists and self._values_equal(lookup.value, expected_value):
                    passed = True
                    last_detail = f"Matched value: {lookup.value!r}."
                    break
            return self._result(
                expectation,
                passed,
                f"Searched field: {field_path}. Expected value: {expected_value!r}. {last_detail}",
            )

        return self._unsupported_result(expectation, "API")

    def _validate_db_expectation(
        self,
        expectation: str,
        tool_payload: dict[str, Any],
    ) -> ExpectationCheckResult:
        query = tool_payload.get("query")
        rows = query.get("rows") if isinstance(query, dict) else None
        row_count = query.get("row_count") if isinstance(query, dict) else None
        first_row_result = self._first_db_row(rows)
        normalized_expectation = self._normalize_keyword(expectation)

        if normalized_expectation == "one row exists":
            actual_row_count = row_count if isinstance(row_count, int) else len(rows) if isinstance(rows, list) else None
            passed = actual_row_count == 1
            return self._result(expectation, passed, f"Actual row_count: {actual_row_count}")

        if match := _DB_IS_NULL_RE.fullmatch(expectation):
            field_path = self._parse_field_path(match.group(1))
            lookup = self._try_get_path(first_row_result.value, field_path) if first_row_result.exists else first_row_result
            return self._result(
                expectation,
                lookup.exists and lookup.value is None,
                f"Checked first row. Actual value: {lookup.value!r}. {lookup.detail}",
            )

        if match := _DB_IS_NOT_NULL_RE.fullmatch(expectation):
            field_path = self._parse_field_path(match.group(1))
            lookup = self._try_get_path(first_row_result.value, field_path) if first_row_result.exists else first_row_result
            return self._result(
                expectation,
                lookup.exists and lookup.value is not None,
                f"Checked first row. Actual value: {lookup.value!r}. {lookup.detail}",
            )

        if match := _DB_STARTS_WITH_RE.fullmatch(expectation):
            field_path = self._parse_field_path(match.group(1))
            expected_prefix = str(self._parse_literal(match.group(2)))
            lookup = self._try_get_path(first_row_result.value, field_path) if first_row_result.exists else first_row_result
            passed = lookup.exists and isinstance(lookup.value, str) and lookup.value.startswith(expected_prefix)
            return self._result(
                expectation,
                passed,
                f"Checked first row. Expected prefix: {expected_prefix!r}. Actual value: {lookup.value!r}. {lookup.detail}",
            )

        if match := _DB_EQUALS_RE.fullmatch(expectation):
            field_path = self._parse_field_path(match.group(1))
            expected_value = self._parse_literal(match.group(2))
            lookup = self._try_get_path(first_row_result.value, field_path) if first_row_result.exists else first_row_result
            return self._result(
                expectation,
                lookup.exists and self._values_equal(lookup.value, expected_value),
                f"Checked first row. Expected value: {expected_value!r}. Actual value: {lookup.value!r}. {lookup.detail}",
            )

        return self._unsupported_result(expectation, "DB")

    @staticmethod
    def _expectations(step: ScenarioStep) -> list[str]:
        if step.step_type == ScenarioStepType.API:
            return [] if step.api is None else list(step.api.expected)
        return [] if step.db is None else list(step.db.expected)

    @staticmethod
    def _result(rule: str, passed: bool, detail: str | None = None) -> ExpectationCheckResult:
        return ExpectationCheckResult(
            rule=rule,
            status=StepStatus.PASS if passed else StepStatus.FAIL,
            detail=detail,
        )

    @classmethod
    def _unsupported_result(cls, rule: str, step_type: str) -> ExpectationCheckResult:
        return ExpectationCheckResult(
            rule=rule,
            status=StepStatus.BLOCKED,
            detail=f"Unsupported {step_type} expectation rule.",
        )

    @classmethod
    def _try_get_path(cls, root: Any, field_path: str) -> _PathLookupResult:
        path_segments = cls._split_field_path(field_path)
        if not path_segments:
            return _PathLookupResult(False, None, "Field path is empty.")
        if root is None:
            return _PathLookupResult(False, None, "Root value is missing.")

        current = root
        traversed: list[str] = []
        for segment in path_segments:
            if not segment:
                return _PathLookupResult(False, None, f"Field path '{field_path}' contains an empty segment.")
            current_location = ".".join(traversed) if traversed else "<root>"
            if isinstance(current, dict):
                if segment not in current:
                    return _PathLookupResult(
                        False,
                        None,
                        f"Missing path segment '{segment}' at {current_location}.",
                    )
                current = current[segment]
                traversed.append(segment)
                continue
            if isinstance(current, list):
                if not segment.isdigit():
                    return _PathLookupResult(
                        False,
                        None,
                        f"Expected numeric list index at segment '{segment}' in path '{field_path}'.",
                    )
                index = int(segment)
                if index >= len(current):
                    return _PathLookupResult(
                        False,
                        None,
                        f"List index {index} is out of range at {current_location}.",
                    )
                current = current[index]
                traversed.append(segment)
                continue
            return _PathLookupResult(
                False,
                None,
                f"Cannot resolve segment '{segment}' at {current_location}; actual type is {type(current).__name__}.",
            )
        return _PathLookupResult(True, current, f"Resolved path '{field_path}'.")

    @staticmethod
    def _parse_literal(raw_value: str) -> Any:
        normalized = raw_value.strip()
        if not normalized:
            return ""
        lowered = normalized.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None
        if (normalized.startswith('"') and normalized.endswith('"')) or (
            normalized.startswith("'") and normalized.endswith("'")
        ) or (
            normalized.startswith("`") and normalized.endswith("`")
        ):
            return normalized[1:-1]
        if re.fullmatch(r"-?\d+", normalized):
            return int(normalized)
        if re.fullmatch(r"-?(?:\d+\.\d+|\d+\.|\.\d+)(?:[eE][+-]?\d+)?|-?\d+[eE][+-]?\d+", normalized):
            return float(normalized)
        return normalized

    @classmethod
    def _values_equal(cls, actual_value: Any, expected_value: Any) -> bool:
        normalized_actual = cls._parse_literal(actual_value) if isinstance(actual_value, str) else actual_value
        return normalized_actual == expected_value

    @classmethod
    def _parse_field_path(cls, raw_field_path: str) -> str:
        return cls._strip_wrapping_quotes(raw_field_path.strip()).strip()

    @classmethod
    def _split_field_path(cls, field_path: str) -> list[str]:
        normalized_path = cls._parse_field_path(field_path)
        if not normalized_path:
            return []
        return [
            cls._strip_wrapping_quotes(segment.strip()).strip()
            for segment in normalized_path.split(".")
        ]

    @staticmethod
    def _strip_wrapping_quotes(value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
            return value[1:-1]
        return value

    @staticmethod
    def _normalize_keyword(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip()).lower()

    @staticmethod
    def _first_db_row(rows: Any) -> _PathLookupResult:
        if not isinstance(rows, list):
            return _PathLookupResult(False, None, "DB rows are missing or not an array.")
        if not rows:
            return _PathLookupResult(False, None, "No DB rows available; field checks use the first row.")
        first_row = rows[0]
        if not isinstance(first_row, dict):
            return _PathLookupResult(False, None, f"First DB row is {type(first_row).__name__}, expected object.")
        return _PathLookupResult(True, first_row, "Using first DB row.")
