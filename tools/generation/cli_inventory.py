"""Support code for the generation CLI adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic
from tools.generation.persistence.artifacts import ENTITY_INVENTORY_FILENAME


def _load_yaml_inventory_file(path: Path, *, inventory_kind: str) -> tuple[dict[str, Any] | None, list[GenerationDiagnostic]]:
    if not path.exists():
        return None, [
            GenerationDiagnostic(
                code=f"adapter_{inventory_kind}_file_missing",
                message=f"{inventory_kind.replace('_', ' ').title()} file does not exist.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
            )
        ]
    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [
            GenerationDiagnostic(
                code=f"adapter_{inventory_kind}_invalid_yaml",
                message=f"{inventory_kind.replace('_', ' ').title()} file must contain valid YAML.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
                details={"error": str(exc)},
            )
        ]
    if not isinstance(payload, dict):
        return None, [
            GenerationDiagnostic(
                code=f"adapter_{inventory_kind}_not_object",
                message=f"{inventory_kind.replace('_', ' ').title()} file must contain a YAML object.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
            )
        ]
    return payload, []



def _validate_entity_inventory_file(path: Path) -> tuple[dict[str, Any] | None, list[GenerationDiagnostic]]:
    payload, diagnostics = _load_yaml_inventory_file(path, inventory_kind="entity_inventory")
    if payload is None:
        return None, diagnostics
    required_fields = ("version", "source_id", "project", "surface", "entities")
    missing_fields = [field_name for field_name in required_fields if field_name not in payload]
    if missing_fields:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_entity_inventory_missing_fields",
                message="Entity inventory is missing required top-level fields.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
                details={"missing_fields": missing_fields},
            )
        )
        return payload, diagnostics
    if not isinstance(payload.get("entities"), list):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_entity_inventory_entities_not_list",
                message="Entity inventory field 'entities' must be a YAML array.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
            )
        )
        return payload, diagnostics
    seen_names: set[str] = set()
    for index, item in enumerate(payload.get("entities", []), start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_entity_inventory_item_invalid",
                    message="Each entity inventory item must be a YAML object.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity_index": index},
                )
            )
            continue
        entity_name = str(item.get("name") or "").strip()
        if not entity_name:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_entity_inventory_name_missing",
                    message="Each entity inventory item must include name.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity_index": index},
                )
            )
            continue
        if entity_name in seen_names:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_entity_inventory_duplicate_name",
                    message="Entity inventory names must be unique.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity": entity_name},
                )
            )
        seen_names.add(entity_name)
        if not str(item.get("id_field") or "").strip():
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_entity_inventory_id_field_missing",
                    message="Each entity inventory item must include id_field.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity": entity_name},
                )
            )
    return payload, diagnostics



def _validate_operation_inventory_file(path: Path) -> tuple[dict[str, Any] | None, list[GenerationDiagnostic]]:
    payload, diagnostics = _load_yaml_inventory_file(path, inventory_kind="operation_inventory")
    if payload is None:
        return None, diagnostics
    allowed_same_state_behaviors = {"reject", "idempotent_success"}
    required_fields = ("version", "source_id", "project", "surface", "entity_operations", "routes")
    missing_fields = [field_name for field_name in required_fields if field_name not in payload]
    if missing_fields:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_operation_inventory_missing_fields",
                message="Operation inventory is missing required top-level fields.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(path),
                details={"missing_fields": missing_fields},
            )
        )
        return payload, diagnostics
    for field_name in ("entity_operations", "routes", "db_verifications"):
        if field_name in payload and not isinstance(payload.get(field_name), list):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_field_not_list",
                    message="Operation inventory list fields must be YAML arrays.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"field": field_name},
                )
            )
    entity_inventory_payload, entity_inventory_diagnostics = _validate_entity_inventory_file(path.parent / ENTITY_INVENTORY_FILENAME)
    entity_items = [] if entity_inventory_payload is None else entity_inventory_payload.get("entities", [])
    known_entities = {
        str(item.get("name")).strip()
        for item in entity_items
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    if path.parent / ENTITY_INVENTORY_FILENAME != path and (path.parent / ENTITY_INVENTORY_FILENAME).exists():
        diagnostics.extend(entity_inventory_diagnostics)
    for index, item in enumerate(payload.get("entity_operations", []), start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_operation_invalid",
                    message="Each entity operation inventory item must be a YAML object.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"operation_index": index},
                )
            )
            continue
        entity_name = str(item.get("entity") or "").strip()
        operation_name = str(item.get("operation") or "").strip()
        if not entity_name or not operation_name:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_operation_missing_fields",
                    message="Each entity operation must include entity and operation.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"operation_index": index},
                )
            )
        elif known_entities and entity_name not in known_entities:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_unknown_entity",
                    message="Entity operation references an entity not declared in entity-inventory.yaml.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity": entity_name, "operation": operation_name},
                )
            )
    for index, item in enumerate(payload.get("routes", []), start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_route_invalid",
                    message="Each route inventory item must be a YAML object.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
            continue
        method = str(item.get("method") or "").strip()
        route_path = str(item.get("path") or "").strip()
        if not method or not route_path:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_route_missing_fields",
                    message="Each route inventory item must include method and path.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
        if item.get("success_status") is not None and not isinstance(item.get("success_status"), int):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_success_status_invalid",
                    message="Route success_status must be an integer.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
        failure_statuses = item.get("failure_statuses", [])
        if failure_statuses is not None and not isinstance(failure_statuses, list):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_failure_statuses_invalid",
                    message="Route failure_statuses must be a YAML array when present.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
        target_state = item.get("target_state")
        if target_state is not None and not isinstance(target_state, str):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_target_state_invalid",
                    message="Route target_state must be a string when present.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
        same_state_behavior = item.get("same_state_behavior")
        normalized_same_state_behavior = (
            str(same_state_behavior).strip().lower()
            if isinstance(same_state_behavior, str)
            else ""
        )
        if same_state_behavior is not None and normalized_same_state_behavior not in allowed_same_state_behaviors:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_behavior_invalid",
                    message="Route same_state_behavior must be `reject` or `idempotent_success` when present.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_behavior": same_state_behavior},
                )
            )
        same_state_status = item.get("same_state_status")
        if same_state_status is not None and not isinstance(same_state_status, int):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_status_invalid",
                    message="Route same_state_status must be an integer when present.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index},
                )
            )
        if same_state_behavior is not None and same_state_status is None:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_contract_incomplete",
                    message="Route same_state_behavior requires same_state_status.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_behavior": same_state_behavior},
                )
            )
        if same_state_behavior is not None and not str(target_state or "").strip():
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_contract_incomplete",
                    message="Route same_state_behavior requires target_state so same-state lifecycle cases have an explicit source of truth.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_behavior": same_state_behavior},
                )
            )
        same_state_evidence = item.get("same_state_evidence")
        if same_state_behavior is not None and not _has_same_state_evidence(same_state_evidence):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_evidence_missing",
                    message=(
                        "Route same_state_behavior must include same_state_evidence with the code or test source "
                        "used to confirm whether reissuing the command rejects or succeeds idempotently."
                    ),
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_behavior": same_state_behavior},
                )
            )
        if isinstance(same_state_status, int) and normalized_same_state_behavior == "idempotent_success" and not (200 <= same_state_status < 300):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_contract_inconsistent",
                    message="same_state_behavior=idempotent_success requires a 2xx same_state_status.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_status": same_state_status},
                )
            )
        if isinstance(same_state_status, int) and normalized_same_state_behavior == "reject" and 200 <= same_state_status < 300:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_contract_inconsistent",
                    message="same_state_behavior=reject must not use a 2xx same_state_status.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_status": same_state_status},
                )
            )
        if (
            isinstance(same_state_status, int)
            and normalized_same_state_behavior == "reject"
            and isinstance(failure_statuses, list)
            and failure_statuses
            and same_state_status not in failure_statuses
        ):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_same_state_contract_inconsistent",
                    message="Rejecting same-state behavior must list same_state_status in failure_statuses.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"route_index": index, "same_state_status": same_state_status},
                )
            )
    for index, item in enumerate(payload.get("db_verifications", []), start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_db_verification_invalid",
                    message="Each db_verifications item must be a YAML object.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"db_verification_index": index},
                )
            )
            continue
        entity_name = str(item.get("entity") or "").strip()
        operation_name = str(item.get("operation") or "").strip()
        if not entity_name or not operation_name:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_db_verification_missing_fields",
                    message="Each db_verifications item must include entity and operation.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"db_verification_index": index},
                )
            )
        elif known_entities and entity_name not in known_entities:
            diagnostics.append(
                GenerationDiagnostic(
                    code="adapter_operation_inventory_unknown_entity",
                    message="DB verification references an entity not declared in entity-inventory.yaml.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(path),
                    details={"entity": entity_name, "operation": operation_name},
                )
            )
    return payload, diagnostics


def _has_same_state_evidence(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(isinstance(item, str) and item.strip() for item in value)
    return False

