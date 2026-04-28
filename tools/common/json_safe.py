"""JSON-safe value normalization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID


def to_json_safe(value: Any) -> Any:
    """Recursively normalize common Python values to JSON-compatible values."""

    if value is None:
        return value
    if isinstance(value, Enum):
        return to_json_safe(value.value)
    if isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return to_json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {_to_json_safe_key(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_json_safe(item) for item in value]
    if isinstance(value, set | frozenset):
        return [to_json_safe(item) for item in value]
    return value


def _to_json_safe_key(key: Any) -> str | int | float | bool | None:
    normalized_key = to_json_safe(key)
    if normalized_key is None or isinstance(normalized_key, str | int | float | bool):
        return normalized_key
    return str(normalized_key)
