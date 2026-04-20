"""Database query models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.common.errors import ValidationError


@dataclass(slots=True)
class DbEnvConfig:
    database_url: str

    @classmethod
    def from_mapping(cls, values: dict[str, str | None]) -> "DbEnvConfig":
        return cls(database_url=(values.get("DATABASE_URL") or "").strip())

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
