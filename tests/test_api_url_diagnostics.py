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
    requests.ConnectionError = _RequestException
    requests.Timeout = _RequestException
    requests.SSLError = _RequestException
    requests.Response = _Response
    requests.Session = object
    requests_auth = types.ModuleType("requests.auth")
    requests_auth.HTTPBasicAuth = object
    requests.auth = requests_auth
    sys.modules["requests"] = requests
    sys.modules["requests.auth"] = requests_auth

try:
    import dotenv  # noqa: F401
except ModuleNotFoundError:
    dotenv = types.ModuleType("dotenv")
    dotenv.dotenv_values = lambda env_path: {}
    sys.modules["dotenv"] = dotenv

from tools.api.auth import AuthStrategyFactory
from tools.api.models import EnvConfig, RequestStep
from tools.api.services import ApiRequestBuilder, ApiRequestService
from tools.common.statuses import StepStatus


class ApiUrlDiagnosticsTests(unittest.TestCase):
    def test_api_base_url_with_trailing_spaces_is_sanitized(self) -> None:
        result = self._execute_with_base_url(" https://app2.101-group.ru  ")

        self.assertEqual(result.status, StepStatus.PASS)
        debug = result.details["request_debug"]
        self.assertEqual(debug["base_url_repr"], "'https://app2.101-group.ru'")
        self.assertEqual(debug["final_url_repr"], "'https://app2.101-group.ru/api/price_list/'")
        self.assertEqual(debug["parsed_hostname"], "app2.101-group.ru")

    def test_api_base_url_with_trailing_cr_is_sanitized(self) -> None:
        result = self._execute_with_base_url("https://app2.101-group.ru\r")

        self.assertEqual(result.status, StepStatus.PASS)
        debug = result.details["request_debug"]
        self.assertEqual(debug["base_url_repr"], "'https://app2.101-group.ru'")
        self.assertEqual(debug["hostname_repr"], "'app2.101-group.ru'")

    def test_api_base_url_wrapped_in_quotes_is_sanitized(self) -> None:
        result = self._execute_with_base_url('"https://app2.101-group.ru"')

        self.assertEqual(result.status, StepStatus.PASS)
        debug = result.details["request_debug"]
        self.assertEqual(debug["base_url_repr"], "'https://app2.101-group.ru'")
        self.assertEqual(debug["final_url_repr"], "'https://app2.101-group.ru/api/price_list/'")

    def test_final_url_debug_fields_are_present(self) -> None:
        result = self._execute_with_base_url("https://app2.101-group.ru")

        debug = result.details["request_debug"]
        for key in (
            "base_url_repr",
            "path_repr",
            "final_url_repr",
            "parsed_scheme",
            "parsed_netloc",
            "parsed_hostname",
            "parsed_port",
            "hostname_repr",
            "base_url_env_key",
            "getaddrinfo",
        ):
            self.assertIn(key, debug)
        self.assertEqual(debug["base_url_env_key"], "API_BASE_URL")
        self.assertEqual(debug["getaddrinfo"]["status"], StepStatus.PASS.value)

    def test_hostname_precheck_failure_returns_blocked_with_structured_diagnostics(self) -> None:
        env = EnvConfig.from_mapping({"API_BASE_URL": "https://bad.example.local"})
        step = RequestStep(method="GET", path="/api/price_list/")
        prepared = self._builder().build(env, step)

        result = ApiRequestService(session=_RecordingSession(), resolver=_failing_resolver).execute(step, prepared)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        debug = result.details["request_debug"]
        self.assertEqual(debug["hostname_repr"], "'bad.example.local'")
        self.assertEqual(debug["final_url_repr"], "'https://bad.example.local/api/price_list/'")
        self.assertEqual(debug["getaddrinfo"]["status"], StepStatus.BLOCKED.value)
        self.assertEqual(debug["getaddrinfo"]["error_type"], "OSError")

    def _execute_with_base_url(self, raw_base_url: str):
        env = EnvConfig.from_mapping({"API_BASE_URL": raw_base_url, "API_AUTH_TYPE": "none"})
        step = RequestStep(method="GET", path="/api/price_list/")
        prepared = self._builder().build(env, step)
        return ApiRequestService(session=_RecordingSession(), resolver=_passing_resolver).execute(step, prepared)

    @staticmethod
    def _builder() -> ApiRequestBuilder:
        return ApiRequestBuilder(auth_strategy_factory=AuthStrategyFactory())


class _RecordingSession:
    def request(self, method: str, url: str, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.headers = {}
        response._content = b"{}"
        return response


def _passing_resolver(hostname, port):
    return [(2, 1, 6, "", ("203.0.113.30", port or 443))]


def _failing_resolver(hostname, port):
    raise OSError("mock getaddrinfo failure")


if __name__ == "__main__":
    unittest.main()
