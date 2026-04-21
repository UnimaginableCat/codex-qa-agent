"""Authentication strategies for API requests."""

from __future__ import annotations

from typing import Protocol

from requests.auth import HTTPBasicAuth

from .errors import AuthConfigurationError
from .models import AuthType, EnvConfig, PreparedRequest


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

        if _has_authorization_header(prepared_request.headers):
            return
        prepared_request.headers["Authorization"] = f"Bearer {env.api_bearer_token}"


class BasicAuthStrategy:
    def apply(self, env: EnvConfig, prepared_request: PreparedRequest) -> None:
        if not env.api_username:
            raise AuthConfigurationError("API_AUTH_TYPE=basic but API_USERNAME is missing")
        if env.api_password is None:
            raise AuthConfigurationError("API_AUTH_TYPE=basic but API_PASSWORD is missing")

        # Scenario-provided Authorization is intentional input and wins over env-driven auth.
        if _has_authorization_header(prepared_request.headers):
            return
        prepared_request.auth = HTTPBasicAuth(env.api_username, env.api_password)


class AuthStrategyFactory:
    """Builds auth strategies from environment configuration."""

    def __init__(self, strategies: dict[AuthType, AuthStrategy] | None = None) -> None:
        self._strategies = strategies or {
            AuthType.NONE: NoAuthStrategy(),
            AuthType.BEARER: BearerTokenAuthStrategy(),
            AuthType.BASIC: BasicAuthStrategy(),
        }

    def create(self, env: EnvConfig) -> AuthStrategy:
        try:
            return self._strategies[env.auth_type]
        except KeyError as exc:
            raise AuthConfigurationError(f"Unsupported auth type: {env.auth_type}") from exc


def _has_authorization_header(headers: dict[str, str]) -> bool:
    return any(str(header_name).lower() == "authorization" for header_name in headers)
