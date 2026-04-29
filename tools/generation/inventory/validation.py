"""Top-level staged inventory validation orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.inventory.db import _db_verification_inventory_diagnostics
from tools.generation.inventory.entity import (
    _known_entity_names,
    _validate_entity_inventory_file,
)
from tools.generation.inventory.entity_operations import (
    _declared_route_specs,
    _entity_operation_inventory_diagnostics,
)
from tools.generation.inventory.routes import _route_inventory_diagnostics
from tools.generation.inventory.common import (
    _diagnostic,
    _list_payload_items,
    _load_yaml_inventory_file,
    _missing_required_fields,
    _project_path_diagnostics,
)
from tools.generation.persistence.artifacts import ENTITY_INVENTORY_FILENAME


_OPERATION_INVENTORY_REQUIRED_FIELDS = (
    "version",
    "source_id",
    "project",
    "surface",
    "entity_operations",
    "routes",
)
_OPERATION_INVENTORY_LIST_FIELDS = ("entity_operations", "routes", "db_verifications")


def _validate_operation_inventory_file(path: Path) -> tuple[dict[str, Any] | None, list[GenerationDiagnostic]]:
    payload, diagnostics = _load_yaml_inventory_file(path, inventory_kind="operation_inventory")
    if payload is None:
        return None, diagnostics

    missing_fields = _missing_required_fields(payload, _OPERATION_INVENTORY_REQUIRED_FIELDS)
    if missing_fields:
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_missing_fields",
                message="Operation inventory is missing required top-level fields.",
                path=path,
                details={"missing_fields": missing_fields},
            )
        )
        return payload, diagnostics

    diagnostics.extend(_project_path_diagnostics(payload, path=path, inventory_kind="operation_inventory"))
    diagnostics.extend(_operation_inventory_list_field_diagnostics(payload, path=path))

    known_entities, entity_inventory_diagnostics = _known_entities_from_sibling_inventory(path)
    diagnostics.extend(entity_inventory_diagnostics)

    route_specs = _declared_route_specs(payload)
    diagnostics.extend(
        _entity_operation_inventory_diagnostics(
            _list_payload_items(payload, "entity_operations"),
            path=path,
            known_entities=known_entities,
            route_specs=route_specs,
        )
    )
    diagnostics.extend(_route_inventory_diagnostics(_list_payload_items(payload, "routes"), path=path))
    diagnostics.extend(
        _db_verification_inventory_diagnostics(
            _list_payload_items(payload, "db_verifications"),
            path=path,
            known_entities=known_entities,
        )
    )
    return payload, diagnostics


def _operation_inventory_list_field_diagnostics(
    payload: dict[str, Any],
    *,
    path: Path,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    for field_name in _OPERATION_INVENTORY_LIST_FIELDS:
        if field_name in payload and not isinstance(payload.get(field_name), list):
            diagnostics.append(
                _diagnostic(
                    code="adapter_operation_inventory_field_not_list",
                    message="Operation inventory list fields must be YAML arrays.",
                    path=path,
                    details={"field": field_name},
                )
            )
    return diagnostics


def _known_entities_from_sibling_inventory(path: Path) -> tuple[set[str], list[GenerationDiagnostic]]:
    entity_inventory_path = path.parent / ENTITY_INVENTORY_FILENAME
    entity_inventory_payload, entity_inventory_diagnostics = _validate_entity_inventory_file(entity_inventory_path)
    if entity_inventory_path != path and entity_inventory_path.exists():
        diagnostics = entity_inventory_diagnostics
    else:
        diagnostics = []
    return _known_entity_names(entity_inventory_payload), diagnostics


__all__ = [
    "_load_yaml_inventory_file",
    "_validate_entity_inventory_file",
    "_validate_operation_inventory_file",
]
