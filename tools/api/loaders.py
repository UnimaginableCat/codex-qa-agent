"""Loaders for API tooling."""

from __future__ import annotations

from pathlib import Path

from tools.common import DotenvEnvLoader, ValidationError, read_json_file

from .models import EnvConfig, RequestStep


class ApiEnvLoader:
    """Loads API env configuration."""

    def __init__(self, dotenv_loader: DotenvEnvLoader | None = None) -> None:
        self._dotenv_loader = dotenv_loader or DotenvEnvLoader()

    def load(self, env_path: Path, actor: str | None = None) -> EnvConfig:
        values = self._dotenv_loader.load(env_path)
        actor_suffix = self._actor_suffix(actor)
        selected_base_url_key = self._select_key(values, "API_BASE_URL", actor_suffix)
        scoped_values = self._overlay_actor_values(values, actor_suffix)
        raw_base_url = self._read_raw_env_value(env_path, selected_base_url_key)
        if raw_base_url is not None:
            scoped_values["__RAW_API_BASE_URL"] = raw_base_url
        return EnvConfig.from_mapping(
            scoped_values,
            actor=actor,
            api_base_url_key=selected_base_url_key,
        )

    @staticmethod
    def _overlay_actor_values(values: dict[str, str | None], actor_suffix: str | None) -> dict[str, str | None]:
        if not actor_suffix:
            return dict(values)

        scoped = dict(values)
        for base_key in (
            "API_BASE_URL",
            "API_AUTH_TYPE",
            "API_BEARER_TOKEN",
            "API_USERNAME",
            "API_PASSWORD",
            "API_BASIC_USERNAME",
            "API_BASIC_PASSWORD",
            "BASIC_AUTH_USERNAME",
            "BASIC_AUTH_PASSWORD",
        ):
            actor_key = f"{base_key}__{actor_suffix}"
            if actor_key in values:
                scoped[base_key] = values[actor_key]
        return scoped

    @staticmethod
    def _select_key(values: dict[str, str | None], base_key: str, actor_suffix: str | None) -> str:
        if not actor_suffix:
            return base_key
        actor_key = f"{base_key}__{actor_suffix}"
        if actor_key in values:
            return actor_key
        return base_key

    @staticmethod
    def _actor_suffix(actor: str | None) -> str | None:
        if actor is None:
            return None
        normalized = "".join(char.upper() if char.isalnum() else "_" for char in actor.strip())
        normalized = "_".join(part for part in normalized.split("_") if part)
        return normalized or None

    @staticmethod
    def _read_raw_env_value(env_path: Path, key: str) -> str | None:
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            return None

        prefix = f"{key}="
        for line in lines:
            stripped_line = line.lstrip()
            if stripped_line.startswith(prefix):
                return stripped_line[len(prefix):]
        return None


class RequestStepLoader:
    """Loads and validates an API request step definition."""

    def load(self, step_path: Path) -> RequestStep:
        payload = read_json_file(step_path, "Step")
        if not isinstance(payload, dict):
            raise ValidationError("Step JSON must be an object")

        return RequestStep.from_mapping(payload)
