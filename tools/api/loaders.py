"""Loaders for API tooling."""

from __future__ import annotations

from pathlib import Path

from tools.common import DotenvEnvLoader, ValidationError, read_json_file

from .models import EnvConfig, RequestStep


class ApiEnvLoader:
    """Loads API env configuration."""

    def __init__(self, dotenv_loader: DotenvEnvLoader | None = None) -> None:
        self._dotenv_loader = dotenv_loader or DotenvEnvLoader()

    def load(self, env_path: Path) -> EnvConfig:
        values = self._dotenv_loader.load(env_path)
        raw_base_url = self._read_raw_env_value(env_path, "API_BASE_URL")
        if raw_base_url is not None:
            values["__RAW_API_BASE_URL"] = raw_base_url
        return EnvConfig.from_mapping(values)

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
