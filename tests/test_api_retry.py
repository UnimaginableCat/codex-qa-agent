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

    class ReadTimeout(_RequestException):
        pass

    class ConnectTimeout(_RequestException):
        pass

    class Timeout(_RequestException):
        pass

    class SSLError(_RequestException):
        pass

    class _Response:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers = {}
            self._content = b"{}"

        def json(self):
            return {}

        @property
        def text(self) -> str:
            return "{}"

    requests.RequestException = _RequestException
    requests.ConnectionError = ConnectionError
    requests.Timeout = Timeout
    requests.SSLError = SSLError
    requests.ReadTimeout = ReadTimeout
    requests.ConnectTimeout = ConnectTimeout
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

if not hasattr(requests, "ReadTimeout"):
    class ReadTimeout(requests.RequestException):
        pass

    requests.ReadTimeout = ReadTimeout

if not hasattr(requests, "ConnectTimeout"):
    class ConnectTimeout(requests.RequestException):
        pass

    requests.ConnectTimeout = ConnectTimeout

try:
    import dotenv  # noqa: F401
except ModuleNotFoundError:
    dotenv = types.ModuleType("dotenv")

    def _dotenv_values(env_path):
        return {}

    dotenv.dotenv_values = _dotenv_values
    sys.modules["dotenv"] = dotenv

from tools.api.models import PreparedRequest, RequestRetryPolicy, RequestStep
from tools.api.services import ApiRequestService
from tools.common.statuses import StepStatus


class ApiRetryTests(unittest.TestCase):
    def test_get_read_timeout_retries_and_succeeds_by_default(self) -> None:
        session = _SequenceSession([requests.ReadTimeout("read timed out"), _response(200)])

        result = self._service(session).execute(self._step("GET"), self._prepared_request())

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertEqual(session.call_count, 2)
        self.assertIn("after 2 attempt(s)", result.message)
        self.assertEqual(result.details["retry"]["attempt_count"], 2)
        self.assertEqual(result.details["retry"]["attempts"][0]["reason"], "read_timeout")
        self.assertTrue(result.details["retry"]["attempts"][0]["will_retry"])

    def test_post_read_timeout_without_opt_in_does_not_retry(self) -> None:
        session = _SequenceSession([requests.ReadTimeout("read timed out"), _response(200)])

        result = self._service(session).execute(self._step("POST"), self._prepared_request())

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertEqual(session.call_count, 1)
        self.assertEqual(result.details["retry"]["enabled"], False)
        self.assertEqual(result.details["retry"]["policy_source"], "disabled_non_idempotent_method")

    def test_post_read_timeout_retries_with_explicit_retry_policy(self) -> None:
        session = _SequenceSession([requests.ReadTimeout("read timed out"), _response(200)])
        step = self._step(
            "POST",
            retry_policy=RequestRetryPolicy.from_mapping(
                {
                    "enabled": True,
                    "max_attempts": 2,
                    "backoff_seconds": 0,
                    "retry_on": ["read_timeout", "connection_error"],
                }
            ),
        )

        result = self._service(session).execute(step, self._prepared_request())

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertEqual(session.call_count, 2)
        self.assertEqual(result.details["retry"]["policy_source"], "step_retry_config")

    def test_connection_error_exhaustion_reports_attempts_and_last_error(self) -> None:
        session = _SequenceSession(
            [
                requests.ConnectionError("temporary connection reset"),
                requests.ConnectionError("still down"),
            ]
        )
        step = self._step(
            "GET",
            retry_policy=RequestRetryPolicy.from_mapping(
                {
                    "enabled": True,
                    "max_attempts": 2,
                    "backoff_seconds": 0,
                    "retry_on": ["connection_error"],
                }
            ),
        )

        result = self._service(session).execute(step, self._prepared_request())

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertEqual(session.call_count, 2)
        self.assertIn("after 2 attempt(s)", result.message)
        self.assertIn("still down", result.message)
        self.assertEqual(result.details["retry"]["final_attempt"], 2)
        self.assertEqual(result.details["retry"]["final_reason"], "connection_error")

    def test_configured_retry_on_503_status_can_succeed(self) -> None:
        session = _SequenceSession([_response(503), _response(200)])
        step = self._step(
            "GET",
            retry_policy=RequestRetryPolicy.from_mapping(
                {
                    "enabled": True,
                    "max_attempts": 2,
                    "backoff_seconds": 0,
                    "retry_on_statuses": [503],
                }
            ),
        )

        result = self._service(session).execute(step, self._prepared_request())

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertEqual(session.call_count, 2)
        self.assertEqual(result.details["retry"]["attempts"][0]["reason"], "http_503")
        self.assertTrue(result.details["retry"]["attempts"][0]["will_retry"])

    @staticmethod
    def _service(session: "_SequenceSession") -> ApiRequestService:
        return ApiRequestService(
            session=session,
            resolver=_passing_resolver,
            system_resolver_diagnostics=False,
            sleep_func=lambda delay: None,
            jitter_func=lambda upper_bound: 0,
        )

    @staticmethod
    def _step(method: str, retry_policy: RequestRetryPolicy | None = None) -> RequestStep:
        return RequestStep(
            method=method,
            path="/health",
            retry_policy=retry_policy or RequestRetryPolicy(configured=False),
        )

    @staticmethod
    def _prepared_request() -> PreparedRequest:
        return PreparedRequest(url="https://api.example.invalid/health", headers={})


class _SequenceSession:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.call_count = 0

    def request(self, method: str, url: str, **kwargs):
        self.call_count += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(status_code: int):
    response = requests.Response()
    response.status_code = status_code
    response.headers = {}
    response._content = b'{"ok": true}'
    return response


def _passing_resolver(hostname, port):
    return [(2, 1, 6, "", ("203.0.113.30", port or 443))]


if __name__ == "__main__":
    unittest.main()
