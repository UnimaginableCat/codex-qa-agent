"""Database query models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from tools.common.errors import ValidationError


@dataclass(slots=True)
class DbEnvConfig:
    database_url: str
    database_user: str = ""
    database_password: str = ""

    @classmethod
    def from_mapping(cls, values: dict[str, str | None]) -> "DbEnvConfig":
        return cls(
            database_url=(values.get("DATABASE_URL") or "").strip(),
            database_user=cls._first_defined(
                values,
                "DATABASE_USER",
                "DB_USER",
                "PGUSER",
                "POSTGRES_USER",
            ),
            database_password=cls._first_defined(
                values,
                "DATABASE_PASSWORD",
                "DB_PASSWORD",
                "PGPASSWORD",
                "POSTGRES_PASSWORD",
            ),
        )

    def is_ready(self) -> bool:
        return bool(self.database_url) and (
            self.has_inline_credentials()
            or bool(self.database_user and self.database_password)
        )

    def has_inline_credentials(self) -> bool:
        if not self.database_url:
            return False

        parsed = urlparse(self.database_url)
        return bool(parsed.username and parsed.password)

    def connection_kwargs(self) -> dict[str, str]:
        kwargs: dict[str, str] = {}
        if self.database_user:
            kwargs["user"] = self.database_user
        if self.database_password:
            kwargs["password"] = self.database_password
        return kwargs

    @staticmethod
    def _first_defined(values: dict[str, str | None], *keys: str) -> str:
        for key in keys:
            value = (values.get(key) or "").strip()
            if value:
                return value
        return ""


@dataclass(slots=True)
class QueryStep:
    sql: str
    params: dict[str, Any] | list[Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "QueryStep":
        sql = str(payload.get("sql", "")).strip()
        if not sql:
            raise ValidationError("Step must include sql")

        params = payload.get("params")
        if params is None:
            normalized_params: dict[str, Any] | list[Any] = {}
        elif isinstance(params, dict):
            normalized_params = params
        elif isinstance(params, list):
            normalized_params = params
        else:
            raise ValidationError("Step field 'params' must be an object or an array")

        return cls(sql=sql, params=normalized_params)


@dataclass(slots=True)
class QueryData:
    row_count: int
    rows: list[dict[str, Any]]
