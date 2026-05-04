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


SAFE_RETRY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEFAULT_RETRY_REASONS = ("read_timeout", "connect_timeout", "connection_error")
SUPPORTED_RETRY_REASONS = frozenset(DEFAULT_RETRY_REASONS)


@dataclass(slots=True)
class EnvConfig:
    api_base_url: str
    auth_type: AuthType = AuthType.NONE
    api_bearer_token: str | None = None
    api_username: str | None = None
    api_password: str | None = None
    actor: str | None = None
    api_base_url_key: str = "API_BASE_URL"
    api_base_url_raw: str | None = None

    @classmethod
    def from_mapping(
        cls,
        values: dict[str, str | None],
        *,
        actor: str | None = None,
        api_base_url_key: str = "API_BASE_URL",
    ) -> "EnvConfig":
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
            actor=_normalize_env_value(actor),
            api_base_url_key=api_base_url_key,
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
    actor: str | None = None
    timeout_seconds: int = 30
    retry_policy: "RequestRetryPolicy" = field(default_factory=lambda: RequestRetryPolicy(configured=False))

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
            actor=_normalize_env_value(payload.get("actor")),
            timeout_seconds=timeout_seconds,
            retry_policy=RequestRetryPolicy.from_mapping(payload.get("retry")),
        )


@dataclass(slots=True)
class RequestRetryPolicy:
    configured: bool = False
    enabled: bool | None = None
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    retry_on: tuple[str, ...] = DEFAULT_RETRY_REASONS
    retry_on_statuses: tuple[int, ...] = ()
    allow_retry_on_non_idempotent_methods: bool = False

    @classmethod
    def from_mapping(cls, payload: Any) -> "RequestRetryPolicy":
        if payload is None:
            return cls(configured=False)
        if not isinstance(payload, dict):
            raise ValidationError("Step field 'retry' must be an object")

        enabled = _optional_bool(payload.get("enabled"), "retry.enabled")
        max_attempts = _positive_int(payload.get("max_attempts", 3), "retry.max_attempts")
        backoff_seconds = _non_negative_float(payload.get("backoff_seconds", 1.0), "retry.backoff_seconds")
        backoff_multiplier = _positive_float(payload.get("backoff_multiplier", 2.0), "retry.backoff_multiplier")
        allow_non_idempotent = _bool_value(
            payload.get("allow_retry_on_non_idempotent_methods", False),
            "retry.allow_retry_on_non_idempotent_methods",
        )

        retry_on_raw = payload.get("retry_on", list(DEFAULT_RETRY_REASONS))
        retry_on = _string_tuple(retry_on_raw, "retry.retry_on")
        unsupported_reasons = [reason for reason in retry_on if reason not in SUPPORTED_RETRY_REASONS]
        if unsupported_reasons:
            raise ValidationError(
                "Step field 'retry.retry_on' contains unsupported value(s): "
                + ", ".join(sorted(unsupported_reasons))
            )

        retry_statuses = _status_tuple(payload.get("retry_on_statuses", []), "retry.retry_on_statuses")

        return cls(
            configured=True,
            enabled=enabled,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            backoff_multiplier=backoff_multiplier,
            retry_on=retry_on,
            retry_on_statuses=retry_statuses,
            allow_retry_on_non_idempotent_methods=allow_non_idempotent,
        )

    def is_enabled_for_method(self, method: str) -> bool:
        normalized_method = method.upper()
        if self.enabled is False:
            return False
        if normalized_method in SAFE_RETRY_METHODS:
            return True if self.enabled is None else self.enabled
        if self.enabled is True:
            return True
        return self.allow_retry_on_non_idempotent_methods

    def source_for_method(self, method: str) -> str:
        if not self.configured and method.upper() in SAFE_RETRY_METHODS:
            return "default_safe_method"
        if self.configured:
            return "step_retry_config"
        return "disabled_non_idempotent_method"


@dataclass(slots=True)
class ResponseData:
    http_status: int
    headers: dict[str, str]
    body: Any
    content_length_bytes: int | None = None
    body_content_type: str | None = None
    body_is_binary: bool = False


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


def _optional_bool(value: Any, field_name: str) -> bool | None:
    if value is None:
        return None
    return _bool_value(value, field_name)


def _bool_value(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    raise ValidationError(f"Step field '{field_name}' must be a boolean")


def _positive_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Step field '{field_name}' must be an integer") from exc
    if parsed <= 0:
        raise ValidationError(f"Step field '{field_name}' must be greater than 0")
    return parsed


def _non_negative_float(value: Any, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Step field '{field_name}' must be a number") from exc
    if parsed < 0:
        raise ValidationError(f"Step field '{field_name}' must be greater than or equal to 0")
    return parsed


def _positive_float(value: Any, field_name: str) -> float:
    parsed = _non_negative_float(value, field_name)
    if parsed <= 0:
        raise ValidationError(f"Step field '{field_name}' must be greater than 0")
    return parsed


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValidationError(f"Step field '{field_name}' must be an array")
    return tuple(str(item).strip().lower() for item in value if str(item).strip())


def _status_tuple(value: Any, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ValidationError(f"Step field '{field_name}' must be an array")
    statuses: list[int] = []
    for item in value:
        status = _positive_int(item, field_name)
        if status < 100 or status > 599:
            raise ValidationError(f"Step field '{field_name}' must contain HTTP status codes")
        statuses.append(status)
    return tuple(statuses)
