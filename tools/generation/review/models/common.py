"""Shared helpers for review contract models."""

from __future__ import annotations

from pathlib import Path


def _optional_path(value: object) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))
