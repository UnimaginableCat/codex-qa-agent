"""Loaders for DB tooling."""

from __future__ import annotations

from pathlib import Path

from tools.common import DotenvEnvLoader, ValidationError, read_json_file

from .models import DbEnvConfig, QueryStep


class DbEnvLoader:
    """Loads DB env configuration."""

    def __init__(self, dotenv_loader: DotenvEnvLoader | None = None) -> None:
        self._dotenv_loader = dotenv_loader or DotenvEnvLoader()

    def load(self, env_path: Path) -> DbEnvConfig:
        values = self._dotenv_loader.load(env_path)
        return DbEnvConfig.from_mapping(values)


class QueryStepLoader:
    """Loads and validates a DB query step definition."""

    def load(self, step_path: Path) -> QueryStep:
        payload = read_json_file(step_path, "Step")
        if not isinstance(payload, dict):
            raise ValidationError("Step JSON must be an object")

        return QueryStep.from_mapping(payload)
