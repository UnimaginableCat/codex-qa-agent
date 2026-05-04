from __future__ import annotations

from pathlib import Path
import sys
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import requests
except ModuleNotFoundError:
    requests = types.ModuleType("requests")

    class _RequestException(Exception):
        pass

    class ConnectionError(_RequestException):
        pass

    class Timeout(_RequestException):
        pass

    class SSLError(_RequestException):
        pass

    class _Response:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers = {}
            self._content = b""

        def json(self):
            import json

            return json.loads(self._content.decode("utf-8"))

        @property
        def text(self) -> str:
            return self._content.decode("utf-8")

    requests.RequestException = _RequestException
    requests.ConnectionError = ConnectionError
    requests.Timeout = Timeout
    requests.SSLError = SSLError
    requests.Response = _Response
    requests.Session = object
    requests_auth = types.ModuleType("requests.auth")

    class _HTTPBasicAuth:
        def __init__(self, username: str, password: str) -> None:
            self.username = username
            self.password = password

    requests_auth.HTTPBasicAuth = _HTTPBasicAuth
    requests.auth = requests_auth
    sys.modules["requests"] = requests
    sys.modules["requests.auth"] = requests_auth

try:
    import dotenv  # noqa: F401
except ModuleNotFoundError:
    dotenv = types.ModuleType("dotenv")

    def _dotenv_values(env_path):
        values = {}
        for line in Path(env_path).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
        return values

    dotenv.dotenv_values = _dotenv_values
    sys.modules["dotenv"] = dotenv

from tools.api.models import PreparedRequest, RequestStep
from tools.api.services import ApiRequestService
from tools.common.statuses import StepStatus


class ApiConnectivityClassificationTests(unittest.TestCase):
    def test_dns_failure_is_blocked(self) -> None:
        result = ApiRequestService(
            session=_ResponseSession(200),
            resolver=_failing_resolver,
            system_resolver_diagnostics=False,
        ).execute(
            self._step(),
            self._prepared_request(),
        )

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertEqual(result.details["classification"], "connectivity")
        self.assertEqual(
            result.details["request_debug"]["dns_precheck"]["getaddrinfo"]["status"],
            StepStatus.BLOCKED.value,
        )
        self.assertEqual(result.details["request_debug"]["getaddrinfo"]["status"], StepStatus.BLOCKED.value)
        self.assertEqual(result.details["request_debug"]["hostname_value"], "api.example.invalid")
        self.assertEqual(result.details["request_debug"]["hostname_repr"], "'api.example.invalid'")

    def test_connection_timeout_is_blocked(self) -> None:
        result = self._run_with_exception(requests.Timeout("request timed out"))

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertEqual(result.details["classification"], "connectivity")
        self.assertEqual(result.details["error_type"], "Timeout")

    def test_connection_refused_is_blocked(self) -> None:
        result = self._run_with_exception(requests.ConnectionError("connection refused"))

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertEqual(result.details["classification"], "connectivity")

    def test_ssl_connectivity_failure_is_blocked(self) -> None:
        result = self._run_with_exception(requests.SSLError("certificate verify failed"))

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertEqual(result.details["classification"], "connectivity")
        self.assertEqual(result.details["error_type"], "SSLError")

    def test_service_unavailable_response_is_blocked(self) -> None:
        result = ApiRequestService(
            session=_ResponseSession(503),
            resolver=_passing_resolver,
            system_resolver_diagnostics=False,
        ).execute(
            self._step(),
            self._prepared_request(),
        )

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertEqual(result.details["classification"], "service_unavailable")
        self.assertEqual(result.details["response"].http_status, 503)

    def test_binary_response_body_is_omitted_but_result_stays_structured(self) -> None:
        result = ApiRequestService(
            session=_ResponseSession(200, content=b"%PDF-1.7\nbinary", content_type="application/pdf"),
            resolver=_passing_resolver,
            system_resolver_diagnostics=False,
        ).execute(
            self._step(),
            self._prepared_request(),
        )

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertEqual(result.details["response"].http_status, 200)
        self.assertIn("non-text response body omitted", result.details["response"].body)
        self.assertIn("content-type=application/pdf", result.details["response"].body)

    def test_internal_non_request_exception_is_error(self) -> None:
        result = self._run_with_exception(RuntimeError("session wrapper broke"))

        self.assertEqual(result.status, StepStatus.ERROR)
        self.assertNotEqual(result.details.get("classification"), "connectivity")

    def _run_with_exception(self, exc: Exception):
        return ApiRequestService(
            session=_ExceptionSession(exc),
            resolver=_passing_resolver,
            system_resolver_diagnostics=False,
        ).execute(
            self._step(),
            self._prepared_request(),
        )

    @staticmethod
    def _step() -> RequestStep:
        return RequestStep(method="GET", path="/health")

    @staticmethod
    def _prepared_request() -> PreparedRequest:
        return PreparedRequest(url="https://api.example.invalid/health", headers={})


class _ExceptionSession:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def request(self, method: str, url: str, **kwargs):
        raise self._exc


class _ResponseSession:
    def __init__(
        self,
        status_code: int,
        *,
        content: bytes = b'{"error": "unavailable"}',
        content_type: str = "application/json",
    ) -> None:
        self._status_code = status_code
        self._content = content
        self._content_type = content_type

    def request(self, method: str, url: str, **kwargs):
        response = requests.Response()
        response.status_code = self._status_code
        response._content = self._content
        response.headers["Content-Type"] = self._content_type
        return response


def _passing_resolver(hostname, port):
    return [(2, 1, 6, "", ("203.0.113.20", port or 443))]


def _failing_resolver(hostname, port):
    raise OSError("mock DNS failure")


if __name__ == "__main__":
    unittest.main()
