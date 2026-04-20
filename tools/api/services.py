"""Services for API request execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from tools.common import ExecutionResult, JsonFileLoadError, StepStatus, ValidationError
from tools.common.errors import EnvFileLoadError

from .auth import AuthConfigurationError, AuthStrategyFactory
from .loaders import ApiEnvLoader, RequestStepLoader
from .models import EnvConfig, PreparedRequest, RequestStep, ResponseData


class UrlBuilder:
    """Builds a final request URL from base URL and step path."""

    @staticmethod
    def build(base_url: str, path: str) -> str:
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


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
                details={"method": step.method, "url": prepared_request.url},
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Runtime error: {exc}",
                details={"method": step.method, "url": prepared_request.url},
            )

        response_data = ResponseData(
            http_status=response.status_code,
            headers=dict(response.headers),
            body=self._parse_response_body(response),
        )

        return ExecutionResult(
            status=StepStatus.PASS,
            message="Request executed successfully",
            details={
                "method": step.method,
                "url": prepared_request.url,
                "response": response_data,
            },
        )

    @staticmethod
    def _parse_response_body(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text


class ApiRequestRunner:
    """Coordinates env loading, request step loading, preparation, and execution."""

    def __init__(
        self,
        env_loader: ApiEnvLoader,
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
        except (EnvFileLoadError, JsonFileLoadError) as exc:
            return ExecutionResult(status=StepStatus.ERROR, message=str(exc))
        except ValidationError as exc:
            return ExecutionResult(status=StepStatus.BLOCKED, message=str(exc))

        try:
            prepared_request = self._request_builder.build(env, step)
        except AuthConfigurationError as exc:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=str(exc),
                details={"method": step.method},
            )
        except ValidationError as exc:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=str(exc),
                details={"method": step.method},
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Failed to prepare request: {exc}",
                details={"method": step.method},
            )

        return self._request_service.execute(step, prepared_request)


def build_runner() -> ApiRequestRunner:
    return ApiRequestRunner(
        env_loader=ApiEnvLoader(),
        step_loader=RequestStepLoader(),
        request_builder=ApiRequestBuilder(auth_strategy_factory=AuthStrategyFactory()),
        request_service=ApiRequestService(),
    )
