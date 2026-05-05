"""Shared helpers for generation review logic."""

from __future__ import annotations

from tools.common.slugging import stable_slug


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

def _slugify(value: str) -> str:
    return stable_slug(value, fallback="scenario")
