"""API request models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from tools.common.errors import ValidationError


class AuthType(StrEnum):
    NONE = "none"
    BEARER = "bearer"
    BASIC = "basic"


@dataclass(slots=True)
class EnvConfig:
    api_base_url: str
    auth_type: AuthType = AuthType.NONE
    api_bearer_token: str | None = None
    api_username: str | None = None
    api_password: str | None = None
    api_base_url_key: str = "API_BASE_URL"
    api_base_url_raw: str | None = None

    @classmethod
    def from_mapping(cls, values: dict[str, str | None]) -> "EnvConfig":
        raw_auth_type = _normalize_env_value(values.get("API_AUTH_TYPE")) or "none"
        raw_auth_type = raw_auth_type.lower()

        try:
            auth_type = AuthType(raw_auth_type)
        except ValueError as exc:
            raise ValidationError(
                f"Unsupported API_AUTH_TYPE '{raw_auth_type}'. Expected one of: none, bearer, basic"
            ) from exc

        return cls(
            api_base_url=_normalize_env_value(values.get("API_BASE_URL")) or "",
            auth_type=auth_type,
            api_bearer_token=_normalize_env_value(values.get("API_BEARER_TOKEN")),
            api_username=_first_present(values, "API_USERNAME", "API_BASIC_USERNAME", "BASIC_AUTH_USERNAME"),
            api_password=_first_present(values, "API_PASSWORD", "API_BASIC_PASSWORD", "BASIC_AUTH_PASSWORD"),
            api_base_url_key="API_BASE_URL",
            api_base_url_raw=values.get("__RAW_API_BASE_URL") or values.get("API_BASE_URL"),
        )

    def is_ready(self) -> bool:
        return bool(self.api_base_url)


def _first_present(values: dict[str, str | None], *keys: str) -> str | None:
    for key in keys:
        value = _normalize_env_value(values.get(key))
        if value:
            return value
    return None


def _normalize_env_value(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        normalized = normalized[1:-1].strip()
    return normalized or None


@dataclass(slots=True)
class RequestStep:
    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    query_params: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 30

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "RequestStep":
        method = str(payload.get("method", "")).strip().upper()
        path = str(payload.get("path", "")).strip()

        if not method:
            raise ValidationError("Step must include method")
        if not path:
            raise ValidationError("Step must include path")

        headers_raw = payload.get("headers") or {}
        if not isinstance(headers_raw, dict):
            raise ValidationError("Step field 'headers' must be an object")

        query_params_raw = payload.get("query_params") or {}
        if not isinstance(query_params_raw, dict):
            raise ValidationError("Step field 'query_params' must be an object")

        timeout_raw = payload.get("timeout_seconds", 30)
        try:
            timeout_seconds = int(timeout_raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Step field 'timeout_seconds' must be an integer") from exc

        if timeout_seconds <= 0:
            raise ValidationError("Step field 'timeout_seconds' must be greater than 0")

        return cls(
            method=method,
            path=path,
            headers={str(key): str(value) for key, value in headers_raw.items()},
            body=payload.get("body"),
            query_params=query_params_raw,
            timeout_seconds=timeout_seconds,
        )


@dataclass(slots=True)
class ResponseData:
    http_status: int
    headers: dict[str, str]
    body: Any


@dataclass(slots=True)
class PreparedRequest:
    url: str
    headers: dict[str, str]
    base_url: str = ""
    base_url_raw: str | None = None
    path: str = ""
    base_url_key: str = "API_BASE_URL"
    auth: Any = None
    json_body: Any = None
    query_params: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 30
    request_debug: dict[str, Any] = field(default_factory=dict)
