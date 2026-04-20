#!/usr/bin/env python3
"""Run a read-only database query step and print a structured JSON result."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import psycopg
from dotenv import dotenv_values
from psycopg.rows import dict_row


class StepStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class DbRunnerError(Exception):
    """Base exception for DB runner errors."""


class EnvFileLoadError(DbRunnerError):
    """Raised when env file cannot be loaded."""


class StepFileLoadError(DbRunnerError):
    """Raised when step file cannot be loaded."""


class StepValidationError(DbRunnerError):
    """Raised when DB step content is invalid."""


class SqlSafetyError(DbRunnerError):
    """Raised when SQL is not allowed for read-only execution."""


@dataclass(slots=True)
class DbEnvConfig:
    database_url: str

    @classmethod
    def from_mapping(cls, values: dict[str, str | None]) -> "DbEnvConfig":
        return cls(
            database_url=(values.get("DATABASE_URL") or "").strip(),
        )

    def is_ready(self) -> bool:
        return bool(self.database_url)


@dataclass(slots=True)
class QueryStep:
    sql: str
    params: dict[str, Any] | list[Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "QueryStep":
        sql = str(payload.get("sql", "")).strip()
        if not sql:
            raise StepValidationError("Step must include sql")

        params = payload.get("params")
        if params is None:
            normalized_params: dict[str, Any] | list[Any] = {}
        elif isinstance(params, dict):
            normalized_params = params
        elif isinstance(params, list):
            normalized_params = params
        else:
            raise StepValidationError("Step field 'params' must be an object or an array")

        return cls(sql=sql, params=normalized_params)


@dataclass(slots=True)
class QueryData:
    row_count: int
    rows: list[dict[str, Any]]


@dataclass(slots=True)
class ExecutionResult:
    status: StepStatus
    message: str
    sql: str | None = None
    query: QueryData | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status.value,
            "message": self.message,
        }

        if self.sql is not None:
            result["sql"] = self.sql

        if self.query is not None:
            result["query"] = asdict(self.query)

        return result


class EnvFileLoader:
    """Loads database environment configuration using python-dotenv."""

    def load(self, env_path: Path) -> DbEnvConfig:
        if not env_path.exists():
            raise EnvFileLoadError(f"Env file does not exist: {env_path}")

        try:
            values = dotenv_values(env_path)
        except Exception as exc:  # noqa: BLE001
            raise EnvFileLoadError(f"Failed to load env file '{env_path}': {exc}") from exc

        normalized_values: dict[str, str | None] = {
            str(key): value for key, value in values.items()
        }
        return DbEnvConfig.from_mapping(normalized_values)


class QueryStepLoader:
    """Loads and validates a DB query step definition from JSON."""

    def load(self, step_path: Path) -> QueryStep:
        if not step_path.exists():
            raise StepFileLoadError(f"Step file does not exist: {step_path}")

        try:
            payload = json.loads(step_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise StepFileLoadError(f"Failed to parse step file '{step_path}': {exc}") from exc

        if not isinstance(payload, dict):
            raise StepValidationError("Step JSON must be an object")

        return QueryStep.from_mapping(payload)


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
        forbidden_found = sorted(token for token in set(tokens) if token in self._forbidden_tokens and token != "SELECT")
        if forbidden_found:
            raise SqlSafetyError(
                f"Read-only policy violation. Forbidden SQL keywords found: {', '.join(forbidden_found)}"
            )


class DatabaseQueryService:
    """Executes read-only database queries."""

    def execute(self, env: DbEnvConfig, step: QueryStep) -> ExecutionResult:
        if not env.is_ready():
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message="Missing DATABASE_URL",
                sql=step.sql,
            )

        try:
            with psycopg.connect(env.database_url, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(step.sql, step.params)
                    rows = list(cursor.fetchall())

            return ExecutionResult(
                status=StepStatus.PASS,
                message="Query executed successfully",
                sql=step.sql,
                query=QueryData(
                    row_count=len(rows),
                    rows=rows,
                ),
            )
        except psycopg.Error as exc:
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Database error: {exc}",
                sql=step.sql,
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Runtime error: {exc}",
                sql=step.sql,
            )


class DatabaseQueryRunner:
    """Application service coordinating env loading, step loading, validation, and execution."""

    def __init__(
        self,
        env_loader: EnvFileLoader,
        step_loader: QueryStepLoader,
        sql_validator: ReadOnlySqlValidator,
        query_service: DatabaseQueryService,
    ) -> None:
        self._env_loader = env_loader
        self._step_loader = step_loader
        self._sql_validator = sql_validator
        self._query_service = query_service

    def run(self, env_file: Path, step_file: Path) -> ExecutionResult:
        try:
            env = self._env_loader.load(env_file)
            step = self._step_loader.load(step_file)
        except EnvFileLoadError as exc:
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=str(exc),
            )
        except StepFileLoadError as exc:
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=str(exc),
            )
        except StepValidationError as exc:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=str(exc),
            )

        try:
            self._sql_validator.validate(step.sql)
        except SqlSafetyError as exc:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=str(exc),
                sql=step.sql,
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Failed to validate SQL: {exc}",
                sql=step.sql,
            )

        return self._query_service.execute(env, step)


def build_runner() -> DatabaseQueryRunner:
    return DatabaseQueryRunner(
        env_loader=EnvFileLoader(),
        step_loader=QueryStepLoader(),
        sql_validator=ReadOnlySqlValidator(normalizer=SqlNormalizer()),
        query_service=DatabaseQueryService(),
    )


def main() -> int:
    if len(sys.argv) != 3:
        result = ExecutionResult(
            status=StepStatus.ERROR,
            message="Usage: python tools/db/query_check.py <env_file> <step_json>",
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False))
        return 1

    env_file = Path(sys.argv[1])
    step_file = Path(sys.argv[2])

    runner = build_runner()
    result = runner.run(env_file=env_file, step_file=step_file)

    print(json.dumps(result.to_dict(), ensure_ascii=False))

    if result.status == StepStatus.ERROR:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())