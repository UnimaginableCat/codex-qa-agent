"""DB verification validation rules for operation inventory files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.inventory.common import (
    _diagnostic,
    _is_string_mapping,
    _unknown_entity_diagnostic,
)


def _db_verification_inventory_diagnostics(
    items: list[Any],
    *,
    path: Path,
    known_entities: set[str],
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                _diagnostic(
                    code="adapter_operation_inventory_db_verification_invalid",
                    message="Each db_verifications item must be a YAML object.",
                    path=path,
                    details={"db_verification_index": index},
                )
            )
            continue

        entity_name = str(item.get("entity") or "").strip()
        operation_name = str(item.get("operation") or "").strip()
        if not entity_name or not operation_name:
            diagnostics.append(
                _diagnostic(
                    code="adapter_operation_inventory_db_verification_missing_fields",
                    message="Each db_verifications item must include entity and operation.",
                    path=path,
                    details={"db_verification_index": index},
                )
            )
        elif known_entities and entity_name not in known_entities:
            diagnostics.append(
                _unknown_entity_diagnostic(
                    path=path,
                    entity_name=entity_name,
                    operation_name=operation_name,
                    message="DB verification references an entity not declared in entity-inventory.yaml.",
                )
            )

        column_types = item.get("column_types")
        if column_types is not None and not _is_string_mapping(column_types):
            diagnostics.append(
                _diagnostic(
                    code="adapter_operation_inventory_column_types_invalid",
                    message="DB verification column_types must be a YAML object mapping column names to type names.",
                    path=path,
                    details={"db_verification_index": index, "entity": entity_name, "operation": operation_name},
                )
            )
        diagnostics.extend(
            _db_verification_executable_diagnostics(
                item,
                path=path,
                db_verification_index=index,
            )
        )
    return diagnostics


def _db_verification_executable_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    db_verification_index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    entity_name = str(item.get("entity") or "").strip()
    operation_name = str(item.get("operation") or "").strip()
    scoped_by = _normalized_scoped_by_fields(item.get("scoped_by"))
    sql = str(item.get("sql") or "").strip()
    params = item.get("params")
    expected_outcomes = item.get("expected_outcomes")
    missing_fields: list[str] = []
    if not sql:
        missing_fields.append("sql")
    if not isinstance(params, dict) or any(field_name not in params for field_name in scoped_by):
        missing_fields.append("params")
    if not isinstance(expected_outcomes, list) or not all(str(item).strip() for item in expected_outcomes):
        missing_fields.append("expected_outcomes")
    if missing_fields:
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_db_verification_template_incomplete",
                message="DB verification must include executable sql, params keyed by scoped_by, and expected_outcomes before use in persisted-state checks.",
                path=path,
                details={
                    "db_verification_index": db_verification_index,
                    "entity": entity_name,
                    "operation": operation_name,
                    "missing_fields": missing_fields,
                },
            )
        )
    diagnostics.extend(
        _formula_link_verification_diagnostics(
            item,
            path=path,
            db_verification_index=db_verification_index,
            entity_name=entity_name,
            operation_name=operation_name,
            sql=sql,
            expected_outcomes=expected_outcomes,
        )
    )
    diagnostics.extend(
        _sql_untyped_string_function_param_diagnostics(
            item,
            path=path,
            db_verification_index=db_verification_index,
            entity_name=entity_name,
            operation_name=operation_name,
            sql=sql,
        )
    )
    diagnostics.extend(
        _collection_one_row_verification_diagnostics(
            item,
            path=path,
            db_verification_index=db_verification_index,
            entity_name=entity_name,
            operation_name=operation_name,
            scoped_by=scoped_by,
            sql=sql,
            expected_outcomes=expected_outcomes,
        )
    )
    return diagnostics


def _sql_untyped_string_function_param_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    db_verification_index: int,
    entity_name: str,
    operation_name: str,
    sql: str,
) -> list[GenerationDiagnostic]:
    untyped_params: list[dict[str, str]] = []
    for function_name, call_text in _sql_string_function_calls(sql):
        for param_name in _named_sql_params(call_text):
            if _sql_param_is_explicitly_cast(call_text, param_name):
                continue
            untyped_params.append({"function": function_name, "param": param_name})

    if not untyped_params:
        return []

    return [
        _diagnostic(
            code="adapter_operation_inventory_db_sql_untyped_string_function_param",
            message=(
                "DB verification SQL uses named params inside string-building SQL functions without explicit "
                "casts. PostgreSQL can fail with 'could not determine data type of parameter'. Cast each param "
                "inside CONCAT/CONCAT_WS/FORMAT, for example CAST(:name AS text) or :name::text."
            ),
            path=path,
            details={
                "db_verification_index": db_verification_index,
                "entity": entity_name,
                "operation": operation_name,
                "params": untyped_params,
                "expected_outcomes": item.get("expected_outcomes"),
            },
        )
    ]


def _sql_string_function_calls(sql: str) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    index = 0
    length = len(sql)
    while index < length:
        if sql.startswith("--", index):
            newline_index = sql.find("\n", index)
            if newline_index == -1:
                break
            index = newline_index + 1
            continue
        if sql.startswith("/*", index):
            closing_index = sql.find("*/", index + 2)
            if closing_index == -1:
                break
            index = closing_index + 2
            continue
        current_char = sql[index]
        if current_char in {"'", '"'}:
            index = _consume_sql_quoted(sql, index, current_char)
            continue
        if not (current_char == "_" or current_char.isalpha()):
            index += 1
            continue

        identifier_match = re.match(r"[A-Za-z_]\w*", sql[index:])
        if identifier_match is None:
            index += 1
            continue
        function_name = identifier_match.group(0).lower()
        identifier_end = index + len(identifier_match.group(0))
        if function_name not in {"concat", "concat_ws", "format"}:
            index = identifier_end
            continue

        open_paren_index = _skip_sql_whitespace(sql, identifier_end)
        if open_paren_index >= length or sql[open_paren_index] != "(":
            index = identifier_end
            continue
        close_paren_index = _matching_sql_paren(sql, open_paren_index)
        if close_paren_index is None:
            break
        calls.append((function_name, sql[open_paren_index + 1:close_paren_index]))
        index = close_paren_index + 1
    return calls


def _skip_sql_whitespace(sql: str, index: int) -> int:
    length = len(sql)
    while index < length and sql[index].isspace():
        index += 1
    return index


def _matching_sql_paren(sql: str, open_paren_index: int) -> int | None:
    depth = 0
    index = open_paren_index
    length = len(sql)
    while index < length:
        if sql.startswith("--", index):
            newline_index = sql.find("\n", index)
            if newline_index == -1:
                return None
            index = newline_index + 1
            continue
        if sql.startswith("/*", index):
            closing_index = sql.find("*/", index + 2)
            if closing_index == -1:
                return None
            index = closing_index + 2
            continue
        current_char = sql[index]
        if current_char in {"'", '"'}:
            index = _consume_sql_quoted(sql, index, current_char)
            continue
        if current_char == "(":
            depth += 1
        elif current_char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _named_sql_params(sql: str) -> list[str]:
    params: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        if sql.startswith("--", index):
            newline_index = sql.find("\n", index)
            if newline_index == -1:
                break
            index = newline_index + 1
            continue
        if sql.startswith("/*", index):
            closing_index = sql.find("*/", index + 2)
            if closing_index == -1:
                break
            index = closing_index + 2
            continue
        current_char = sql[index]
        if current_char in {"'", '"'}:
            index = _consume_sql_quoted(sql, index, current_char)
            continue
        if sql.startswith("::", index):
            index += 2
            continue
        if current_char == ":":
            match = re.match(r":([A-Za-z_]\w*)", sql[index:])
            if match:
                params.append(match.group(1))
                index += len(match.group(0))
                continue
        index += 1
    return params


def _consume_sql_quoted(sql: str, start_index: int, quote_char: str) -> int:
    index = start_index + 1
    length = len(sql)
    while index < length:
        if sql[index] == quote_char:
            index += 1
            if index < length and sql[index] == quote_char:
                index += 1
                continue
            break
        index += 1
    return index


def _sql_param_is_explicitly_cast(sql: str, param_name: str) -> bool:
    name = re.escape(param_name)
    return bool(
        re.search(rf"\bcast\s*\(\s*:{name}\s+as\s+[^)]+\)", sql, flags=re.IGNORECASE)
        or re.search(rf":{name}\s*::\s*[a-zA-Z_][\w.]*", sql, flags=re.IGNORECASE)
    )


def _collection_one_row_verification_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    db_verification_index: int,
    entity_name: str,
    operation_name: str,
    scoped_by: list[str],
    sql: str,
    expected_outcomes: Any,
) -> list[GenerationDiagnostic]:
    if not isinstance(expected_outcomes, list):
        return []
    normalized_outcomes = [str(outcome or "").strip().lower() for outcome in expected_outcomes]
    if "one row exists" not in normalized_outcomes:
        return []
    normalized_sql = " ".join(sql.lower().split())
    if not normalized_sql.startswith("select ") or re.search(r"\bcount\s*\(", normalized_sql):
        return []
    if len(scoped_by) != 1:
        return []

    parent_id_param = scoped_by[0]
    equality_filters = _sql_equality_filters(normalized_sql)
    scoped_filters = [
        column_name
        for column_name, parameter_name in equality_filters
        if parameter_name == parent_id_param
    ]
    if not scoped_filters:
        return []
    if any(column_name == "id" for column_name in scoped_filters) and not _has_joined_query_shape(normalized_sql):
        return []

    has_only_parent_scope = all(parameter_name == parent_id_param for _, parameter_name in equality_filters)
    has_row_specific_literal_filter = _has_row_specific_literal_filter(normalized_sql)
    if not has_only_parent_scope or has_row_specific_literal_filter:
        return []

    suspicious_collection_shape = " order by " in normalized_sql or _looks_like_child_collection_query(
        normalized_sql,
        entity_name=entity_name,
        operation_name=operation_name,
    )
    if not suspicious_collection_shape:
        return []

    return [
        _diagnostic(
            code="adapter_operation_inventory_db_verification_one_row_not_case_specific",
            message=(
                "DB verification uses 'one row exists' with a parent-scoped collection query. "
                "Filter to the specific child row being asserted, split expected child rows into separate "
                "verifications, or use a runner-supported aggregate check such as SELECT (COUNT(*) = 1) AS "
                "matching_row_present with expected_outcomes: `matching_row_present` = `true`. LIMIT 1 does "
                "not prove the expected row."
            ),
            path=path,
            details={
                "db_verification_index": db_verification_index,
                "entity": entity_name,
                "operation": operation_name,
                "scoped_by": item.get("scoped_by"),
                "scoped_equality_columns": scoped_filters,
                "expected_outcomes": item.get("expected_outcomes"),
            },
        )
    ]


_SQL_EQUALITY_FILTER_RE = re.compile(r"(?:^|[\s(])(?P<left>[\w.\"\[\]]+)\s*=\s*:(?P<param>[a-zA-Z_]\w*)")


def _sql_equality_filters(normalized_sql: str) -> list[tuple[str, str]]:
    return [
        (_sql_column_name(match.group("left")), match.group("param"))
        for match in _SQL_EQUALITY_FILTER_RE.finditer(normalized_sql)
    ]


def _sql_column_name(value: str) -> str:
    normalized = value.strip().strip('"[]')
    if "." in normalized:
        normalized = normalized.rsplit(".", 1)[-1]
    return normalized.strip().strip('"[]')


def _has_row_specific_literal_filter(normalized_sql: str) -> bool:
    return bool(
        re.search(
            r"(?:^|[\s(])(?:[\w.\"\[\]]+\.)?(?:code|name|type|kind|key|external_id)\s*=\s*('[^']+'|\"[^\"]+\"|\d+)",
            normalized_sql,
        )
    )


def _has_joined_query_shape(normalized_sql: str) -> bool:
    if " join " in normalized_sql:
        return True
    from_match = re.search(r"\bfrom\s+(?P<from_clause>.+?)\s+where\b", normalized_sql)
    return bool(from_match and "," in from_match.group("from_clause"))


def _looks_like_child_collection_query(
    normalized_sql: str,
    *,
    entity_name: str,
    operation_name: str,
) -> bool:
    collection_tokens = (
        "variable",
        "formula",
        "link",
        "item",
        "permission",
        "member",
        "role",
        "tag",
        "attribute",
    )
    haystack = " ".join((normalized_sql, entity_name.lower(), operation_name.lower()))
    return any(token in haystack for token in collection_tokens)


def _formula_link_verification_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    db_verification_index: int,
    entity_name: str,
    operation_name: str,
    sql: str,
    expected_outcomes: Any,
) -> list[GenerationDiagnostic]:
    if not isinstance(expected_outcomes, list):
        return []
    normalized_sql = " ".join(sql.lower().split())
    is_formula_link_check = (
        "pricelisttemplateitemformulavariable" in normalized_sql
        or "formula_link" in entity_name.lower()
        or "formula_link" in operation_name.lower()
    )
    if not is_formula_link_check:
        return []
    normalized_outcomes = [str(outcome or "").strip().lower() for outcome in expected_outcomes]
    if "one row exists" not in normalized_outcomes:
        return []
    filters_specific_variable = any(
        token in normalized_sql
        for token in (
            "variable_id =",
            "variable_id=",
            ".code =",
            ".code=",
            " code =",
            " code=",
        )
    )
    if filters_specific_variable:
        return []
    return [
        _diagnostic(
            code="adapter_operation_inventory_formula_link_verification_not_case_specific",
            message=(
                "Formula-link DB verification uses 'one row exists' while its SQL can return one row per formula "
                "variable. Filter by an expected variable or use formula-specific/parameterized checks so the "
                "expected link set matches the authored quantity_formula."
            ),
            path=path,
            details={
                "db_verification_index": db_verification_index,
                "entity": entity_name,
                "operation": operation_name,
                "expected_outcomes": item.get("expected_outcomes"),
            },
        )
    ]


def _normalized_scoped_by_fields(value: Any) -> list[str]:
    if isinstance(value, list):
        return [field_name for item in value if (field_name := str(item or "").strip())]
    field_name = str(value or "").strip()
    return [field_name] if field_name else []
