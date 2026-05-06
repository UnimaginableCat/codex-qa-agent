"""Shared permission effect parsing helpers for authoring diagnostics."""

from __future__ import annotations

from typing import Any

from ...models import AuthoringEntityOperation


def _operation_permission_effects(operation: AuthoringEntityOperation) -> list[dict[str, str]]:
    effects: list[dict[str, str]] = []
    for item in operation.permission_state_effects:
        key = _permission_key(item)
        if not key:
            continue
        effect = {
            "key": key,
            "state": _permission_state_value(item),
            "actor": str(item.get("actor") or "").strip(),
            "subject": str(
                item.get("subject")
                or item.get("subject_variable")
                or item.get("principal")
                or item.get("principal_variable")
                or item.get("captured_variable")
                or ""
            ).strip(),
            "resource": str(item.get("resource") or "").strip(),
            "mode": str(item.get("mode") or item.get("action") or "").strip().lower(),
        }
        effects.append({field: value for field, value in effect.items() if value})
    return effects


def _permission_key(item: dict[str, Any]) -> str:
    return str(item.get("key") or item.get("permission") or item.get("name") or "").strip()


def _permission_state_value(item: dict[str, Any]) -> str:
    for key in ("state", "value"):
        if key in item and item.get(key) is not None:
            return str(item.get(key)).strip().lower()
    return ""
