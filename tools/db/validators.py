"""Validation utilities for DB tooling."""

from __future__ import annotations

import re

from .errors import SqlSafetyError


class SqlNormalizer:
    """Removes non-code SQL regions before safety validation."""

    def normalize(self, sql: str) -> str:
        sanitized: list[str] = []
        index = 0
        sql_length = len(sql)

        while index < sql_length:
            char = sql[index]
            next_char = sql[index + 1] if index + 1 < sql_length else ""

            if char == "-" and next_char == "-":
                index = self._consume_line_comment(sql, index, sanitized)
                continue
            if char == "/" and next_char == "*":
                index = self._consume_block_comment(sql, index, sanitized)
                continue
            if char == "'":
                index = self._consume_single_quoted_string(sql, index, sanitized)
                continue
            if char == '"':
                index = self._consume_double_quoted_identifier(sql, index, sanitized)
                continue

            dollar_quote_delimiter = self._read_dollar_quote_delimiter(sql, index)
            if dollar_quote_delimiter is not None:
                index = self._consume_dollar_quoted_string(
                    sql,
                    index,
                    dollar_quote_delimiter,
                    sanitized,
                )
                continue

            sanitized.append(char)
            index += 1

        return "".join(sanitized).strip()

    @staticmethod
    def _consume_line_comment(sql: str, start: int, sanitized: list[str]) -> int:
        index = start
        sql_length = len(sql)

        while index < sql_length:
            char = sql[index]
            if char == "\n":
                sanitized.append(char)
                return index + 1
            sanitized.append(" ")
            index += 1

        return index

    @staticmethod
    def _consume_block_comment(sql: str, start: int, sanitized: list[str]) -> int:
        index = start
        sql_length = len(sql)
        depth = 0

        while index < sql_length:
            char = sql[index]
            next_char = sql[index + 1] if index + 1 < sql_length else ""
            if char == "/" and next_char == "*":
                sanitized.extend((" ", " "))
                depth += 1
                index += 2
                continue
            if char == "*" and next_char == "/":
                sanitized.extend((" ", " "))
                depth -= 1
                index += 2
                if depth == 0:
                    return index
                continue
            sanitized.append("\n" if char == "\n" else " ")
            index += 1

        return index

    @staticmethod
    def _consume_single_quoted_string(sql: str, start: int, sanitized: list[str]) -> int:
        sanitized.append(" ")
        index = start + 1
        sql_length = len(sql)

        while index < sql_length:
            char = sql[index]
            next_char = sql[index + 1] if index + 1 < sql_length else ""
            if char == "'" and next_char == "'":
                sanitized.extend((" ", " "))
                index += 2
                continue
            if char == "'":
                sanitized.append(" ")
                return index + 1
            sanitized.append("\n" if char == "\n" else " ")
            index += 1

        return index

    @staticmethod
    def _consume_double_quoted_identifier(sql: str, start: int, sanitized: list[str]) -> int:
        sanitized.append(" ")
        index = start + 1
        sql_length = len(sql)

        while index < sql_length:
            char = sql[index]
            next_char = sql[index + 1] if index + 1 < sql_length else ""
            if char == '"' and next_char == '"':
                sanitized.extend((" ", " "))
                index += 2
                continue
            if char == '"':
                sanitized.append(" ")
                return index + 1
            sanitized.append("\n" if char == "\n" else " ")
            index += 1

        return index

    @staticmethod
    def _read_dollar_quote_delimiter(sql: str, start: int) -> str | None:
        if sql[start] != "$":
            return None

        if start + 1 < len(sql) and sql[start + 1] == "$":
            return "$$"

        index = start + 1
        if index >= len(sql) or not (sql[index].isalpha() or sql[index] == "_"):
            return None

        index += 1
        while index < len(sql) and (sql[index].isalnum() or sql[index] == "_"):
            index += 1

        if index < len(sql) and sql[index] == "$":
            return sql[start : index + 1]

        return None

    @staticmethod
    def _consume_dollar_quoted_string(
        sql: str,
        start: int,
        delimiter: str,
        sanitized: list[str],
    ) -> int:
        index = start
        sql_length = len(sql)
        delimiter_length = len(delimiter)

        while index < sql_length:
            if sql.startswith(delimiter, index):
                sanitized.extend(" " for _ in range(delimiter_length))
                index += delimiter_length
                if index > start + delimiter_length:
                    return index
                continue

            char = sql[index]
            sanitized.append("\n" if char == "\n" else " ")
            index += 1

        return index


class ReadOnlySqlValidator:
    """Validates that SQL is read-only and safe for verification use."""

    _forbidden_tokens = {
        "INSERT",
        "UPDATE",
        "DELETE",
        "UPSERT",
        "MERGE",
        "ALTER",
        "DROP",
        "TRUNCATE",
        "CREATE",
        "GRANT",
        "REVOKE",
        "CALL",
        "EXEC",
        "EXECUTE",
        "DO",
        "COPY",
        "VACUUM",
        "ANALYZE",
        "REFRESH",
        "REINDEX",
        "LOCK",
    }

    def __init__(self, normalizer: SqlNormalizer) -> None:
        self._normalizer = normalizer

    def validate(self, sql: str) -> None:
        normalized = self._normalizer.normalize(sql)
        if not normalized:
            raise SqlSafetyError("SQL is empty after normalization")

        upper_sql = normalized.upper()

        if ";" in upper_sql.rstrip(";"):
            raise SqlSafetyError("Multiple SQL statements are not allowed")

        if not upper_sql.startswith("SELECT"):
            raise SqlSafetyError("Only SELECT queries are allowed")

        tokens = re.findall(r"\b[A-Z_]+\b", upper_sql)
        forbidden_found = sorted(
            token for token in set(tokens) if token in self._forbidden_tokens and token != "SELECT"
        )
        if forbidden_found:
            raise SqlSafetyError(
                f"Read-only policy violation. Forbidden SQL keywords found: {', '.join(forbidden_found)}"
            )
