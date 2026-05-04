"""Shared helpers for staged inventory validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic


def _diagnostic(
    *,
    code: str,
    message: str,
    path: Path,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    details: dict[str, Any] | None = None,
) -> GenerationDiagnostic:
    return GenerationDiagnostic(
        code=code,
        message=message,
        severity=severity,
        source_ref=str(path),
        details=details,
    )


def _load_yaml_inventory_file(path: Path, *, inventory_kind: str) -> tuple[dict[str, Any] | None, list[GenerationDiagnostic]]:
    if not path.exists():
        return None, [
            _diagnostic(
                code=f"adapter_{inventory_kind}_file_missing",
                message=f"{inventory_kind.replace('_', ' ').title()} file does not exist.",
                path=path,
            )
        ]
    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [
            _diagnostic(
                code=f"adapter_{inventory_kind}_invalid_yaml",
                message=f"{inventory_kind.replace('_', ' ').title()} file must contain valid YAML.",
                path=path,
                details={"error": str(exc)},
            )
        ]
    if not isinstance(payload, dict):
        return None, [
            _diagnostic(
                code=f"adapter_{inventory_kind}_not_object",
                message=f"{inventory_kind.replace('_', ' ').title()} file must contain a YAML object.",
                path=path,
            )
        ]
    return payload, []


def _missing_required_fields(payload: dict[str, Any], required_fields: tuple[str, ...]) -> list[str]:
    return [field_name for field_name in required_fields if field_name not in payload]


def _list_payload_items(payload: dict[str, Any], field_name: str) -> list[Any]:
    value = payload.get(field_name, [])
    return value if isinstance(value, list) else []


def _unknown_entity_diagnostic(
    *,
    path: Path,
    entity_name: str,
    operation_name: str,
    message: str,
) -> GenerationDiagnostic:
    return _diagnostic(
        code="adapter_operation_inventory_unknown_entity",
        message=message,
        path=path,
        details={"entity": entity_name, "operation": operation_name},
    )


def _project_path_diagnostics(
    payload: dict[str, Any],
    *,
    path: Path,
    inventory_kind: str,
) -> list[GenerationDiagnostic]:
    project = str(payload.get("project") or "").strip()
    if not project:
        return []
    normalized = project.replace("\\", "/").strip("/")
    if normalized.startswith("code/") and len(normalized.split("/", 1)[1].strip()) > 0:
        return []
    return [
        _diagnostic(
            code=f"adapter_{inventory_kind}_project_must_target_code_subdir",
            message=f"{inventory_kind.replace('_', ' ').title()} project must point at a workspace project under code/<project>.",
            path=path,
            details={"project": project},
        )
    ]


def _is_valid_request_constraints(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        if not str(item.get("field") or "").strip():
            return False
        if not str(item.get("format") or "").strip():
            return False
        if item.get("when") is not None and not isinstance(item.get("when"), dict):
            return False
    return True


def _is_valid_capture_rule_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        capture = str(item or "").strip()
        if not capture or "->" not in capture:
            return False
        source, target = capture.split("->", 1)
        if not source.strip() or not target.strip():
            return False
    return True


def _is_string_mapping(value: Any) -> bool:
    return isinstance(value, dict) and all(str(key).strip() and str(item).strip() for key, item in value.items())


def _is_valid_optional_state_or_state_list(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(isinstance(item, str) and item.strip() for item in value)
    return False
