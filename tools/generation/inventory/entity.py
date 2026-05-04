"""Entity inventory validation rules."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.domain.models import DiagnosticSeverity
from tools.generation.inventory.common import (
    _diagnostic,
    _load_yaml_inventory_file,
    _missing_required_fields,
    _project_path_diagnostics,
)


_ENTITY_INVENTORY_REQUIRED_FIELDS = ("version", "source_id", "project", "surface", "entities")
_DEFAULT_SUSPICIOUS_ID_FIELD_PATTERNS = (
    r"(?:^|_)(?:company_)?member_guid$",
    r"(?:^|_)user_guid$",
)
_DEFAULT_COMPOSITE_ENTITY_NAME_PATTERNS = (
    r"(?:^|_)(?:permission|permissions|override|overrides|assignment|assignments|grant|grants|access)(?:_|$)",
)


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

    diagnostics.extend(
        _entity_inventory_item_diagnostics(
            entities,
            path=path,
            identity_policy=_entity_identity_policy(payload),
        )
    )
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


def _entity_inventory_item_diagnostics(
    items: list[Any],
    *,
    path: Path,
    identity_policy: dict[str, Any],
) -> list[GenerationDiagnostic]:
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

        id_field = str(item.get("id_field") or "").strip()
        if not id_field:
            diagnostics.append(
                _diagnostic(
                    code="adapter_entity_inventory_id_field_missing",
                    message="Each entity inventory item must include id_field.",
                    path=path,
                    details={"entity": entity_name},
                )
            )
        else:
            identity_risk = _foreign_identity_id_field_risk(
                entity_name=entity_name,
                id_field=id_field,
                key_fields=_string_list(item.get("key_fields")),
                policy=identity_policy,
            )
            if identity_risk is None:
                continue
            explicitly_allowed = _id_field_allowed(entity_name=entity_name, id_field=id_field, policy=identity_policy)
            override_allowed = explicitly_allowed and identity_policy["allow_suspicious_id_field_override"]
            strict = (
                identity_policy["enforcement"] == "error"
                or (not override_allowed and identity_risk == "composite_entity")
                or (explicitly_allowed and not override_allowed)
            )
            if explicitly_allowed and not strict:
                diagnostics.append(
                    _diagnostic(
                        code="adapter_entity_inventory_suspicious_identity_id_field_allowed",
                        message=(
                            "Entity id_field matches the suspicious identity-field policy and was allowed by "
                            "an explicit unsafe override. Prefer an entity-owned id_field plus key_fields."
                        ),
                        path=path,
                        severity=DiagnosticSeverity.WARNING,
                        details={
                            "entity": entity_name,
                            "id_field": id_field,
                            "policy": identity_policy["source"],
                            "risk": identity_risk,
                            "justification": identity_policy["justification"],
                        },
                    )
                )
                continue
            diagnostics.append(
                _diagnostic(
                    code=(
                        "adapter_entity_inventory_suspicious_identity_id_field_disallowed"
                        if strict
                        else "adapter_entity_inventory_suspicious_identity_id_field"
                    ),
                    message=(
                        "Entity id_field matches the configured suspicious identity-field policy. "
                        "Keep the canonical entity id_field and declare natural/composite identity in key_fields."
                    ),
                    path=path,
                    severity=DiagnosticSeverity.ERROR if strict else DiagnosticSeverity.WARNING,
                    details={
                        "entity": entity_name,
                        "id_field": id_field,
                        "policy": identity_policy["source"],
                        "risk": identity_risk,
                        "suggestion": (
                            "Use an entity-owned id_field, then include relationship/actor variables in key_fields "
                            "when they form the natural key. For a genuinely intentional unsafe exception, document "
                            "the field in metadata.identity_field_policy.allow_id_fields and also set "
                            "allow_suspicious_id_field_override: true with a justification."
                        ),
                    },
                )
            )
    return diagnostics


def _entity_identity_policy(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    raw_policy = metadata.get("identity_field_policy") if isinstance(metadata.get("identity_field_policy"), dict) else {}
    disable_default_id_patterns = bool(raw_policy.get("disable_default_suspicious_id_field_patterns"))
    disable_default_entity_patterns = bool(raw_policy.get("disable_default_composite_entity_patterns"))
    return {
        "source": "metadata.identity_field_policy",
        "enforcement": _identity_policy_enforcement(raw_policy.get("enforcement")),
        "allow_id_fields": _string_set(raw_policy.get("allow_id_fields")),
        "allow_suspicious_id_field_override": bool(raw_policy.get("allow_suspicious_id_field_override"))
        and bool(str(raw_policy.get("justification") or "").strip()),
        "justification": str(raw_policy.get("justification") or "").strip(),
        "suspicious_id_field_patterns": (
            []
            if disable_default_id_patterns
            else list(_DEFAULT_SUSPICIOUS_ID_FIELD_PATTERNS)
        )
        + _string_list(raw_policy.get("suspicious_id_field_patterns")),
        "composite_entity_patterns": (
            []
            if disable_default_entity_patterns
            else list(_DEFAULT_COMPOSITE_ENTITY_NAME_PATTERNS)
        )
        + _string_list(raw_policy.get("composite_entity_patterns")),
    }


def _identity_policy_enforcement(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"error", "block", "blocked", "strict", "disallow"}:
        return "error"
    return "warn"


def _foreign_identity_id_field_risk(
    *,
    entity_name: str,
    id_field: str,
    key_fields: list[str],
    policy: dict[str, Any],
) -> str | None:
    if not _matches_any_pattern(id_field, policy["suspicious_id_field_patterns"]):
        return None
    if _matches_any_pattern(entity_name, policy["composite_entity_patterns"]):
        return "composite_entity"
    if len([field for field in key_fields if field.strip()]) > 1:
        return "composite_key"
    return None


def _id_field_allowed(*, entity_name: str, id_field: str, policy: dict[str, Any]) -> bool:
    values = {id_field.strip().lower(), f"{entity_name.strip().lower()}.{id_field.strip().lower()}"}
    allowed = {value.strip().lower() for value in policy["allow_id_fields"]}
    return bool(values & allowed)


def _matches_any_pattern(value: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        try:
            if re.search(pattern, value.strip(), re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def _string_set(value: Any) -> set[str]:
    return set(_string_list(value))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if str(item).strip()]
    return []
