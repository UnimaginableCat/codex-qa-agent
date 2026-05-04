"""DB verification validation rules for operation inventory files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.inventory.common import (
    _diagnostic,
    _is_string_mapping,
    _unknown_entity_diagnostic,
)


def _db_verification_inventory_diagnostics(
    items: list[Any],
    *,
    path: Path,
    known_entities: set[str],
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                _diagnostic(
                    code="adapter_operation_inventory_db_verification_invalid",
                    message="Each db_verifications item must be a YAML object.",
                    path=path,
                    details={"db_verification_index": index},
                )
            )
            continue

        entity_name = str(item.get("entity") or "").strip()
        operation_name = str(item.get("operation") or "").strip()
        if not entity_name or not operation_name:
            diagnostics.append(
                _diagnostic(
                    code="adapter_operation_inventory_db_verification_missing_fields",
                    message="Each db_verifications item must include entity and operation.",
                    path=path,
                    details={"db_verification_index": index},
                )
            )
        elif known_entities and entity_name not in known_entities:
            diagnostics.append(
                _unknown_entity_diagnostic(
                    path=path,
                    entity_name=entity_name,
                    operation_name=operation_name,
                    message="DB verification references an entity not declared in entity-inventory.yaml.",
                )
            )

        column_types = item.get("column_types")
        if column_types is not None and not _is_string_mapping(column_types):
            diagnostics.append(
                _diagnostic(
                    code="adapter_operation_inventory_column_types_invalid",
                    message="DB verification column_types must be a YAML object mapping column names to type names.",
                    path=path,
                    details={"db_verification_index": index, "entity": entity_name, "operation": operation_name},
                )
            )
        diagnostics.extend(
            _db_verification_executable_diagnostics(
                item,
                path=path,
                db_verification_index=index,
            )
        )
    return diagnostics


def _db_verification_executable_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    db_verification_index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    entity_name = str(item.get("entity") or "").strip()
    operation_name = str(item.get("operation") or "").strip()
    scoped_by = _normalized_scoped_by_fields(item.get("scoped_by"))
    sql = str(item.get("sql") or "").strip()
    params = item.get("params")
    expected_outcomes = item.get("expected_outcomes")
    missing_fields: list[str] = []
    if not sql:
        missing_fields.append("sql")
    if not isinstance(params, dict) or any(field_name not in params for field_name in scoped_by):
        missing_fields.append("params")
    if not isinstance(expected_outcomes, list) or not all(str(item).strip() for item in expected_outcomes):
        missing_fields.append("expected_outcomes")
    if missing_fields:
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_db_verification_template_incomplete",
                message="DB verification must include executable sql, params keyed by scoped_by, and expected_outcomes before use in persisted-state checks.",
                path=path,
                details={
                    "db_verification_index": db_verification_index,
                    "entity": entity_name,
                    "operation": operation_name,
                    "missing_fields": missing_fields,
                },
            )
        )
    return diagnostics


def _normalized_scoped_by_fields(value: Any) -> list[str]:
    if isinstance(value, list):
        return [field_name for item in value if (field_name := str(item or "").strip())]
    field_name = str(value or "").strip()
    return [field_name] if field_name else []
