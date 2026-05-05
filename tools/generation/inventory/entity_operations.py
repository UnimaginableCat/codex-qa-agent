"""Entity operation validation rules for operation inventory files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.inventory.common import (
    _diagnostic,
    _is_valid_capture_rule_list,
    _unknown_entity_diagnostic,
)


def _declared_route_specs(payload: dict[str, Any]) -> set[tuple[str, str]]:
    route_specs: set[tuple[str, str]] = set()
    for item in payload.get("routes", []):
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "").strip().upper()
        route_path = str(item.get("path") or "").strip()
        if method and route_path:
            route_specs.add((method, route_path))
    return route_specs


def _entity_operation_inventory_diagnostics(
    items: list[Any],
    *,
    path: Path,
    known_entities: set[str],
    route_specs: set[tuple[str, str]],
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                _diagnostic(
                    code="adapter_operation_inventory_operation_invalid",
                    message="Each entity operation inventory item must be a YAML object.",
                    path=path,
                    details={"operation_index": index},
                )
            )
            continue

        entity_name = str(item.get("entity") or "").strip()
        operation_name = str(item.get("operation") or "").strip()
        if not entity_name or not operation_name:
            diagnostics.append(
                _diagnostic(
                    code="adapter_operation_inventory_operation_missing_fields",
                    message="Each entity operation must include entity and operation.",
                    path=path,
                    details={"operation_index": index},
                )
            )
        elif known_entities and entity_name not in known_entities:
            diagnostics.append(
                _unknown_entity_diagnostic(
                    path=path,
                    entity_name=entity_name,
                    operation_name=operation_name,
                    message="Entity operation references an entity not declared in entity-inventory.yaml.",
                )
            )

        diagnostics.extend(
            _entity_operation_executable_diagnostics(
                item,
                path=path,
                operation_index=index,
                route_specs=route_specs,
            )
        )
    return diagnostics


def _entity_operation_executable_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    operation_index: int,
    route_specs: set[tuple[str, str]],
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    entity_name = str(item.get("entity") or "").strip()
    operation_name = str(item.get("operation") or "").strip()
    route_payload = item.get("route") if isinstance(item.get("route"), dict) else {}
    method = str(route_payload.get("method") or item.get("method") or "").strip().upper()
    route_path = str(route_payload.get("path") or item.get("path") or "").strip()
    sql = str(item.get("sql") or "").strip()

    if not ((method and route_path) or sql):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_operation_template_missing",
                message="Entity operation must include an executable route or SQL template before it can be used for workflow setup.",
                path=path,
                details={"operation_index": operation_index, "entity": entity_name, "operation": operation_name},
            )
        )
    if method and route_path and route_specs and (method, route_path) not in route_specs:
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_operation_route_undeclared",
                message="Entity operation route must be declared in operation-inventory routes so route/status contracts stay synchronized.",
                path=path,
                details={
                    "operation_index": operation_index,
                    "entity": entity_name,
                    "operation": operation_name,
                    "method": method,
                    "path": route_path,
                },
            )
        )
    captures = item.get("captures")
    if captures is not None and not _is_valid_capture_rule_list(captures):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_capture_rule_invalid",
                message="Entity operation captures must use explicit '<source> -> <variable>' rules; bare variable names are ambiguous.",
                path=path,
                details={"operation_index": operation_index, "entity": entity_name, "operation": operation_name},
            )
        )
    permission_state_effects = item.get("permission_state_effects")
    if permission_state_effects is not None and not _is_valid_permission_state_effects(permission_state_effects):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_permission_state_effects_invalid",
                message="permission_state_effects must be a YAML array of objects with key, permission, or name.",
                path=path,
                details={"operation_index": operation_index, "entity": entity_name, "operation": operation_name},
            )
        )
    return diagnostics


def _is_valid_permission_state_effects(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        if not str(item.get("key") or item.get("permission") or item.get("name") or "").strip():
            return False
    return True
