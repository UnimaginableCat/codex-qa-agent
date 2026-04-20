"""Environment loading helpers."""

from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

from .errors import EnvFileLoadError


class DotenvEnvLoader:
    """Loads env values from a dotenv file."""

    def load(self, env_path: Path) -> dict[str, str | None]:
        if not env_path.exists():
            raise EnvFileLoadError(f"Env file does not exist: {env_path}")

        try:
            values = dotenv_values(env_path)
        except Exception as exc:  # noqa: BLE001
            raise EnvFileLoadError(f"Failed to load env file '{env_path}': {exc}") from exc

        return {str(key): value for key, value in values.items()}
