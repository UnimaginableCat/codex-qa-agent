"""Stage inventory loading and shape diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.persistence.artifacts import (
    ENTITY_INVENTORY_FILENAME,
    OPERATION_INVENTORY_FILENAME,
    managed_generation_artifacts_root_for_path,
)

from ..diagnostics import authoring_diagnostic


ENTITY_INVENTORY_CONTRACT = (
    ENTITY_INVENTORY_FILENAME,
    ("version", "source_id", "project", "surface", "entities"),
    {"entities"},
)
OPERATION_INVENTORY_CONTRACT = (
    OPERATION_INVENTORY_FILENAME,
    ("version", "source_id", "project", "surface", "entity_operations", "routes"),
    {"entity_operations", "routes", "db_verifications"},
)


def _required_stage_inventory_diagnostics(file_path: Path) -> list[GenerationDiagnostic]:
    if managed_generation_artifacts_root_for_path(file_path) is None:
        return []
    inventory_specs = (
        ("entity_inventory", file_path.parent / ENTITY_INVENTORY_FILENAME, *ENTITY_INVENTORY_CONTRACT[1:]),
        ("operation_inventory", file_path.parent / OPERATION_INVENTORY_FILENAME, *OPERATION_INVENTORY_CONTRACT[1:]),
    )
    diagnostics: list[GenerationDiagnostic] = []
    for inventory_kind, inventory_path, required_fields, list_fields in inventory_specs:
        diagnostics.extend(
            _inventory_file_diagnostics(
                inventory_kind=inventory_kind,
                inventory_path=inventory_path,
                required_fields=required_fields,
                list_fields=list_fields,
            )
        )
    return diagnostics


def _inventory_file_diagnostics(
    *,
    inventory_kind: str,
    inventory_path: Path,
    required_fields: tuple[str, ...],
    list_fields: set[str],
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not inventory_path.exists():
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_missing",
                "Managed authoring bundles require staged inventory files before authoring-plan validation or compile.",
                source_ref=str(inventory_path),
                details={"inventory_kind": inventory_kind, "path": str(inventory_path)},
            )
        )
        return diagnostics
    try:
        import yaml

        payload = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
    except Exception as exc:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_invalid",
                "Staged inventory file could not be parsed as YAML.",
                source_ref=str(inventory_path),
                details={"inventory_kind": inventory_kind, "path": str(inventory_path), "error": str(exc)},
            )
        )
        return diagnostics
    if not isinstance(payload, dict):
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_invalid",
                "Staged inventory file must contain a YAML object.",
                source_ref=str(inventory_path),
                details={"inventory_kind": inventory_kind, "path": str(inventory_path)},
            )
        )
        return diagnostics
    missing_fields = [field_name for field_name in required_fields if field_name not in payload]
    if missing_fields:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_invalid",
                "Staged inventory file is missing required top-level fields.",
                source_ref=str(inventory_path),
                details={
                    "inventory_kind": inventory_kind,
                    "path": str(inventory_path),
                    "missing_fields": missing_fields,
                },
            )
        )
    for field_name in list_fields:
        if field_name in payload and not isinstance(payload.get(field_name), list):
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_stage_inventory_invalid",
                    "Staged inventory list fields must be YAML arrays.",
                    source_ref=str(inventory_path),
                    details={
                        "inventory_kind": inventory_kind,
                        "path": str(inventory_path),
                        "field": field_name,
                    },
                )
            )
    return diagnostics


def _load_entity_inventory_payload(bundle_file_path: Path) -> dict[str, Any] | None:
    return _load_inventory_payload_if_valid(
        inventory_path=bundle_file_path.parent / ENTITY_INVENTORY_FILENAME,
        required_fields=ENTITY_INVENTORY_CONTRACT[1],
        list_fields=ENTITY_INVENTORY_CONTRACT[2],
    )


def _load_operation_inventory_payload(bundle_file_path: Path) -> dict[str, Any] | None:
    return _load_inventory_payload_if_valid(
        inventory_path=bundle_file_path.parent / OPERATION_INVENTORY_FILENAME,
        required_fields=OPERATION_INVENTORY_CONTRACT[1],
        list_fields=OPERATION_INVENTORY_CONTRACT[2],
    )


def _load_inventory_payload_if_valid(
    *,
    inventory_path: Path,
    required_fields: tuple[str, ...],
    list_fields: set[str],
) -> dict[str, Any] | None:
    if not inventory_path.exists():
        return None
    try:
        import yaml

        payload = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if any(field_name not in payload for field_name in required_fields):
        return None
    if any(field_name in payload and not isinstance(payload.get(field_name), list) for field_name in list_fields):
        return None
    return payload
