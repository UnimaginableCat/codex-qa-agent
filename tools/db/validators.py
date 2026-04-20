"""Validation utilities for DB tooling."""

from __future__ import annotations

import re

from .errors import SqlSafetyError


class SqlNormalizer:
    """Normalizes SQL for safety validation."""

    _line_comment_pattern = re.compile(r"--.*?$", re.MULTILINE)
    _block_comment_pattern = re.compile(r"/\*.*?\*/", re.DOTALL)

    def normalize(self, sql: str) -> str:
        without_line_comments = self._line_comment_pattern.sub("", sql)
        without_block_comments = self._block_comment_pattern.sub("", without_line_comments)
        return without_block_comments.strip()


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
