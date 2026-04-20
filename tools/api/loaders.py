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
        return EnvConfig.from_mapping(values)


class RequestStepLoader:
    """Loads and validates an API request step definition."""

    def load(self, step_path: Path) -> RequestStep:
        payload = read_json_file(step_path, "Step")
        if not isinstance(payload, dict):
            raise ValidationError("Step JSON must be an object")

        return RequestStep.from_mapping(payload)
