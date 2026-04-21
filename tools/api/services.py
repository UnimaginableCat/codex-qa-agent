"""Services for API request execution."""

from __future__ import annotations

from pathlib import Path
import socket
from typing import Any
from urllib.parse import urlsplit

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

        final_url = UrlBuilder.build(env.api_base_url, step.path)
        prepared_request = PreparedRequest(
            url=final_url,
            headers=dict(step.headers),
            base_url=env.api_base_url,
            path=step.path,
            base_url_key=env.api_base_url_key,
            json_body=step.body,
            query_params=step.query_params,
            timeout_seconds=step.timeout_seconds,
        )
        prepared_request.request_debug = build_request_debug(prepared_request)

        auth_strategy = self._auth_strategy_factory.create(env)
        auth_strategy.apply(env, prepared_request)

        return prepared_request


class ApiRequestService:
    """Executes HTTP requests for scenario API steps."""

    def __init__(self, session: requests.Session | None = None, resolver=None) -> None:
        self._session = session or requests.Session()
        self._resolver = resolver or socket.getaddrinfo

    def execute(self, step: RequestStep, prepared_request: PreparedRequest) -> ExecutionResult:
        request_debug = dict(prepared_request.request_debug or build_request_debug(prepared_request))
        request_debug.update(self._request_runtime_debug())
        precheck = self._precheck_connectivity(request_debug)
        request_debug["getaddrinfo"] = precheck
        if precheck["status"] == StepStatus.BLOCKED.value:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=(
                    "Hostname DNS precheck failed: "
                    f"{precheck.get('error_type')}: {precheck.get('message')}"
                ),
                details={
                    "method": step.method,
                    "url": prepared_request.url,
                    "classification": "connectivity",
                    "request_debug": request_debug,
                },
            )

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
                status=StepStatus.BLOCKED,
                message=f"Request failed: {exc}",
                details={
                    "method": step.method,
                    "url": prepared_request.url,
                    "error_type": type(exc).__name__,
                    "classification": "connectivity",
                    "request_debug": request_debug,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Runtime error: {exc}",
                details={"method": step.method, "url": prepared_request.url, "request_debug": request_debug},
            )

        response_data = ResponseData(
            http_status=response.status_code,
            headers=dict(response.headers),
            body=self._parse_response_body(response),
        )

        if response.status_code in {502, 503, 504}:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=f"Remote service unavailable: HTTP {response.status_code}",
                details={
                    "method": step.method,
                    "url": prepared_request.url,
                    "response": response_data,
                    "classification": "service_unavailable",
                    "request_debug": request_debug,
                },
            )

        return ExecutionResult(
            status=StepStatus.PASS,
            message="Request executed successfully",
            details={
                "method": step.method,
                "url": prepared_request.url,
                "response": response_data,
                "request_debug": request_debug,
            },
        )

    def _precheck_connectivity(self, request_debug: dict[str, Any]) -> dict[str, Any]:
        hostname = request_debug.get("parsed_hostname")
        if not hostname:
            return {
                "status": StepStatus.BLOCKED.value,
                "hostname_repr": request_debug.get("hostname_repr"),
                "final_url_repr": request_debug.get("final_url_repr"),
                "error_type": "MissingHostname",
                "message": "URL does not contain a hostname.",
            }

        try:
            results = self._resolver(hostname, request_debug.get("parsed_port"))
        except Exception as exc:  # noqa: BLE001
            return {
                "status": StepStatus.BLOCKED.value,
                "hostname_repr": request_debug.get("hostname_repr"),
                "final_url_repr": request_debug.get("final_url_repr"),
                "error_type": type(exc).__name__,
                "message": str(exc),
            }

        return {
            "status": StepStatus.PASS.value,
            "hostname_repr": request_debug.get("hostname_repr"),
            "port": request_debug.get("parsed_port"),
            "result_count": len(results),
            "addresses": sorted({str(result[4][0]) for result in results if len(result) >= 5 and result[4]}),
        }

    def _request_runtime_debug(self) -> dict[str, Any]:
        return {
            "requests_verify": "default",
            "requests_allow_redirects": "default",
            "requests_proxies": "default",
            "session_trust_env": getattr(self._session, "trust_env", None),
        }

    @staticmethod
    def _parse_response_body(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text


def build_request_debug(prepared_request: PreparedRequest) -> dict[str, Any]:
    parsed_url = urlsplit(prepared_request.url)
    hostname = parsed_url.hostname
    port = _parsed_port(parsed_url)
    if port is None:
        port = _default_port(parsed_url.scheme)

    return {
        "base_url_repr": repr(prepared_request.base_url),
        "path_repr": repr(prepared_request.path),
        "final_url_repr": repr(prepared_request.url),
        "parsed_scheme": parsed_url.scheme,
        "parsed_netloc": parsed_url.netloc,
        "parsed_hostname": hostname,
        "parsed_port": port,
        "hostname_repr": repr(hostname),
        "base_url_env_key": prepared_request.base_url_key,
    }


def _parsed_port(parsed_url) -> int | None:
    try:
        return parsed_url.port
    except ValueError:
        return None


def _default_port(scheme: str) -> int | None:
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    return None


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
