"""Loaders for DB tooling."""

from __future__ import annotations

from pathlib import Path

from tools.common import DotenvEnvLoader, ValidationError, read_json_file

from .models import DbEnvConfig, QueryStep


class DbEnvLoader:
    """Loads DB env configuration."""

    def __init__(self, dotenv_loader: DotenvEnvLoader | None = None) -> None:
        self._dotenv_loader = dotenv_loader or DotenvEnvLoader()

    def load(self, env_path: Path, actor: str | None = None) -> DbEnvConfig:
        values = self._dotenv_loader.load(env_path)
        actor_suffix = self._actor_suffix(actor)
        selected_database_url_key = self._select_key(values, "DATABASE_URL", actor_suffix)
        scoped_values = self._overlay_actor_values(values, actor_suffix)
        return DbEnvConfig.from_mapping(
            scoped_values,
            actor=actor,
            database_url_key=selected_database_url_key,
        )

    @staticmethod
    def _overlay_actor_values(values: dict[str, str | None], actor_suffix: str | None) -> dict[str, str | None]:
        if not actor_suffix:
            return dict(values)

        scoped = dict(values)
        for base_key in (
            "DATABASE_URL",
            "DATABASE_USER",
            "DATABASE_PASSWORD",
            "DB_USER",
            "DB_PASSWORD",
            "PGUSER",
            "PGPASSWORD",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
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


class QueryStepLoader:
    """Loads and validates a DB query step definition."""

    def load(self, step_path: Path) -> QueryStep:
        payload = read_json_file(step_path, "Step")
        if not isinstance(payload, dict):
            raise ValidationError("Step JSON must be an object")

        return QueryStep.from_mapping(payload)
