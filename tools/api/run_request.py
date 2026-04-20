#!/usr/bin/env python3
"""Run an API request step and print a structured JSON result."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import requests
from dotenv import dotenv_values
from requests.auth import HTTPBasicAuth


class StepStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class AuthType(StrEnum):
    NONE = "none"
    BEARER = "bearer"
    BASIC = "basic"


class ApiRunnerError(Exception):
    """Base exception for API runner errors."""


class EnvFileLoadError(ApiRunnerError):
    """Raised when env file cannot be loaded."""


class StepFileLoadError(ApiRunnerError):
    """Raised when step file cannot be loaded."""


class StepValidationError(ApiRunnerError):
    """Raised when step content is invalid."""


class AuthConfigurationError(ApiRunnerError):
    """Raised when auth config is missing or invalid."""


@dataclass(slots=True)
class EnvConfig:
    api_base_url: str
    auth_type: AuthType = AuthType.NONE
    api_bearer_token: str | None = None
    api_username: str | None = None
    api_password: str | None = None

    @classmethod
    def from_mapping(cls, values: dict[str, str | None]) -> "EnvConfig":
        raw_auth_type = (values.get("API_AUTH_TYPE") or "none").strip().lower()

        try:
            auth_type = AuthType(raw_auth_type)
        except ValueError as exc:
            raise EnvFileLoadError(
                f"Unsupported API_AUTH_TYPE '{raw_auth_type}'. "
                f"Expected one of: none, bearer, basic"
            ) from exc

        return cls(
            api_base_url=(values.get("API_BASE_URL") or "").strip(),
            auth_type=auth_type,
            api_bearer_token=(values.get("API_BEARER_TOKEN") or "").strip() or None,
            api_username=(values.get("API_USERNAME") or "").strip() or None,
            api_password=(values.get("API_PASSWORD") or "").strip() or None,
        )

    def is_ready(self) -> bool:
        return bool(self.api_base_url)


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
            raise StepValidationError("Step must include method")
        if not path:
            raise StepValidationError("Step must include path")

        headers_raw = payload.get("headers") or {}
        if not isinstance(headers_raw, dict):
            raise StepValidationError("Step field 'headers' must be an object")

        query_params_raw = payload.get("query_params") or {}
        if not isinstance(query_params_raw, dict):
            raise StepValidationError("Step field 'query_params' must be an object")

        timeout_raw = payload.get("timeout_seconds", 30)
        try:
            timeout_seconds = int(timeout_raw)
        except (TypeError, ValueError) as exc:
            raise StepValidationError("Step field 'timeout_seconds' must be an integer") from exc

        if timeout_seconds <= 0:
            raise StepValidationError("Step field 'timeout_seconds' must be greater than 0")

        return cls(
            method=method,
            path=path,
            headers={str(k): str(v) for k, v in headers_raw.items()},
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
class ExecutionResult:
    status: StepStatus
    message: str
    method: str | None = None
    url: str | None = None
    response: ResponseData | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status.value,
            "message": self.message,
        }

        if self.method is not None:
            result["method"] = self.method

        if self.url is not None:
            result["url"] = self.url

        if self.response is not None:
            result["response"] = asdict(self.response)

        return result


@dataclass(slots=True)
class PreparedRequest:
    url: str
    headers: dict[str, str]
    auth: Any = None
    json_body: Any = None
    query_params: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 30


class EnvFileLoader:
    """Loads environment configuration using python-dotenv."""

    def load(self, env_path: Path) -> EnvConfig:
        if not env_path.exists():
            raise EnvFileLoadError(f"Env file does not exist: {env_path}")

        try:
            values = dotenv_values(env_path)
        except Exception as exc:  # noqa: BLE001
            raise EnvFileLoadError(f"Failed to load env file '{env_path}': {exc}") from exc

        normalized_values: dict[str, str | None] = {
            str(key): value for key, value in values.items()
        }
        return EnvConfig.from_mapping(normalized_values)


class RequestStepLoader:
    """Loads and validates a request step definition from JSON."""

    def load(self, step_path: Path) -> RequestStep:
        if not step_path.exists():
            raise StepFileLoadError(f"Step file does not exist: {step_path}")

        try:
            payload = json.loads(step_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise StepFileLoadError(f"Failed to parse step file '{step_path}': {exc}") from exc

        if not isinstance(payload, dict):
            raise StepValidationError("Step JSON must be an object")

        return RequestStep.from_mapping(payload)


class UrlBuilder:
    """Builds a final request URL from base URL and step path."""

    @staticmethod
    def build(base_url: str, path: str) -> str:
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


class AuthStrategy(Protocol):
    """Applies auth configuration to a prepared request."""

    def apply(self, env: EnvConfig, prepared_request: PreparedRequest) -> None:
        ...


class NoAuthStrategy:
    def apply(self, env: EnvConfig, prepared_request: PreparedRequest) -> None:
        return


class BearerTokenAuthStrategy:
    def apply(self, env: EnvConfig, prepared_request: PreparedRequest) -> None:
        if not env.api_bearer_token:
            raise AuthConfigurationError("API_AUTH_TYPE=bearer but API_BEARER_TOKEN is missing")

        prepared_request.headers.setdefault("Authorization", f"Bearer {env.api_bearer_token}")


class BasicAuthStrategy:
    def apply(self, env: EnvConfig, prepared_request: PreparedRequest) -> None:
        if not env.api_username:
            raise AuthConfigurationError("API_AUTH_TYPE=basic but API_USERNAME is missing")
        if env.api_password is None:
            raise AuthConfigurationError("API_AUTH_TYPE=basic but API_PASSWORD is missing")

        prepared_request.auth = HTTPBasicAuth(env.api_username, env.api_password)


class AuthStrategyFactory:
    """Builds auth strategies from environment configuration."""

    @staticmethod
    def create(env: EnvConfig) -> AuthStrategy:
        if env.auth_type == AuthType.NONE:
            return NoAuthStrategy()
        if env.auth_type == AuthType.BEARER:
            return BearerTokenAuthStrategy()
        if env.auth_type == AuthType.BASIC:
            return BasicAuthStrategy()

        raise AuthConfigurationError(f"Unsupported auth type: {env.auth_type}")


class ApiRequestBuilder:
    """Builds a prepared request from environment and step definition."""

    def __init__(self, auth_strategy_factory: AuthStrategyFactory) -> None:
        self._auth_strategy_factory = auth_strategy_factory

    def build(self, env: EnvConfig, step: RequestStep) -> PreparedRequest:
        if not env.is_ready():
            raise AuthConfigurationError("Missing API_BASE_URL")

        prepared_request = PreparedRequest(
            url=UrlBuilder.build(env.api_base_url, step.path),
            headers=dict(step.headers),
            json_body=step.body,
            query_params=step.query_params,
            timeout_seconds=step.timeout_seconds,
        )

        auth_strategy = self._auth_strategy_factory.create(env)
        auth_strategy.apply(env, prepared_request)

        return prepared_request


class ApiRequestService:
    """Executes HTTP requests for scenario API steps."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def execute(self, step: RequestStep, prepared_request: PreparedRequest) -> ExecutionResult:
        request_kwargs: dict[str, Any] = {
            "headers": prepared_request.headers,
            "params": prepared_request.query_params,
            "timeout": prepared_request.timeout_seconds,
        }

        if prepared_request.auth is not None:
            request_kwargs["auth"] = prepared_request.auth

        if prepared_request.json_body is not None:
            request_kwargs["json"] = prepared_request.json_body

        try:
            response = self._session.request(step.method, prepared_request.url, **request_kwargs)
        except requests.RequestException as exc:
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Request failed: {exc}",
                method=step.method,
                url=prepared_request.url,
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Runtime error: {exc}",
                method=step.method,
                url=prepared_request.url,
            )

        response_data = ResponseData(
            http_status=response.status_code,
            headers=dict(response.headers),
            body=self._parse_response_body(response),
        )

        return ExecutionResult(
            status=StepStatus.PASS,
            message="Request executed successfully",
            method=step.method,
            url=prepared_request.url,
            response=response_data,
        )

    @staticmethod
    def _parse_response_body(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text


class ApiRequestRunner:
    """Application service coordinating config loading, request preparation, and execution."""

    def __init__(
        self,
        env_loader: EnvFileLoader,
        step_loader: RequestStepLoader,
        request_builder: ApiRequestBuilder,
        request_service: ApiRequestService,
    ) -> None:
        self._env_loader = env_loader
        self._step_loader = step_loader
        self._request_builder = request_builder
        self._request_service = request_service

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
            prepared_request = self._request_builder.build(env, step)
        except AuthConfigurationError as exc:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=str(exc),
                method=step.method,
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Failed to prepare request: {exc}",
                method=step.method,
            )

        return self._request_service.execute(step, prepared_request)


def build_runner() -> ApiRequestRunner:
    return ApiRequestRunner(
        env_loader=EnvFileLoader(),
        step_loader=RequestStepLoader(),
        request_builder=ApiRequestBuilder(auth_strategy_factory=AuthStrategyFactory()),
        request_service=ApiRequestService(),
    )


def main() -> int:
    if len(sys.argv) != 3:
        result = ExecutionResult(
            status=StepStatus.ERROR,
            message="Usage: python tools/api/run_request.py <env_file> <step_json>",
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