"""Support code for the generation CLI adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.common.statuses import StepStatus
from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.persistence import managed_generation_artifacts_root_for_path
from tools.generation.persistence.artifacts import (
    AUTHORING_PLAN_FILENAME,
    CONTEXT_FILENAME,
    ENTITY_INVENTORY_FILENAME,
    OPERATION_INVENTORY_FILENAME,
)

LEGACY_AGENT_PLAN_ROOT = ("artifacts", "agent", "input")
MANAGED_AGENT_PLAN_ROOT = ("artifacts", "agent", "generation")


class GenerationCliInputError(ValueError):
    def __init__(self, diagnostics: list[GenerationDiagnostic]) -> None:
        super().__init__("Invalid generation CLI input.")
        self.diagnostics = diagnostics



def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result



def _path_under_root(path: Path, root_parts: tuple[str, ...]) -> bool:
    parts = tuple(part.lower() for part in path.parts)
    width = len(root_parts)
    return any(parts[index:index + width] == root_parts for index in range(len(parts) - width + 1))



def _managed_bundle_dir_for_authoring_path(path: Path) -> Path | None:
    resolved = path.resolve()
    if managed_generation_artifacts_root_for_path(resolved) is None:
        return None
    if resolved.is_dir():
        return resolved
    if resolved.is_file() and resolved.name == AUTHORING_PLAN_FILENAME:
        return resolved.parent
    return None



def _resolve_bundle_dir(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_dir():
        return resolved
    if resolved.is_file() and resolved.name in {
        CONTEXT_FILENAME,
        AUTHORING_PLAN_FILENAME,
        ENTITY_INVENTORY_FILENAME,
        OPERATION_INVENTORY_FILENAME,
    }:
        return resolved.parent
    return resolved



def _highest_priority_status(statuses: list[StepStatus]) -> StepStatus:
    if StepStatus.ERROR in statuses:
        return StepStatus.ERROR
    if StepStatus.BLOCKED in statuses:
        return StepStatus.BLOCKED
    if StepStatus.FAIL in statuses:
        return StepStatus.FAIL
    return StepStatus.PASS

