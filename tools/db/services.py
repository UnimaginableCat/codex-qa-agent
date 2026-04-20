"""Services for DB query validation and execution."""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from tools.common import ExecutionResult, JsonFileLoadError, StepStatus, ValidationError
from tools.common.errors import EnvFileLoadError

from .errors import SqlSafetyError
from .loaders import DbEnvLoader, QueryStepLoader
from .models import DbEnvConfig, QueryData, QueryStep
from .sql_params import NamedSqlParamConverter
from .validators import ReadOnlySqlValidator, SqlNormalizer


class DatabaseQueryService:
    """Executes read-only database queries."""

    def __init__(self, sql_param_converter: NamedSqlParamConverter) -> None:
        self._sql_param_converter = sql_param_converter

    def execute(self, env: DbEnvConfig, step: QueryStep) -> ExecutionResult:
        if not env.is_ready():
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=(
                    "Missing DB connection settings. Provide DATABASE_URL with embedded "
                    "credentials, or set DATABASE_URL with DATABASE_USER and DATABASE_PASSWORD."
                ),
                details={"sql": step.sql},
            )

        try:
            prepared_sql = self._sql_param_converter.prepare(step.sql, step.params)
        except ValidationError as exc:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=str(exc),
                details={"sql": step.sql},
            )

        try:
            with psycopg.connect(
                env.database_url,
                row_factory=dict_row,
                **env.connection_kwargs(),
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(prepared_sql.sql, prepared_sql.params)
                    rows = list(cursor.fetchall())

            return ExecutionResult(
                status=StepStatus.PASS,
                message="Query executed successfully",
                details={
                    "sql": step.sql,
                    "executed_sql": prepared_sql.sql,
                    "query": QueryData(row_count=len(rows), rows=rows),
                },
            )
        except psycopg.Error as exc:
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Database error: {exc}",
                details={
                    "sql": step.sql,
                    "executed_sql": prepared_sql.sql,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Runtime error: {exc}",
                details={
                    "sql": step.sql,
                    "executed_sql": prepared_sql.sql,
                },
            )


class DatabaseQueryRunner:
    """Coordinates env loading, step loading, SQL validation, and execution."""

    def __init__(
        self,
        env_loader: DbEnvLoader,
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
        except (EnvFileLoadError, JsonFileLoadError) as exc:
            return ExecutionResult(status=StepStatus.ERROR, message=str(exc))
        except ValidationError as exc:
            return ExecutionResult(status=StepStatus.BLOCKED, message=str(exc))

        try:
            self._sql_validator.validate(step.sql)
        except SqlSafetyError as exc:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=str(exc),
                details={"sql": step.sql},
            )
        except ValidationError as exc:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=str(exc),
                details={"sql": step.sql},
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Failed to validate SQL: {exc}",
                details={"sql": step.sql},
            )

        return self._query_service.execute(env, step)


def build_runner() -> DatabaseQueryRunner:
    return DatabaseQueryRunner(
        env_loader=DbEnvLoader(),
        step_loader=QueryStepLoader(),
        sql_validator=ReadOnlySqlValidator(normalizer=SqlNormalizer()),
        query_service=DatabaseQueryService(sql_param_converter=NamedSqlParamConverter()),
    )
