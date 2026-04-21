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

    class HTTPBasicAuth:
        def __init__(self, username: str, password: str) -> None:
            self.username = username
            self.password = password

    requests_auth.HTTPBasicAuth = HTTPBasicAuth
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

from tools.api.auth import AuthStrategyFactory
from tools.api.models import EnvConfig, RequestStep
from tools.api.services import ApiRequestBuilder, ApiRequestRunner, ApiRequestService
from tools.common.errors import ValidationError
from tools.common.statuses import StepStatus


class ApiAuthTests(unittest.TestCase):
    def test_basic_auth_env_attaches_requests_auth(self) -> None:
        step = self._step()
        env = EnvConfig.from_mapping(
            {
                "API_BASE_URL": "https://api.example.local",
                "API_AUTH_TYPE": "basic",
                "API_USERNAME": "user",
                "API_PASSWORD": "password",
            }
        )

        prepared = self._builder().build(env, step)
        session = _RecordingSession()
        result = ApiRequestService(session=session, resolver=_passing_resolver).execute(step, prepared)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertIsNotNone(prepared.auth)
        self.assertIs(session.last_kwargs["auth"], prepared.auth)
        self.assertNotIn("Authorization", prepared.headers)

    def test_basic_auth_aliases_are_supported(self) -> None:
        env = EnvConfig.from_mapping(
            {
                "API_BASE_URL": "https://api.example.local",
                "API_AUTH_TYPE": "basic",
                "API_BASIC_USERNAME": "user",
                "API_BASIC_PASSWORD": "password",
            }
        )

        prepared = self._builder().build(env, self._step())

        self.assertIsNotNone(prepared.auth)

    def test_bearer_auth_env_attaches_bearer_header(self) -> None:
        step = self._step()
        env = EnvConfig.from_mapping(
            {
                "API_BASE_URL": "https://api.example.local",
                "API_AUTH_TYPE": "bearer",
                "API_BEARER_TOKEN": "token-value",
            }
        )

        prepared = self._builder().build(env, step)
        session = _RecordingSession()
        result = ApiRequestService(session=session, resolver=_passing_resolver).execute(step, prepared)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertEqual(session.last_kwargs["headers"]["Authorization"], "Bearer token-value")
        self.assertNotIn("auth", session.last_kwargs)

    def test_explicit_authorization_header_overrides_basic_env_auth(self) -> None:
        step = self._step(headers={"authorization": "Custom abc"})
        env = EnvConfig.from_mapping(
            {
                "API_BASE_URL": "https://api.example.local",
                "API_AUTH_TYPE": "basic",
                "API_USERNAME": "user",
                "API_PASSWORD": "password",
            }
        )

        prepared = self._builder().build(env, step)
        session = _RecordingSession()
        result = ApiRequestService(session=session, resolver=_passing_resolver).execute(step, prepared)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertIsNone(prepared.auth)
        self.assertNotIn("auth", session.last_kwargs)
        self.assertEqual(session.last_kwargs["headers"]["authorization"], "Custom abc")

    def test_explicit_authorization_header_overrides_bearer_env_auth(self) -> None:
        step = self._step(headers={"Authorization": "Custom abc"})
        env = EnvConfig.from_mapping(
            {
                "API_BASE_URL": "https://api.example.local",
                "API_AUTH_TYPE": "bearer",
                "API_BEARER_TOKEN": "token-value",
            }
        )

        prepared = self._builder().build(env, step)

        self.assertEqual(prepared.headers["Authorization"], "Custom abc")

    def test_basic_auth_missing_username_returns_blocked(self) -> None:
        result = self._run_with_env(
            {
                "API_BASE_URL": "https://api.example.local",
                "API_AUTH_TYPE": "basic",
                "API_PASSWORD": "password",
            }
        )

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertIn("API_USERNAME is missing", result.message)
        self.assertNotIn("password", result.message)

    def test_basic_auth_missing_password_returns_blocked(self) -> None:
        result = self._run_with_env(
            {
                "API_BASE_URL": "https://api.example.local",
                "API_AUTH_TYPE": "basic",
                "API_USERNAME": "user",
            }
        )

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertIn("API_PASSWORD is missing", result.message)
        self.assertNotIn("user", result.message)

    def test_unsupported_auth_type_returns_blocked(self) -> None:
        result = ApiRequestRunner(
            env_loader=_FailingEnvLoader(
                ValidationError("Unsupported API_AUTH_TYPE 'digest'. Expected one of: none, bearer, basic")
            ),
            step_loader=_StaticStepLoader(self._step()),
            request_builder=self._builder(),
            request_service=ApiRequestService(session=_RecordingSession(), resolver=_passing_resolver),
        ).run(Path("env"), Path("step"))

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertIn("Unsupported API_AUTH_TYPE 'digest'", result.message)

    def test_no_auth_configured_sends_request_without_auth(self) -> None:
        step = self._step()
        env = EnvConfig.from_mapping(
            {
                "API_BASE_URL": "https://api.example.local",
                "API_AUTH_TYPE": "none",
            }
        )

        prepared = self._builder().build(env, step)
        session = _RecordingSession()
        result = ApiRequestService(session=session, resolver=_passing_resolver).execute(step, prepared)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertNotIn("auth", session.last_kwargs)
        self.assertNotIn("Authorization", session.last_kwargs["headers"])

    def _run_with_env(self, env_values: dict[str, str]):
        return ApiRequestRunner(
            env_loader=_StaticEnvLoader(EnvConfig.from_mapping(env_values)),
            step_loader=_StaticStepLoader(self._step()),
            request_builder=self._builder(),
            request_service=ApiRequestService(session=_RecordingSession(), resolver=_passing_resolver),
        ).run(Path("env"), Path("step"))

    @staticmethod
    def _builder() -> ApiRequestBuilder:
        return ApiRequestBuilder(auth_strategy_factory=AuthStrategyFactory())

    @staticmethod
    def _step(headers: dict[str, str] | None = None) -> RequestStep:
        return RequestStep(method="GET", path="/health", headers=headers or {})


class _RecordingSession:
    def __init__(self) -> None:
        self.last_method = None
        self.last_url = None
        self.last_kwargs = None

    def request(self, method: str, url: str, **kwargs):
        self.last_method = method
        self.last_url = url
        self.last_kwargs = kwargs
        response = requests.Response()
        response.status_code = 200
        response.headers = {}
        response._content = b"{}"
        return response


class _StaticEnvLoader:
    def __init__(self, env: EnvConfig) -> None:
        self._env = env

    def load(self, env_path: Path) -> EnvConfig:
        return self._env


class _FailingEnvLoader:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def load(self, env_path: Path):
        raise self._exc


class _StaticStepLoader:
    def __init__(self, step: RequestStep) -> None:
        self._step = step

    def load(self, step_path: Path) -> RequestStep:
        return self._step


def _passing_resolver(hostname, port):
    return [(2, 1, 6, "", ("203.0.113.10", port or 443))]


if __name__ == "__main__":
    unittest.main()
