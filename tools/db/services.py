"""Services for DB query validation and execution."""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from tools.common import ExecutionResult, JsonFileLoadError, StepStatus, ValidationError
from tools.common.errors import EnvFileLoadError
from tools.common.runtime_signals import (
    ContinuationHint,
    NormalizedRuntimeSignal,
    RetryHint,
    RuntimeFailureCategory,
    RuntimeSignalSource,
    RuntimeSignalTag,
    ToolFailureCode,
)

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
                details={
                    "sql": step.sql,
                    "actor": env.actor,
                    "database_url_key": env.database_url_key,
                    "runtime_signal": _db_connection_configuration_signal().to_dict(),
                },
            )

        try:
            prepared_sql = self._sql_param_converter.prepare(step.sql, step.params)
        except ValidationError as exc:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=str(exc),
                details={
                    "sql": step.sql,
                    "actor": env.actor,
                    "database_url_key": env.database_url_key,
                    "runtime_signal": _db_connection_configuration_signal().to_dict(),
                },
            )

        try:
            with psycopg.connect(
                env.database_url,
                row_factory=dict_row,
                **env.connection_kwargs(),
            ) as connection:
                with connection.cursor() as cursor:
                    if prepared_sql.params:
                        cursor.execute(prepared_sql.sql, prepared_sql.params)
                    else:
                        cursor.execute(prepared_sql.sql)
                    rows = list(cursor.fetchall())

            return ExecutionResult(
                status=StepStatus.PASS,
                message="Query executed successfully",
                details={
                    "sql": step.sql,
                    "executed_sql": prepared_sql.sql,
                    "actor": env.actor,
                    "database_url_key": env.database_url_key,
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
                    "actor": env.actor,
                    "database_url_key": env.database_url_key,
                    "runtime_signal": _db_connection_failure_signal().to_dict(),
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Runtime error: {exc}",
                details={
                    "sql": step.sql,
                    "executed_sql": prepared_sql.sql,
                    "actor": env.actor,
                    "database_url_key": env.database_url_key,
                    "runtime_signal": _runtime_tool_failure_signal().to_dict(),
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
            step = self._step_loader.load(step_file)
            env = self._env_loader.load(env_file, actor=step.actor)
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
                details={
                    "sql": step.sql,
                    "runtime_signal": _db_read_only_guard_signal().to_dict(),
                },
            )
        except ValidationError as exc:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=str(exc),
                details={
                    "sql": step.sql,
                    "runtime_signal": _db_connection_configuration_signal().to_dict(),
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Failed to validate SQL: {exc}",
                details={
                    "sql": step.sql,
                    "runtime_signal": _runtime_tool_failure_signal().to_dict(),
                },
            )

        return self._query_service.execute(env, step)


def build_runner() -> DatabaseQueryRunner:
    return DatabaseQueryRunner(
        env_loader=DbEnvLoader(),
        step_loader=QueryStepLoader(),
        sql_validator=ReadOnlySqlValidator(normalizer=SqlNormalizer()),
        query_service=DatabaseQueryService(sql_param_converter=NamedSqlParamConverter()),
    )


def _db_connection_configuration_signal() -> NormalizedRuntimeSignal:
    return NormalizedRuntimeSignal(
        source=RuntimeSignalSource.TOOL,
        code=ToolFailureCode.DB_CONNECTION_CONFIGURATION_MISSING,
        category=RuntimeFailureCategory.CONFIGURATION,
        retry_hint=RetryHint.AFTER_OPERATOR_FIX,
        continuation_hint=ContinuationHint.STOP_AND_FIX,
        tags=(RuntimeSignalTag.ENVIRONMENT_BLOCKED, RuntimeSignalTag.USER_FIXABLE),
        operator_fixable=True,
    )


def _db_connection_failure_signal() -> NormalizedRuntimeSignal:
    return NormalizedRuntimeSignal(
        source=RuntimeSignalSource.TOOL,
        code=ToolFailureCode.DB_CONNECTION_FAILED,
        category=RuntimeFailureCategory.DATABASE,
        retry_hint=RetryHint.MANUAL_RETRY,
        continuation_hint=ContinuationHint.RETRY_MANUALLY,
        tags=(
            RuntimeSignalTag.RETRYABLE,
            RuntimeSignalTag.ENVIRONMENT_BLOCKED,
            RuntimeSignalTag.USER_FIXABLE,
        ),
        resumable=True,
        operator_fixable=True,
    )


def _db_read_only_guard_signal() -> NormalizedRuntimeSignal:
    return NormalizedRuntimeSignal(
        source=RuntimeSignalSource.TOOL,
        code=ToolFailureCode.DB_READ_ONLY_GUARD_VIOLATION,
        category=RuntimeFailureCategory.READ_ONLY_GUARD,
        continuation_hint=ContinuationHint.STOP_AND_FIX,
        tags=(RuntimeSignalTag.USER_FIXABLE,),
        operator_fixable=True,
    )


def _runtime_tool_failure_signal() -> NormalizedRuntimeSignal:
    return NormalizedRuntimeSignal(
        source=RuntimeSignalSource.TOOL,
        code=ToolFailureCode.RUNTIME_TOOL_FAILURE,
        category=RuntimeFailureCategory.TOOL_RUNTIME,
        retry_hint=RetryHint.MANUAL_RETRY,
        continuation_hint=ContinuationHint.RETRY_MANUALLY,
        tags=(RuntimeSignalTag.RETRYABLE,),
        resumable=True,
    )
