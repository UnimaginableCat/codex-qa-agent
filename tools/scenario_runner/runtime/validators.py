"""Declarative expectation validators for scenario runner steps."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from numbers import Number
import re
from typing import Any

from tools.common.errors import ValidationError
from tools.common.statuses import StepStatus

from .interpolator import EXACT_PLACEHOLDER_PATTERN, InterpolationError, PlaceholderInterpolator
from ..domain.models import ExpectationCheckResult, ScenarioStep, ScenarioStepType
from .path_lookup import PathLookupResult as _PathLookupResult
from .path_lookup import resolve_path

_HTTP_EXPECTATION_RE = re.compile(r"^\s*HTTP\s+(\d{3})(?:\s+or\s+HTTP\s+(\d{3}))?\s*$", re.IGNORECASE)
_RESPONSE_CONTAINS_FIELD_RE = re.compile(r"^\s*response\s+contains\s+field\s+(.+?)\s*$", re.IGNORECASE)
_RESPONSE_LENGTH_RE = re.compile(
    r"^\s*response\s+(.+?)\s+length\s*(>=|<=|!=|=|>|<)\s*(.+?)\s*$",
    re.IGNORECASE,
)
_RESPONSE_VALUE_RE = re.compile(r"^\s*response\s+(.+?)\s*$", re.IGNORECASE)
_RESPONSE_NOT_NULL_RE = re.compile(r"^\s*response\s+(.+?)\s+is\s+not\s+null\s*$", re.IGNORECASE)
_ARRAY_CONTAINS_RE = re.compile(
    r"^\s*array\s+contains\s+item\s+with\s+(.+?)\s*=\s*(.+?)\s*$",
    re.IGNORECASE,
)
_DB_IS_NULL_RE = re.compile(r"^\s*(.+?)\s+is\s+null\s*$", re.IGNORECASE)
_DB_IS_NOT_NULL_RE = re.compile(r"^\s*(.+?)\s+is\s+not\s+null\s*$", re.IGNORECASE)
_DB_STARTS_WITH_RE = re.compile(r"^\s*(.+?)\s+starts\s+with\s+(.+?)\s*$", re.IGNORECASE)
_COMPARISON_OPERATORS = (">=", "<=", "!=", "=", ">", "<")
_COMPARISON_OPERATOR_CHARS = frozenset("!<=>")
_VALIDATION_STATUS_PRIORITY = {
    StepStatus.PASS: 0,
    StepStatus.FAIL: 1,
    StepStatus.BLOCKED: 2,
    StepStatus.ERROR: 3,
}


@dataclass(frozen=True, slots=True)
class _ComparisonRule:
    left: str
    operator: str
    right: str


@dataclass(frozen=True, slots=True)
class ExpectationContractDiagnostic:
    rule: str
    step_type: ScenarioStepType
    supported: bool
    detail: str


class ExpectationValidationError(ValidationError):
    """Raised when an expectation rule is malformed or unsupported."""


class ScenarioStepValidator:
    """Validates parsed expectation strings against structured tool payloads."""

    def __init__(self, interpolator: PlaceholderInterpolator | None = None) -> None:
        self._interpolator = interpolator or PlaceholderInterpolator()

    def validate(
        self,
        step: ScenarioStep,
        tool_payload: dict[str, Any],
        variables: dict[str, Any] | None = None,
    ) -> list[ExpectationCheckResult]:
        expectations = self._expectations(step)
        if not expectations:
            return []

        raw_expectations = list(expectations)
        if variables is not None:
            interpolated_expectations: list[str] = []
            for expectation in expectations:
                try:
                    interpolated_expectations.append(str(self._interpolator.interpolate(expectation, variables)))
                except InterpolationError as exc:
                    return [
                        ExpectationCheckResult(
                            rule=expectation,
                            status=StepStatus.BLOCKED,
                            detail=f"Expectation interpolation failed: {exc}",
                        )
                    ]
            expectations = interpolated_expectations

        if step.step_type == ScenarioStepType.API:
            return [
                self._validate_api_expectation(
                    expectation,
                    tool_payload,
                    variables=variables,
                    raw_expectation=raw_expectations[index],
                )
                for index, expectation in enumerate(expectations)
            ]
        return [self._validate_db_expectation(expectation, tool_payload) for expectation in expectations]

    def inspect_contract(self, step: ScenarioStep) -> list[ExpectationContractDiagnostic]:
        diagnostics: list[ExpectationContractDiagnostic] = []
        for expectation in self._expectations(step):
            if step.step_type == ScenarioStepType.API:
                diagnostics.append(self._inspect_api_expectation_contract(expectation))
            else:
                diagnostics.append(self._inspect_db_expectation_contract(expectation))
        return diagnostics

    @staticmethod
    def final_status(expectation_results: list[ExpectationCheckResult]) -> StepStatus:
        if not expectation_results:
            return StepStatus.PASS
        return max((result.status for result in expectation_results), key=_VALIDATION_STATUS_PRIORITY.__getitem__)

    def _validate_api_expectation(
        self,
        expectation: str,
        tool_payload: dict[str, Any],
        variables: dict[str, Any] | None = None,
        raw_expectation: str | None = None,
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

        if normalized_expectation == "response body exists":
            content_length = response.get("content_length_bytes") if isinstance(response, dict) else None
            if isinstance(content_length, int) and not isinstance(content_length, bool):
                passed = content_length > 0
                detail = (
                    f"Actual response body type: {type(response_body).__name__}. "
                    f"Content length bytes: {content_length}."
                )
            else:
                passed = response_body is not None and response_body != ""
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

        if match := _RESPONSE_LENGTH_RE.fullmatch(expectation):
            field_path = self._parse_field_path(match.group(1))
            operator = match.group(2)
            expected_length = self._parse_literal(match.group(3))
            lookup = self._try_get_path(response_body, field_path)
            if not lookup.exists:
                return self._result(expectation, False, f"Field path: {field_path}. {lookup.detail}")
            if not isinstance(expected_length, int) or isinstance(expected_length, bool):
                return self._result(
                    expectation,
                    False,
                    f"Expected length must be an integer. Parsed expected value: {expected_length!r}.",
                )
            if not hasattr(lookup.value, "__len__") or isinstance(lookup.value, (bool, int, float)):
                return self._result(
                    expectation,
                    False,
                    f"Value at '{field_path}' has no length; actual type is {type(lookup.value).__name__}.",
                )
            actual_length = len(lookup.value)
            passed, comparison_detail = self._compare_values(actual_length, expected_length, operator)
            return self._result(
                expectation,
                passed,
                (
                    f"Field path: {field_path}. Operator: {operator}. Expected length: {expected_length}. "
                    f"Actual length: {actual_length}. {comparison_detail} {lookup.detail}"
                ),
            )

        if match := _RESPONSE_VALUE_RE.fullmatch(expectation):
            comparison_rule = self._split_comparison_rule(match.group(1))
            if comparison_rule is None:
                comparison_rule = self._raw_api_typed_comparison_rule(raw_expectation, variables)
            if comparison_rule is not None:
                if self._is_ambiguous_root_length_comparison(comparison_rule):
                    return self._unsupported_result(expectation, "API")
                field_path = self._parse_field_path(comparison_rule.left)
                raw_rhs = self._raw_api_comparison_rhs(raw_expectation, comparison_rule.operator)
                expected_value = self._parse_api_expected_value(comparison_rule.right, raw_rhs, variables)
                lookup = self._try_get_path(response_body, field_path)
                passed, comparison_detail = self._compare_values(
                    lookup.value,
                    expected_value,
                    comparison_rule.operator,
                )
                return self._result(
                    expectation,
                    lookup.exists and passed,
                    (
                        f"Field path: {field_path}. Operator: {comparison_rule.operator}. "
                        f"Expected value: {expected_value!r}. Actual value: {lookup.value!r}. "
                        f"{comparison_detail} {lookup.detail}"
                    ),
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

        if self._looks_like_malformed_comparison(expectation):
            return self._unsupported_result(expectation, "API")

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
        db_expectation = self._normalize_db_expectation_rule(expectation)
        normalized_expectation = self._normalize_keyword(db_expectation)

        if normalized_expectation == "one row exists":
            actual_row_count = row_count if isinstance(row_count, int) else len(rows) if isinstance(rows, list) else None
            passed = actual_row_count == 1
            return self._result(expectation, passed, f"Actual row_count: {actual_row_count}")

        if normalized_expectation == "no rows exist":
            actual_row_count = row_count if isinstance(row_count, int) else len(rows) if isinstance(rows, list) else None
            passed = actual_row_count == 0
            return self._result(expectation, passed, f"Actual row_count: {actual_row_count}")

        if match := _DB_IS_NULL_RE.fullmatch(db_expectation):
            field_path = self._parse_field_path(match.group(1))
            lookup = self._try_get_path(first_row_result.value, field_path) if first_row_result.exists else first_row_result
            return self._result(
                expectation,
                lookup.exists and lookup.value is None,
                f"Checked first row. Actual value: {lookup.value!r}. {lookup.detail}",
            )

        if match := _DB_IS_NOT_NULL_RE.fullmatch(db_expectation):
            field_path = self._parse_field_path(match.group(1))
            lookup = self._try_get_path(first_row_result.value, field_path) if first_row_result.exists else first_row_result
            return self._result(
                expectation,
                lookup.exists and lookup.value is not None,
                f"Checked first row. Actual value: {lookup.value!r}. {lookup.detail}",
            )

        if match := _DB_STARTS_WITH_RE.fullmatch(db_expectation):
            field_path = self._parse_field_path(match.group(1))
            expected_prefix = str(self._parse_literal(match.group(2)))
            lookup = self._try_get_path(first_row_result.value, field_path) if first_row_result.exists else first_row_result
            passed = lookup.exists and isinstance(lookup.value, str) and lookup.value.startswith(expected_prefix)
            return self._result(
                expectation,
                passed,
                f"Checked first row. Expected prefix: {expected_prefix!r}. Actual value: {lookup.value!r}. {lookup.detail}",
            )

        comparison_rule = self._split_comparison_rule(db_expectation)
        if comparison_rule is not None:
            field_path = self._parse_field_path(comparison_rule.left)
            expected_value = self._parse_literal(comparison_rule.right)
            lookup = self._try_get_path(first_row_result.value, field_path) if first_row_result.exists else first_row_result
            passed, comparison_detail = self._compare_values(lookup.value, expected_value, comparison_rule.operator)
            return self._result(
                expectation,
                lookup.exists and passed,
                (
                    f"Checked first row. Field path: {field_path}. Operator: {comparison_rule.operator}. "
                    f"Expected value: {expected_value!r}. Actual value: {lookup.value!r}. "
                    f"{comparison_detail} {lookup.detail}"
                ),
            )

        if self._looks_like_malformed_comparison(db_expectation):
            return self._unsupported_result(expectation, "DB")

        return self._unsupported_result(expectation, "DB")

    def _inspect_api_expectation_contract(self, expectation: str) -> ExpectationContractDiagnostic:
        normalized_expectation = self._normalize_keyword(expectation)
        supported = any(
            (
                _HTTP_EXPECTATION_RE.fullmatch(expectation),
                normalized_expectation == "response json exists",
                normalized_expectation == "response body exists",
                normalized_expectation == "response json is an array",
                _RESPONSE_CONTAINS_FIELD_RE.fullmatch(expectation),
                _RESPONSE_LENGTH_RE.fullmatch(expectation),
                _RESPONSE_NOT_NULL_RE.fullmatch(expectation),
                _ARRAY_CONTAINS_RE.fullmatch(expectation),
                (
                    (_RESPONSE_VALUE_RE.fullmatch(expectation) is not None)
                    and (
                        (
                            comparison_rule := self._split_comparison_rule(
                                _RESPONSE_VALUE_RE.fullmatch(expectation).group(1)
                            )
                        )
                        is not None
                        and not self._is_ambiguous_root_length_comparison(comparison_rule)
                    )
                ),
            )
        )
        return ExpectationContractDiagnostic(
            rule=expectation,
            step_type=ScenarioStepType.API,
            supported=supported,
            detail=(
                f"Unsupported expectation rule: {expectation} (API)."
                if not supported
                else "Expectation syntax is supported."
            ),
        )

    def _inspect_db_expectation_contract(self, expectation: str) -> ExpectationContractDiagnostic:
        normalized_rule = self._normalize_db_expectation_rule(expectation)
        normalized_expectation = self._normalize_keyword(normalized_rule)
        supported = any(
            (
                normalized_expectation == "one row exists",
                normalized_expectation == "no rows exist",
                _DB_IS_NULL_RE.fullmatch(normalized_rule),
                _DB_IS_NOT_NULL_RE.fullmatch(normalized_rule),
                _DB_STARTS_WITH_RE.fullmatch(normalized_rule),
                self._split_comparison_rule(normalized_rule) is not None,
            )
        )
        return ExpectationContractDiagnostic(
            rule=expectation,
            step_type=ScenarioStepType.DB,
            supported=supported,
            detail=(
                f"Unsupported expectation rule: {expectation} (DB)."
                if not supported
                else "Expectation syntax is supported."
            ),
        )

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
            detail=f"Unsupported expectation rule: {rule} ({step_type}).",
        )

    @classmethod
    def _try_get_path(cls, root: Any, field_path: str) -> _PathLookupResult:
        return resolve_path(root, field_path)

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
        if normalized.startswith("`") and normalized.endswith("`"):
            return ScenarioStepValidator._parse_literal(normalized[1:-1])
        if (normalized.startswith('"') and normalized.endswith('"')) or (
            normalized.startswith("'") and normalized.endswith("'")
        ):
            return normalized[1:-1]
        if re.fullmatch(r"-?\d+", normalized):
            return int(normalized)
        if re.fullmatch(r"-?(?:\d+\.\d+|\d+\.|\.\d+)(?:[eE][+-]?\d+)?|-?\d+[eE][+-]?\d+", normalized):
            return float(normalized)
        return normalized

    @classmethod
    def _parse_api_expected_value(
        cls,
        interpolated_raw_value: str,
        raw_value: str | None,
        variables: dict[str, Any] | None,
    ) -> Any:
        if raw_value is not None and variables is not None:
            variable_name = cls._typed_placeholder_variable_name(raw_value)
            if variable_name is not None and variable_name in variables:
                return deepcopy(variables[variable_name])
        return cls._parse_literal(interpolated_raw_value)

    @staticmethod
    def _typed_placeholder_variable_name(raw_value: str) -> str | None:
        normalized = raw_value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] == "`":
            normalized = normalized[1:-1].strip()
        match = EXACT_PLACEHOLDER_PATTERN.fullmatch(normalized)
        return match.group(1) if match else None

    @classmethod
    def _raw_api_comparison_rhs(cls, raw_expectation: str | None, operator: str) -> str | None:
        if raw_expectation is None:
            return None
        match = _RESPONSE_VALUE_RE.fullmatch(raw_expectation)
        if match is None:
            return None
        comparison_rule = cls._split_comparison_rule(match.group(1))
        if comparison_rule is None or comparison_rule.operator != operator:
            return None
        return comparison_rule.right

    @classmethod
    def _raw_api_typed_comparison_rule(
        cls,
        raw_expectation: str | None,
        variables: dict[str, Any] | None,
    ) -> _ComparisonRule | None:
        if raw_expectation is None or variables is None:
            return None
        match = _RESPONSE_VALUE_RE.fullmatch(raw_expectation)
        if match is None:
            return None
        comparison_rule = cls._split_comparison_rule(match.group(1))
        if comparison_rule is None:
            return None
        variable_name = cls._typed_placeholder_variable_name(comparison_rule.right)
        if variable_name is None or variable_name not in variables:
            return None
        return comparison_rule

    @classmethod
    def _values_equal(cls, actual_value: Any, expected_value: Any) -> bool:
        if isinstance(actual_value, bool) or isinstance(expected_value, bool):
            return type(actual_value) is bool and type(expected_value) is bool and actual_value == expected_value
        if isinstance(actual_value, Number) and isinstance(expected_value, Number):
            return actual_value == expected_value
        return actual_value == expected_value

    @classmethod
    def _compare_values(cls, actual_value: Any, expected_value: Any, operator: str) -> tuple[bool, str]:
        if operator == "=":
            return cls._values_equal(actual_value, expected_value), "Compared by equality."
        if operator == "!=":
            return not cls._values_equal(actual_value, expected_value), "Compared by inequality."

        if not cls._is_non_bool_number(actual_value) or not cls._is_non_bool_number(expected_value):
            return (
                False,
                (
                    f"Operator {operator!r} requires numeric values; actual type is "
                    f"{type(actual_value).__name__}, expected type is {type(expected_value).__name__}."
                ),
            )

        if operator == ">":
            return actual_value > expected_value, "Compared numerically."
        if operator == ">=":
            return actual_value >= expected_value, "Compared numerically."
        if operator == "<":
            return actual_value < expected_value, "Compared numerically."
        if operator == "<=":
            return actual_value <= expected_value, "Compared numerically."
        return False, f"Unsupported comparison operator: {operator!r}."

    @staticmethod
    def _is_non_bool_number(value: Any) -> bool:
        return isinstance(value, Number) and not isinstance(value, bool)

    @classmethod
    def _is_ambiguous_root_length_comparison(cls, comparison_rule: _ComparisonRule) -> bool:
        return cls._normalize_keyword(comparison_rule.left) == "length"

    @classmethod
    def _split_comparison_rule(cls, rule: str) -> _ComparisonRule | None:
        normalized = rule.strip()
        quote_char: str | None = None

        for index, char in enumerate(normalized):
            if quote_char is not None:
                if char == quote_char:
                    quote_char = None
                continue
            if char in {'"', "'", "`"}:
                quote_char = char
                continue
            for operator in _COMPARISON_OPERATORS:
                if not normalized.startswith(operator, index):
                    continue
                left = normalized[:index].strip()
                right = normalized[index + len(operator) :].strip()
                if not left or not right:
                    return None
                if left[-1] in _COMPARISON_OPERATOR_CHARS:
                    return None
                return _ComparisonRule(left=left, operator=operator, right=right)
        return None

    @staticmethod
    def _looks_like_malformed_comparison(rule: str) -> bool:
        stripped = rule.strip()
        return any(char in stripped for char in _COMPARISON_OPERATOR_CHARS)

    @classmethod
    def _parse_field_path(cls, raw_field_path: str) -> str:
        return cls._strip_wrapping_quotes(raw_field_path.strip()).strip()

    @classmethod
    def _normalize_db_expectation_rule(cls, expectation: str) -> str:
        normalized = expectation.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'", "`"}:
            if cls._split_comparison_rule(normalized) is not None:
                return normalized
            return normalized[1:-1].strip()
        return normalized

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
