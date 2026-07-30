"""Helpers for adapting scenario SQL params to psycopg placeholders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.common.errors import ValidationError


@dataclass(slots=True)
class PreparedSql:
    sql: str
    params: dict[str, Any] | list[Any]
    placeholder_names: list[str] = field(default_factory=list)


class NamedSqlParamConverter:
    """Converts readable :named params into psycopg-compatible placeholders.

    Psycopg treats every percent sign as parameter syntax whenever params are
    supplied, even when the percent appears inside a SQL string literal. Source
    SQL remains standard SQL; this adapter escapes its literal percent signs
    while preserving the placeholders it inserts.
    """

    def prepare(self, sql: str, params: dict[str, Any] | list[Any]) -> PreparedSql:
        converted_sql, placeholder_names = self._convert_placeholders(sql)
        if not placeholder_names:
            return PreparedSql(sql=sql, params=params)

        if not isinstance(params, dict):
            raise ValidationError("SQL with :named_param placeholders requires params to be an object")

        missing_names = sorted({name for name in placeholder_names if name not in params})
        if missing_names:
            raise ValidationError(
                "Missing SQL params for named placeholders: " + ", ".join(missing_names)
            )

        return PreparedSql(
            sql=converted_sql,
            params=params,
            placeholder_names=placeholder_names,
        )

    def _convert_placeholders(self, sql: str) -> tuple[str, list[str]]:
        parts: list[str] = []
        placeholder_names: list[str] = []
        index = 0
        length = len(sql)

        while index < length:
            if sql.startswith("--", index):
                newline_index = sql.find("\n", index)
                if newline_index == -1:
                    parts.append(self._escape_literal_percents(sql[index:]))
                    break
                parts.append(self._escape_literal_percents(sql[index:newline_index + 1]))
                index = newline_index + 1
                continue

            if sql.startswith("/*", index):
                closing_index = sql.find("*/", index + 2)
                if closing_index == -1:
                    parts.append(self._escape_literal_percents(sql[index:]))
                    break
                parts.append(self._escape_literal_percents(sql[index:closing_index + 2]))
                index = closing_index + 2
                continue

            current_char = sql[index]

            if current_char == "'":
                quoted_text, index = self._consume_quoted(sql, index, "'")
                parts.append(self._escape_literal_percents(quoted_text))
                continue

            if current_char == '"':
                quoted_identifier, index = self._consume_quoted(sql, index, '"')
                parts.append(self._escape_literal_percents(quoted_identifier))
                continue

            if sql.startswith("::", index):
                parts.append("::")
                index += 2
                continue

            if current_char == ":":
                placeholder_name, next_index = self._consume_placeholder_name(sql, index + 1)
                if placeholder_name:
                    placeholder_names.append(placeholder_name)
                    parts.append(f"%({placeholder_name})s")
                    index = next_index
                    continue

            parts.append(self._escape_literal_percents(current_char))
            index += 1

        return "".join(parts), placeholder_names

    @staticmethod
    def _escape_literal_percents(value: str) -> str:
        return value.replace("%", "%%")

    @staticmethod
    def _consume_quoted(sql: str, start_index: int, quote_char: str) -> tuple[str, int]:
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

        return sql[start_index:index], index

    @staticmethod
    def _consume_placeholder_name(sql: str, start_index: int) -> tuple[str, int]:
        if start_index >= len(sql):
            return "", start_index

        first_char = sql[start_index]
        if not (first_char == "_" or first_char.isalpha()):
            return "", start_index

        index = start_index + 1
        while index < len(sql):
            current_char = sql[index]
            if current_char == "_" or current_char.isalnum():
                index += 1
                continue
            break

        return sql[start_index:index], index
