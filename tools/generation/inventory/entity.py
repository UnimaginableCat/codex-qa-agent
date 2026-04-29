"""Entity inventory validation rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.inventory.common import (
    _diagnostic,
    _load_yaml_inventory_file,
    _missing_required_fields,
    _project_path_diagnostics,
)


_ENTITY_INVENTORY_REQUIRED_FIELDS = ("version", "source_id", "project", "surface", "entities")


def _validate_entity_inventory_file(path: Path) -> tuple[dict[str, Any] | None, list[GenerationDiagnostic]]:
    payload, diagnostics = _load_yaml_inventory_file(path, inventory_kind="entity_inventory")
    if payload is None:
        return None, diagnostics

    missing_fields = _missing_required_fields(payload, _ENTITY_INVENTORY_REQUIRED_FIELDS)
    if missing_fields:
        diagnostics.append(
            _diagnostic(
                code="adapter_entity_inventory_missing_fields",
                message="Entity inventory is missing required top-level fields.",
                path=path,
                details={"missing_fields": missing_fields},
            )
        )
        return payload, diagnostics

    diagnostics.extend(_project_path_diagnostics(payload, path=path, inventory_kind="entity_inventory"))
    entities = payload.get("entities")
    if not isinstance(entities, list):
        diagnostics.append(
            _diagnostic(
                code="adapter_entity_inventory_entities_not_list",
                message="Entity inventory field 'entities' must be a YAML array.",
                path=path,
            )
        )
        return payload, diagnostics

    diagnostics.extend(_entity_inventory_item_diagnostics(entities, path=path))
    return payload, diagnostics


def _known_entity_names(entity_inventory_payload: dict[str, Any] | None) -> set[str]:
    if entity_inventory_payload is None:
        return set()
    entity_items = entity_inventory_payload.get("entities", [])
    return {
        str(item.get("name")).strip()
        for item in entity_items
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }


def _entity_inventory_item_diagnostics(items: list[Any], *, path: Path) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    seen_names: set[str] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                _diagnostic(
                    code="adapter_entity_inventory_item_invalid",
                    message="Each entity inventory item must be a YAML object.",
                    path=path,
                    details={"entity_index": index},
                )
            )
            continue

        entity_name = str(item.get("name") or "").strip()
        if not entity_name:
            diagnostics.append(
                _diagnostic(
                    code="adapter_entity_inventory_name_missing",
                    message="Each entity inventory item must include name.",
                    path=path,
                    details={"entity_index": index},
                )
            )
            continue

        if entity_name in seen_names:
            diagnostics.append(
                _diagnostic(
                    code="adapter_entity_inventory_duplicate_name",
                    message="Entity inventory names must be unique.",
                    path=path,
                    details={"entity": entity_name},
                )
            )
        seen_names.add(entity_name)

        if not str(item.get("id_field") or "").strip():
            diagnostics.append(
                _diagnostic(
                    code="adapter_entity_inventory_id_field_missing",
                    message="Each entity inventory item must include id_field.",
                    path=path,
                    details={"entity": entity_name},
                )
            )
    return diagnostics
