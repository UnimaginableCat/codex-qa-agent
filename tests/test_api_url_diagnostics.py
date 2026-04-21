from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys
import types
import unittest
from unittest.mock import patch

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
        self.assertEqual(debug["env_base_url_raw_value"], " https://app2.101-group.ru  ")
        self.assertEqual(debug["env_base_url_normalized_value"], "https://app2.101-group.ru")
        self.assertEqual(debug["base_url_value"], "https://app2.101-group.ru")
        self.assertEqual(debug["base_url_repr"], "'https://app2.101-group.ru'")
        self.assertEqual(debug["final_url_value"], "https://app2.101-group.ru/api/price_list/")
        self.assertEqual(debug["final_url_repr"], "'https://app2.101-group.ru/api/price_list/'")
        self.assertEqual(debug["parsed_hostname"], "app2.101-group.ru")

    def test_api_base_url_with_trailing_cr_is_sanitized(self) -> None:
        result = self._execute_with_base_url("https://app2.101-group.ru\r")

        self.assertEqual(result.status, StepStatus.PASS)
        debug = result.details["request_debug"]
        self.assertEqual(debug["env_base_url_raw_value"], "https://app2.101-group.ru\r")
        self.assertEqual(debug["env_base_url_normalized_value"], "https://app2.101-group.ru")
        self.assertEqual(debug["base_url_repr"], "'https://app2.101-group.ru'")
        self.assertEqual(debug["hostname_value"], "app2.101-group.ru")
        self.assertEqual(debug["hostname_repr"], "'app2.101-group.ru'")

    def test_api_base_url_wrapped_in_quotes_is_sanitized(self) -> None:
        result = self._execute_with_base_url('"https://app2.101-group.ru"')

        self.assertEqual(result.status, StepStatus.PASS)
        debug = result.details["request_debug"]
        self.assertEqual(debug["env_base_url_raw_value"], '"https://app2.101-group.ru"')
        self.assertEqual(debug["env_base_url_normalized_value"], "https://app2.101-group.ru")
        self.assertEqual(debug["base_url_repr"], "'https://app2.101-group.ru'")
        self.assertEqual(debug["final_url_repr"], "'https://app2.101-group.ru/api/price_list/'")

    def test_final_url_debug_fields_are_present(self) -> None:
        result = self._execute_with_base_url("https://app2.101-group.ru")

        debug = result.details["request_debug"]
        for key in (
            "env_base_url_raw_value",
            "env_base_url_raw_repr",
            "env_base_url_normalized_value",
            "env_base_url_normalized_repr",
            "base_url_value",
            "base_url_repr",
            "normalized_base_url_value",
            "normalized_base_url_repr",
            "path_value",
            "path_repr",
            "final_url_value",
            "final_url_repr",
            "parsed_scheme",
            "parsed_netloc",
            "parsed_hostname",
            "parsed_port",
            "hostname_value",
            "hostname_repr",
            "base_url_env_key",
            "dns_precheck",
            "getaddrinfo",
            "gethostbyname",
            "getfqdn",
            "resolver_debug",
            "process_debug",
            "resolv_conf",
            "getent_hosts",
            "nslookup",
            "ping",
            "hosts_file",
            "resolver_comparison",
        ):
            self.assertIn(key, debug)
        self.assertEqual(debug["base_url_env_key"], "API_BASE_URL")
        self.assertEqual(debug["hostname_value"], "app2.101-group.ru")
        self.assertEqual(debug["hostname_repr"], "'app2.101-group.ru'")
        self.assertEqual(debug["parsed_port"], 443)
        self.assertEqual(debug["dns_precheck"]["getaddrinfo"]["status"], StepStatus.PASS.value)
        self.assertEqual(debug["getaddrinfo"]["status"], StepStatus.PASS.value)
        self.assertIn("sample_results", debug["dns_precheck"]["getaddrinfo"])
        self.assertIn("resolved_addresses", debug["dns_precheck"]["getaddrinfo"])
        self.assertIn("sys_executable", debug["process_debug"])
        self.assertIn("hostname", debug["process_debug"])
        self.assertIn("fqdn", debug["process_debug"])
        self.assertIn("resolv_conf", debug["resolver_debug"])
        self.assertIn("nslookup", debug["resolver_debug"])
        self.assertIn("ping", debug["resolver_debug"])
        self.assertIn("hosts_file", debug["resolver_debug"])
        self.assertEqual(debug["resolver_comparison"]["python_getaddrinfo"], "see request_debug.dns_precheck.getaddrinfo")

    def test_hostname_precheck_failure_returns_blocked_with_structured_diagnostics(self) -> None:
        env = EnvConfig.from_mapping({"API_BASE_URL": "https://bad.example.local"})
        step = RequestStep(method="GET", path="/api/price_list/")
        prepared = self._builder().build(env, step)

        result = ApiRequestService(
            session=_RecordingSession(),
            resolver=_failing_resolver,
            system_resolver_diagnostics=False,
        ).execute(step, prepared)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        debug = result.details["request_debug"]
        self.assertEqual(debug["hostname_value"], "bad.example.local")
        self.assertEqual(debug["hostname_repr"], "'bad.example.local'")
        self.assertEqual(debug["final_url_value"], "https://bad.example.local/api/price_list/")
        self.assertEqual(debug["final_url_repr"], "'https://bad.example.local/api/price_list/'")
        self.assertEqual(debug["dns_precheck"]["status"], StepStatus.BLOCKED.value)
        self.assertEqual(debug["getaddrinfo"]["status"], StepStatus.BLOCKED.value)
        self.assertEqual(debug["getaddrinfo"]["error_type"], "OSError")

    def test_resolver_command_results_are_structured(self) -> None:
        env = EnvConfig.from_mapping({"API_BASE_URL": "https://app2.101-group.ru"})
        step = RequestStep(method="GET", path="/api/price_list/")
        prepared = self._builder().build(env, step)

        with patch("tools.api.services.shutil.which", side_effect=_fake_which):
            with patch("tools.api.services.subprocess.run", side_effect=_fake_subprocess_run):
                result = ApiRequestService(session=_RecordingSession(), resolver=_passing_resolver).execute(step, prepared)

        debug = result.details["request_debug"]
        self.assertEqual(debug["getent_hosts"]["status"], StepStatus.PASS.value)
        self.assertEqual(debug["nslookup"]["status"], StepStatus.PASS.value)
        self.assertEqual(debug["ping"]["status"], StepStatus.BLOCKED.value)
        self.assertEqual(debug["resolver_comparison"]["system_getent_status"], StepStatus.PASS.value)
        self.assertEqual(debug["resolver_comparison"]["system_nslookup_status"], StepStatus.PASS.value)
        self.assertEqual(debug["resolver_comparison"]["system_ping_status"], StepStatus.BLOCKED.value)

    def test_request_debug_does_not_include_auth_secrets(self) -> None:
        env = EnvConfig.from_mapping(
            {
                "API_BASE_URL": "https://app2.101-group.ru",
                "API_AUTH_TYPE": "bearer",
                "API_BEARER_TOKEN": "very-secret-token",
                "API_USERNAME": "user",
                "API_PASSWORD": "very-secret-password",
            }
        )
        step = RequestStep(method="GET", path="/api/price_list/")
        prepared = self._builder().build(env, step)

        with patch.dict(
            "os.environ",
            {"HTTP_PROXY": "http://proxy-user:proxy-password@proxy.local:8080"},
        ):
            result = ApiRequestService(
                session=_RecordingSession(),
                resolver=_passing_resolver,
                system_resolver_diagnostics=False,
            ).execute(step, prepared)

        debug_text = json.dumps(result.details["request_debug"], ensure_ascii=False)
        self.assertNotIn("very-secret-token", debug_text)
        self.assertNotIn("very-secret-password", debug_text)
        self.assertNotIn("Authorization", debug_text)
        self.assertNotIn("proxy-password", debug_text)
        self.assertIn("http://<redacted>@proxy.local:8080", debug_text)

    def _execute_with_base_url(self, raw_base_url: str):
        env = EnvConfig.from_mapping({"API_BASE_URL": raw_base_url, "API_AUTH_TYPE": "none"})
        step = RequestStep(method="GET", path="/api/price_list/")
        prepared = self._builder().build(env, step)
        return ApiRequestService(
            session=_RecordingSession(),
            resolver=_passing_resolver,
            system_resolver_diagnostics=False,
        ).execute(step, prepared)

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


def _fake_which(command: str) -> str | None:
    if command in {"getent", "nslookup", "ping"}:
        return f"/usr/bin/{command}"
    return None


def _fake_subprocess_run(command, **kwargs):
    if command[0].endswith("getent"):
        return SimpleNamespace(returncode=0, stdout="203.0.113.30 app2.101-group.ru\n", stderr="")
    if command[0].endswith("nslookup"):
        return SimpleNamespace(returncode=0, stdout="Name: app2.101-group.ru\nAddress: 203.0.113.30\n", stderr="")
    if command[0].endswith("ping"):
        return SimpleNamespace(returncode=2, stdout="", stderr="ping: app2.101-group.ru: Temporary failure\n")
    return SimpleNamespace(returncode=127, stdout="", stderr="not found")


if __name__ == "__main__":
    unittest.main()
