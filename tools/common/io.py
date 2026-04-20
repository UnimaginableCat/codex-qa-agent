"""Shared file I/O helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import JsonFileLoadError


def read_json_file(path: Path, description: str) -> Any:
    """Read and parse a JSON file."""

    if not path.exists():
        raise JsonFileLoadError(f"{description} file does not exist: {path}")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise JsonFileLoadError(f"Failed to parse {description.lower()} '{path}': {exc}") from exc


def write_text_file(path: Path, content: str) -> None:
    """Write text content to a file, creating parent directories when needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
