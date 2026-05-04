"""Suppression helpers for inventory-backed authoring diagnostics."""

from __future__ import annotations

from pathlib import Path

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.persistence.artifacts import managed_generation_artifacts_root_for_path

from .indexes import _has_explicit_same_state_contract, _route_inventory_specs, _route_path_shape
from .loading import _load_operation_inventory_payload


def suppress_inventory_backed_same_state_warnings(
    *,
    file_path: Path,
    diagnostics: list[GenerationDiagnostic],
) -> list[GenerationDiagnostic]:
    if managed_generation_artifacts_root_for_path(file_path) is None:
        return diagnostics
    operation_inventory = _load_operation_inventory_payload(file_path)
    if operation_inventory is None:
        return diagnostics
    route_specs = _route_inventory_specs(operation_inventory)
    same_state_route_shapes = {
        route_shape
        for (_, route_shape), route_spec in route_specs.items()
        if _has_explicit_same_state_contract(route_spec)
    }
    filtered: list[GenerationDiagnostic] = []
    for diagnostic in diagnostics:
        if diagnostic.code != "authoring_same_state_lifecycle_contract_unconfirmed":
            filtered.append(diagnostic)
            continue
        route_shape = _route_path_shape(str(diagnostic.details.get("route_path") or ""))
        if route_shape not in same_state_route_shapes:
            filtered.append(diagnostic)
    return filtered
