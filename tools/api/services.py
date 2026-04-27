"""Services for API request execution."""

from __future__ import annotations

import os
import platform
from pathlib import Path
import random
import re
import shutil
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlsplit

import requests


def _ensure_requests_exception_aliases() -> None:
    exceptions_module = getattr(requests, "exceptions", None)
    if exceptions_module is None:
        return
    for exception_name in (
        "RequestException",
        "ConnectionError",
        "SSLError",
        "ReadTimeout",
        "ConnectTimeout",
    ):
        if hasattr(requests, exception_name):
            continue
        exception_type = getattr(exceptions_module, exception_name, None)
        if exception_type is not None:
            setattr(requests, exception_name, exception_type)


_ensure_requests_exception_aliases()

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

from .auth import AuthConfigurationError, AuthStrategyFactory
from .loaders import ApiEnvLoader, RequestStepLoader
from .models import EnvConfig, PreparedRequest, RequestRetryPolicy, RequestStep, ResponseData


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
            base_url_raw=env.api_base_url_raw,
            path=step.path,
            base_url_key=env.api_base_url_key,
            json_body=step.body,
            query_params=step.query_params,
            timeout_seconds=step.timeout_seconds,
        )
        prepared_request.request_debug = build_request_debug(prepared_request)
        if env.actor:
            prepared_request.request_debug["actor"] = env.actor
            prepared_request.request_debug["api_base_url_key"] = env.api_base_url_key

        auth_strategy = self._auth_strategy_factory.create(env)
        auth_strategy.apply(env, prepared_request)

        return prepared_request


class ApiRequestService:
    """Executes HTTP requests for scenario API steps."""

    def __init__(
        self,
        session: requests.Session | None = None,
        resolver=None,
        hostname_resolver=None,
        fqdn_resolver=None,
        system_resolver_diagnostics: bool = True,
        sleep_func=None,
        jitter_func=None,
    ) -> None:
        self._session = session or requests.Session()
        self._resolver = resolver or socket.getaddrinfo
        self._hostname_resolver = hostname_resolver or socket.gethostbyname
        self._fqdn_resolver = fqdn_resolver or socket.getfqdn
        self._derive_hostname_debug_from_resolver = (
            resolver is not None and hostname_resolver is None and fqdn_resolver is None
        )
        self._system_resolver_diagnostics = system_resolver_diagnostics
        self._sleep_func = sleep_func or time.sleep
        self._jitter_func = jitter_func or (lambda upper_bound: random.uniform(0, upper_bound))

    def execute(self, step: RequestStep, prepared_request: PreparedRequest) -> ExecutionResult:
        request_debug = dict(prepared_request.request_debug or build_request_debug(prepared_request))
        request_debug.update(self._request_runtime_debug())
        dns_precheck = self._precheck_connectivity(request_debug)
        resolver_debug = self._resolver_debug(request_debug.get("parsed_hostname"))
        request_debug["dns_precheck"] = dns_precheck
        request_debug["resolver_debug"] = resolver_debug
        request_debug["process_debug"] = resolver_debug.get("process")
        request_debug["resolv_conf"] = resolver_debug.get("resolv_conf")
        request_debug["getent_hosts"] = resolver_debug.get("getent_hosts")
        request_debug["nslookup"] = resolver_debug.get("nslookup")
        request_debug["ping"] = resolver_debug.get("ping")
        request_debug["hosts_file"] = resolver_debug.get("hosts_file")
        request_debug["resolver_comparison"] = resolver_debug.get("comparison")
        request_debug["getaddrinfo"] = dns_precheck["getaddrinfo"]
        request_debug["gethostbyname"] = dns_precheck["gethostbyname"]
        request_debug["getfqdn"] = dns_precheck["getfqdn"]
        if dns_precheck["status"] == StepStatus.BLOCKED.value:
            getaddrinfo_result = dns_precheck["getaddrinfo"]
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=(
                    "Hostname DNS precheck failed: "
                    f"{getaddrinfo_result.get('error_type')}: {getaddrinfo_result.get('message')}"
                ),
                details={
                    "method": step.method,
                    "url": prepared_request.url,
                    "classification": "connectivity",
                    "request_debug": request_debug,
                    "runtime_signal": _api_connectivity_signal().to_dict(),
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

        return self._execute_with_retry(step, prepared_request, request_kwargs, request_debug)

    def _execute_with_retry(
        self,
        step: RequestStep,
        prepared_request: PreparedRequest,
        request_kwargs: dict[str, Any],
        request_debug: dict[str, Any],
    ) -> ExecutionResult:
        retry_policy = step.retry_policy
        retry_enabled = retry_policy.is_enabled_for_method(step.method)
        max_attempts = retry_policy.max_attempts if retry_enabled else 1
        retry_details: dict[str, Any] = {
            "enabled": retry_enabled,
            "policy_source": retry_policy.source_for_method(step.method),
            "method": step.method,
            "safe_method": step.method.upper() in {"GET", "HEAD", "OPTIONS"},
            "max_attempts": max_attempts,
            "retry_on": list(retry_policy.retry_on),
            "retry_on_statuses": list(retry_policy.retry_on_statuses),
            "attempts": [],
        }

        for attempt_number in range(1, max_attempts + 1):
            try:
                response = self._session.request(step.method, prepared_request.url, **request_kwargs)
            except requests.RequestException as exc:
                retry_reason = self._retry_reason_for_exception(exc)
                can_retry = (
                    retry_enabled
                    and retry_reason in retry_policy.retry_on
                    and attempt_number < max_attempts
                )
                delay = self._retry_delay_seconds(retry_policy, attempt_number) if can_retry else 0.0
                retry_details["attempts"].append(
                    {
                        "attempt": attempt_number,
                        "outcome": "exception",
                        "reason": retry_reason or "non_retryable_request_exception",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                        "will_retry": can_retry,
                        "next_delay_seconds": delay if can_retry else None,
                    }
                )
                if can_retry:
                    self._sleep_func(delay)
                    continue
                self._finalize_retry_details(retry_details, attempt_number, retry_reason or "request_exception")
                return ExecutionResult(
                    status=StepStatus.BLOCKED,
                    message=(
                        f"Request failed after {len(retry_details['attempts'])} attempt(s): "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    details={
                        "method": step.method,
                        "url": prepared_request.url,
                        "error_type": type(exc).__name__,
                        "classification": "connectivity",
                        "request_debug": request_debug,
                        "retry": retry_details,
                        "runtime_signal": _api_connectivity_signal().to_dict(),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                retry_details["attempts"].append(
                    {
                        "attempt": attempt_number,
                        "outcome": "runtime_error",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                        "will_retry": False,
                        "next_delay_seconds": None,
                    }
                )
                self._finalize_retry_details(retry_details, attempt_number, "runtime_error")
                return ExecutionResult(
                    status=StepStatus.ERROR,
                    message=f"Runtime error after {len(retry_details['attempts'])} attempt(s): {exc}",
                    details={
                        "method": step.method,
                        "url": prepared_request.url,
                        "request_debug": request_debug,
                        "retry": retry_details,
                        "runtime_signal": _runtime_tool_failure_signal().to_dict(),
                    },
                )

            response_data = ResponseData(
                http_status=response.status_code,
                headers=dict(response.headers),
                body=self._parse_response_body(response),
            )
            retry_reason = f"http_{response.status_code}"
            can_retry = (
                retry_enabled
                and response.status_code in retry_policy.retry_on_statuses
                and attempt_number < max_attempts
            )
            delay = self._retry_delay_seconds(retry_policy, attempt_number) if can_retry else 0.0
            retry_details["attempts"].append(
                {
                    "attempt": attempt_number,
                    "outcome": "response",
                    "http_status": response.status_code,
                    "reason": retry_reason,
                    "will_retry": can_retry,
                    "next_delay_seconds": delay if can_retry else None,
                }
            )
            if can_retry:
                self._sleep_func(delay)
                continue

            self._finalize_retry_details(retry_details, attempt_number, retry_reason)
            if response.status_code in {502, 503, 504}:
                return ExecutionResult(
                    status=StepStatus.BLOCKED,
                    message=(
                        f"Remote service unavailable after {len(retry_details['attempts'])} attempt(s): "
                        f"HTTP {response.status_code}"
                    ),
                    details={
                        "method": step.method,
                        "url": prepared_request.url,
                        "response": response_data,
                        "classification": "service_unavailable",
                        "request_debug": request_debug,
                        "retry": retry_details,
                        "runtime_signal": _api_service_unavailable_signal().to_dict(),
                    },
                )

            success_message = "Request executed successfully"
            if len(retry_details["attempts"]) > 1:
                success_message += f" after {len(retry_details['attempts'])} attempt(s)"
            return ExecutionResult(
                status=StepStatus.PASS,
                message=success_message,
                details={
                    "method": step.method,
                    "url": prepared_request.url,
                    "response": response_data,
                    "request_debug": request_debug,
                    "retry": retry_details,
                },
            )

        self._finalize_retry_details(retry_details, len(retry_details["attempts"]), "attempts_exhausted")
        return ExecutionResult(
            status=StepStatus.BLOCKED,
            message=f"Request failed after {len(retry_details['attempts'])} attempt(s): attempts exhausted",
            details={
                "method": step.method,
                "url": prepared_request.url,
                "classification": "connectivity",
                "request_debug": request_debug,
                "retry": retry_details,
                "runtime_signal": _api_connectivity_signal().to_dict(),
            },
        )

    def _retry_delay_seconds(self, retry_policy: RequestRetryPolicy, attempt_number: int) -> float:
        base_delay = retry_policy.backoff_seconds * (retry_policy.backoff_multiplier ** (attempt_number - 1))
        if base_delay <= 0:
            return 0.0
        jitter_cap = min(base_delay * 0.1, 0.25)
        return round(base_delay + self._jitter_func(jitter_cap), 3)

    @staticmethod
    def _finalize_retry_details(retry_details: dict[str, Any], attempt_number: int, final_reason: str) -> None:
        retry_details["attempt_count"] = len(retry_details["attempts"])
        retry_details["final_attempt"] = attempt_number
        retry_details["final_reason"] = final_reason

    @staticmethod
    def _retry_reason_for_exception(exc: requests.RequestException) -> str | None:
        read_timeout_type = getattr(requests, "ReadTimeout", None)
        connect_timeout_type = getattr(requests, "ConnectTimeout", None)
        if read_timeout_type is not None and isinstance(exc, read_timeout_type):
            return "read_timeout"
        if connect_timeout_type is not None and isinstance(exc, connect_timeout_type):
            return "connect_timeout"
        if isinstance(exc, requests.ConnectionError):
            return "connection_error"
        return None

    def _precheck_connectivity(self, request_debug: dict[str, Any]) -> dict[str, Any]:
        hostname = request_debug.get("parsed_hostname")
        if not hostname:
            return {
                "status": StepStatus.BLOCKED.value,
                "getaddrinfo": {
                    "status": StepStatus.BLOCKED.value,
                    "hostname_value": request_debug.get("hostname_value"),
                    "hostname_repr": request_debug.get("hostname_repr"),
                    "final_url_value": request_debug.get("final_url_value"),
                    "final_url_repr": request_debug.get("final_url_repr"),
                    "error_type": "MissingHostname",
                    "errno": None,
                    "message": "URL does not contain a hostname.",
                },
                "gethostbyname": {
                    "status": StepStatus.BLOCKED.value,
                    "error_type": "MissingHostname",
                    "errno": None,
                    "message": "URL does not contain a hostname.",
                },
                "getfqdn": {"value": None},
            }

        port = request_debug.get("parsed_port")
        gethostbyname_result: dict[str, Any]
        getfqdn_result: dict[str, Any]

        try:
            addrinfo_results = self._resolver(hostname, port)
        except Exception as exc:  # noqa: BLE001
            getaddrinfo_result = {
                "status": StepStatus.BLOCKED.value,
                "hostname_value": request_debug.get("hostname_value"),
                "hostname_repr": request_debug.get("hostname_repr"),
                "final_url_value": request_debug.get("final_url_value"),
                "final_url_repr": request_debug.get("final_url_repr"),
                "error_type": type(exc).__name__,
                "errno": getattr(exc, "errno", None),
                "message": str(exc),
            }
            overall_status = StepStatus.BLOCKED.value
        else:
            getaddrinfo_result = {
                "status": StepStatus.PASS.value,
                "hostname_value": request_debug.get("hostname_value"),
                "hostname_repr": request_debug.get("hostname_repr"),
                "port": port,
                "result_count": len(addrinfo_results),
                "sample_results": _sample_getaddrinfo_results(addrinfo_results),
                "resolved_addresses": _resolved_addresses(addrinfo_results),
                "error_type": None,
                "errno": None,
                "message": None,
            }
            overall_status = StepStatus.PASS.value

        if self._derive_hostname_debug_from_resolver:
            derived_address = _first_resolved_address(addrinfo_results) if overall_status == StepStatus.PASS.value else None
            if derived_address is None:
                gethostbyname_result = {
                    "status": StepStatus.BLOCKED.value,
                    "error_type": "ResolutionError",
                    "errno": None,
                    "message": "No resolved address available from resolver results.",
                    "address": None,
                }
            else:
                gethostbyname_result = {
                    "status": StepStatus.PASS.value,
                    "error_type": None,
                    "errno": None,
                    "message": None,
                    "address": derived_address,
                }
        else:
            try:
                address = self._hostname_resolver(hostname)
            except Exception as exc:  # noqa: BLE001
                gethostbyname_result = {
                    "status": StepStatus.BLOCKED.value,
                    "error_type": type(exc).__name__,
                    "errno": getattr(exc, "errno", None),
                    "message": str(exc),
                    "address": None,
                }
            else:
                gethostbyname_result = {
                    "status": StepStatus.PASS.value,
                    "error_type": None,
                    "errno": None,
                    "message": None,
                    "address": address,
                }

        if self._derive_hostname_debug_from_resolver:
            getfqdn_result = {"value": hostname}
        else:
            try:
                getfqdn_result = {"value": self._fqdn_resolver(hostname)}
            except Exception as exc:  # noqa: BLE001
                getfqdn_result = {
                    "value": None,
                    "error_type": type(exc).__name__,
                    "errno": getattr(exc, "errno", None),
                    "message": str(exc),
                }

        return {
            "status": overall_status,
            "getaddrinfo": getaddrinfo_result,
            "gethostbyname": gethostbyname_result,
            "getfqdn": getfqdn_result,
        }

    def _request_runtime_debug(self) -> dict[str, Any]:
        return {
            "requests_verify": "default",
            "requests_allow_redirects": "default",
            "requests_proxies": "default",
            "session_trust_env": getattr(self._session, "trust_env", None),
        }

    def _resolver_debug(self, hostname: str | None) -> dict[str, Any]:
        if self._system_resolver_diagnostics:
            getent_hosts = _run_getent_hosts(hostname)
            nslookup = _run_nslookup(hostname)
            ping = _run_ping(hostname)
        else:
            getent_hosts = _resolver_command_not_run("getent_hosts")
            nslookup = _resolver_command_not_run("nslookup")
            ping = _resolver_command_not_run("ping")
        hosts_file = _read_hosts_file(hostname)

        return {
            "process": {
                "sys_executable": sys.executable,
                "cwd": os.getcwd(),
                "platform": platform.platform(),
                "hostname": _safe_socket_call(socket.gethostname),
                "fqdn": _safe_socket_call(socket.getfqdn),
                "socket_default_timeout": socket.getdefaulttimeout(),
                "env": {
                    "VIRTUAL_ENV": _safe_env_debug_value("VIRTUAL_ENV"),
                    "PATH": _safe_env_debug_value("PATH"),
                    "HTTP_PROXY": _safe_env_debug_value("HTTP_PROXY"),
                    "HTTPS_PROXY": _safe_env_debug_value("HTTPS_PROXY"),
                    "NO_PROXY": _safe_env_debug_value("NO_PROXY"),
                    "REQUESTS_CA_BUNDLE": _safe_env_debug_value("REQUESTS_CA_BUNDLE"),
                    "SSL_CERT_FILE": _safe_env_debug_value("SSL_CERT_FILE"),
                },
            },
            "resolv_conf": _read_resolv_conf(),
            "hosts_file": hosts_file,
            "getent_hosts": getent_hosts,
            "nslookup": nslookup,
            "ping": ping,
            "comparison": {
                "python_getaddrinfo": "see request_debug.dns_precheck.getaddrinfo",
                "python_gethostbyname": "see request_debug.dns_precheck.gethostbyname",
                "system_getent_status": _command_status(getent_hosts),
                "system_nslookup_status": _command_status(nslookup),
                "system_ping_status": _command_status(ping),
                "hosts_file_status": hosts_file.get("status"),
                "child_env": "see request_debug.process_debug.env",
            },
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
        "env_base_url_raw_value": prepared_request.base_url_raw,
        "env_base_url_raw_repr": repr(prepared_request.base_url_raw),
        "env_base_url_normalized_value": prepared_request.base_url,
        "env_base_url_normalized_repr": repr(prepared_request.base_url),
        "base_url_value": prepared_request.base_url,
        "base_url_repr": repr(prepared_request.base_url),
        "normalized_base_url_value": prepared_request.base_url,
        "normalized_base_url_repr": repr(prepared_request.base_url),
        "path_value": prepared_request.path,
        "path_repr": repr(prepared_request.path),
        "final_url_value": prepared_request.url,
        "final_url_repr": repr(prepared_request.url),
        "parsed_scheme": parsed_url.scheme,
        "parsed_netloc": parsed_url.netloc,
        "parsed_hostname": hostname,
        "parsed_port": port,
        "hostname_value": hostname,
        "hostname_repr": repr(hostname),
        "base_url_env_key": prepared_request.base_url_key,
    }


def _sample_getaddrinfo_results(results: list[Any]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for result in results[:3]:
        family, socktype, proto, canonname, sockaddr = result
        samples.append(
            {
                "family": getattr(family, "name", str(family)),
                "socktype": getattr(socktype, "name", str(socktype)),
                "proto": proto,
                "canonname": canonname,
                "sockaddr": tuple(sockaddr) if isinstance(sockaddr, tuple) else sockaddr,
            }
        )
    return samples


def _resolved_addresses(results: list[Any]) -> list[str]:
    return sorted({str(result[4][0]) for result in results if len(result) >= 5 and result[4]})


def _first_resolved_address(results: list[Any]) -> str | None:
    addresses = _resolved_addresses(results)
    return addresses[0] if addresses else None


def _safe_env_debug_value(key: str) -> str | None:
    value = os.environ.get(key)
    if value is None:
        return None
    if key.upper() in {"HTTP_PROXY", "HTTPS_PROXY"}:
        return re.sub(r"(?<=://)[^/@]+@", "<redacted>@", value)
    return value


def _safe_socket_call(callback) -> dict[str, Any]:
    try:
        return {"status": StepStatus.PASS.value, "value": callback()}
    except Exception as exc:  # noqa: BLE001
        return {
            "status": StepStatus.BLOCKED.value,
            "value": None,
            "error_type": type(exc).__name__,
            "errno": getattr(exc, "errno", None),
            "message": str(exc),
        }


def _read_resolv_conf() -> dict[str, Any]:
    resolv_path = Path("/etc/resolv.conf")
    if not resolv_path.exists():
        return {"exists": False, "first_lines": []}
    try:
        first_lines = resolv_path.read_text(encoding="utf-8", errors="replace").splitlines()[:20]
    except OSError as exc:
        return {
            "exists": True,
            "first_lines": [],
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    return {"exists": True, "first_lines": first_lines}


def _read_hosts_file(hostname: str | None) -> dict[str, Any]:
    hosts_path = Path("/etc/hosts")
    if not hosts_path.exists():
        return {"exists": False, "status": "NOT_AVAILABLE", "path": str(hosts_path), "matching_lines": []}

    try:
        lines = hosts_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {
            "exists": True,
            "status": StepStatus.BLOCKED.value,
            "path": str(hosts_path),
            "matching_lines": [],
            "error_type": type(exc).__name__,
            "message": str(exc),
        }

    matching_lines = []
    if hostname:
        hostname_lower = hostname.lower()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            tokens = stripped.split()
            if any(token.lower() == hostname_lower for token in tokens[1:]):
                matching_lines.append(stripped)

    return {
        "exists": True,
        "status": StepStatus.PASS.value if matching_lines else "NOT_FOUND",
        "path": str(hosts_path),
        "matching_lines": matching_lines[:20],
    }


def _run_getent_hosts(hostname: str | None) -> dict[str, Any]:
    return _run_resolver_command("getent_hosts", ["getent", "hosts", hostname] if hostname else None)


def _run_nslookup(hostname: str | None) -> dict[str, Any]:
    return _run_resolver_command("nslookup", ["nslookup", hostname] if hostname else None)


def _run_ping(hostname: str | None) -> dict[str, Any]:
    return _run_resolver_command("ping", ["ping", "-c", "1", hostname] if hostname else None)


def _run_resolver_command(name: str, command: list[str | None] | None) -> dict[str, Any]:
    if not command or not command[-1]:
        return {"available": False, "reason": "missing hostname", "status": "NOT_AVAILABLE"}

    executable_name = str(command[0])
    executable_path = shutil.which(executable_name)
    if executable_path is None:
        return {"available": False, "reason": f"{executable_name} not found", "status": "NOT_AVAILABLE"}

    resolved_command = [executable_path, *[str(part) for part in command[1:]]]
    try:
        completed = subprocess.run(
            resolved_command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=5,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "available": True,
            "name": name,
            "command": resolved_command,
            "status": StepStatus.BLOCKED.value,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }

    return {
        "available": True,
        "name": name,
        "command": resolved_command,
        "status": StepStatus.PASS.value if completed.returncode == 0 else StepStatus.BLOCKED.value,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _command_status(result: dict[str, Any]) -> str | None:
    return result.get("status")


def _resolver_command_not_run(name: str) -> dict[str, Any]:
    return {"available": False, "name": name, "status": "NOT_RUN", "reason": "system resolver diagnostics disabled"}


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
            step = self._step_loader.load(step_file)
            env = self._env_loader.load(env_file, actor=step.actor)
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
                details={
                    "method": step.method,
                    "runtime_signal": _api_auth_configuration_signal().to_dict(),
                },
            )
        except ValidationError as exc:
            return ExecutionResult(
                status=StepStatus.BLOCKED,
                message=str(exc),
                details={
                    "method": step.method,
                    "runtime_signal": _api_auth_configuration_signal().to_dict(),
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status=StepStatus.ERROR,
                message=f"Failed to prepare request: {exc}",
                details={
                    "method": step.method,
                    "runtime_signal": _runtime_tool_failure_signal().to_dict(),
                },
            )

        return self._request_service.execute(step, prepared_request)


def build_runner() -> ApiRequestRunner:
    return ApiRequestRunner(
        env_loader=ApiEnvLoader(),
        step_loader=RequestStepLoader(),
        request_builder=ApiRequestBuilder(auth_strategy_factory=AuthStrategyFactory()),
        request_service=ApiRequestService(),
    )


def _api_auth_configuration_signal() -> NormalizedRuntimeSignal:
    return NormalizedRuntimeSignal(
        source=RuntimeSignalSource.TOOL,
        code=ToolFailureCode.API_AUTH_CONFIGURATION_BLOCKED,
        category=RuntimeFailureCategory.CONFIGURATION,
        retry_hint=RetryHint.AFTER_OPERATOR_FIX,
        continuation_hint=ContinuationHint.STOP_AND_FIX,
        tags=(RuntimeSignalTag.ENVIRONMENT_BLOCKED, RuntimeSignalTag.USER_FIXABLE),
        operator_fixable=True,
    )


def _api_connectivity_signal() -> NormalizedRuntimeSignal:
    return NormalizedRuntimeSignal(
        source=RuntimeSignalSource.TOOL,
        code=ToolFailureCode.API_CONNECTIVITY_BLOCKED,
        category=RuntimeFailureCategory.CONNECTIVITY,
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


def _api_service_unavailable_signal() -> NormalizedRuntimeSignal:
    return NormalizedRuntimeSignal(
        source=RuntimeSignalSource.TOOL,
        code=ToolFailureCode.API_SERVICE_UNAVAILABLE,
        category=RuntimeFailureCategory.SERVICE_AVAILABILITY,
        retry_hint=RetryHint.AFTER_SERVICE_RECOVERY,
        continuation_hint=ContinuationHint.WAIT_FOR_DECISION,
        tags=(RuntimeSignalTag.RETRYABLE, RuntimeSignalTag.REQUIRES_DECISION),
        resumable=True,
        requires_decision=True,
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
