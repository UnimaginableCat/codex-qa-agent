"""Loading helpers for compact authoring-plan files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised via runtime environment, not unit tests
    yaml = None

from tools.generation.domain.models import GenerationDiagnostic

from .diagnostics import authoring_diagnostic
from .models import (
    AUTHORING_STATE_CHANGE_ALLOWED_TEXT,
    AuthoringPlan,
    AuthoringPlanLoadResult,
    AuthoringStateChange,
    normalize_state_change_value,
)


class AuthoringPlanLoader:
    """Load YAML-first authoring-plan files into typed authoring models."""

    def load(self, file_path: Path) -> AuthoringPlanLoadResult:
        diagnostics: list[GenerationDiagnostic] = []
        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_plan_file_missing",
                    "Authoring-plan file does not exist.",
                    source_ref=str(file_path),
                )
            )
            return AuthoringPlanLoadResult(file_path=file_path, diagnostics=diagnostics)
        except OSError as exc:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_plan_file_unreadable",
                    "Authoring-plan file could not be read.",
                    source_ref=str(file_path),
                    details={"error": str(exc)},
                )
            )
            return AuthoringPlanLoadResult(file_path=file_path, diagnostics=diagnostics)
        suffix = file_path.suffix.lower()
        if suffix in {".yaml", ".yml"} and yaml is None:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_yaml_dependency_missing",
                    "PyYAML is required to load authoring-plan YAML files.",
                    source_ref=str(file_path),
                )
            )
            return AuthoringPlanLoadResult(file_path=file_path, diagnostics=diagnostics)
        try:
            if suffix in {".yaml", ".yml"}:
                assert yaml is not None
                payload = yaml.safe_load(raw_text)
            elif suffix == ".json":
                payload = json.loads(raw_text)
            else:
                if yaml is None:
                    diagnostics.append(
                        authoring_diagnostic(
                            "authoring_yaml_dependency_missing",
                            "PyYAML is required to load non-JSON authoring-plan files.",
                            source_ref=str(file_path),
                        )
                    )
                    return AuthoringPlanLoadResult(file_path=file_path, diagnostics=diagnostics)
                assert yaml is not None
                payload = yaml.safe_load(raw_text)
        except Exception as exc:
            if yaml is not None and isinstance(exc, yaml.YAMLError):
                diagnostics.append(
                    authoring_diagnostic(
                        "authoring_plan_file_invalid_yaml",
                        "Authoring-plan file must contain valid YAML.",
                        source_ref=str(file_path),
                        details={"error": str(exc)},
                    )
                )
                return AuthoringPlanLoadResult(file_path=file_path, diagnostics=diagnostics)
            if isinstance(exc, json.JSONDecodeError):
                diagnostics.append(
                    authoring_diagnostic(
                        "authoring_plan_file_invalid_json",
                        "Authoring-plan JSON file must contain valid JSON.",
                        source_ref=str(file_path),
                        details={"error": str(exc)},
                    )
                )
                return AuthoringPlanLoadResult(file_path=file_path, diagnostics=diagnostics)
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_plan_file_unreadable",
                    "Authoring-plan file could not be parsed.",
                    source_ref=str(file_path),
                    details={"error": str(exc)},
                )
            )
            return AuthoringPlanLoadResult(file_path=file_path, diagnostics=diagnostics)

        diagnostics.extend(_validate_payload_shape(payload, str(file_path)))
        if diagnostics:
            return AuthoringPlanLoadResult(file_path=file_path, diagnostics=diagnostics)
        return AuthoringPlanLoadResult(
            file_path=file_path,
            authoring_plan=AuthoringPlan.from_dict(payload),
            diagnostics=[],
        )


def _validate_payload_shape(payload: Any, source_ref: str) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not isinstance(payload, dict):
        return [
            authoring_diagnostic(
                "authoring_payload_not_object",
                "Authoring-plan file must contain a YAML or JSON object.",
                source_ref=source_ref,
            )
        ]
    if payload.get("scope") is not None and not isinstance(payload.get("scope"), dict):
        diagnostics.append(
            authoring_diagnostic(
                "authoring_field_not_object",
                "Field 'scope' must be a JSON object.",
                source_ref=source_ref,
                details={"field": "scope"},
            )
        )
    if payload.get("defaults") is not None and not isinstance(payload.get("defaults"), dict):
        diagnostics.append(
            authoring_diagnostic(
                "authoring_field_not_object",
                "Field 'defaults' must be a JSON object.",
                source_ref=source_ref,
                details={"field": "defaults"},
            )
        )
    defaults_payload = payload.get("defaults")
    if isinstance(defaults_payload, dict):
        diagnostics.extend(
            _validate_scenario_variables_shape(
                defaults_payload.get("scenario_variables"),
                source_ref,
                field_path="defaults.scenario_variables",
            )
        )
    if payload.get("entities") is not None and not isinstance(payload.get("entities"), dict):
        diagnostics.append(
            authoring_diagnostic(
                "authoring_field_not_object",
                "Field 'entities' must be a JSON object.",
                source_ref=source_ref,
                details={"field": "entities"},
            )
        )
    if payload.get("cases") is not None and not isinstance(payload.get("cases"), list):
        diagnostics.append(
            authoring_diagnostic(
                "authoring_field_not_list",
                "Field 'cases' must be a JSON array.",
                source_ref=source_ref,
                details={"field": "cases"},
            )
        )
    if isinstance(payload.get("cases"), list):
        for case_index, case_payload in enumerate(payload.get("cases", []), start=1):
            if not isinstance(case_payload, dict):
                continue
            case_id = str(case_payload.get("id") or f"case-{case_index:03d}")
            diagnostics.extend(
                _validate_scenario_variables_shape(
                    case_payload.get("scenario_variables"),
                    source_ref,
                    field_path=f"cases[{case_index}].scenario_variables",
                    owner=case_id,
                )
            )
            diagnostics.extend(
                _validate_state_change_field(
                    case_payload.get("state_change"),
                    source_ref,
                    field_path=f"cases[{case_index}].state_change",
                    owner=case_id,
                )
            )
            diagnostics.extend(
                _validate_permission_state_shape(
                    case_payload.get("required_permission_state"),
                    source_ref,
                    field_path=f"cases[{case_index}].required_permission_state",
                    owner=case_id,
                )
            )
    for field_name in ("assumptions", "open_questions"):
        value = payload.get(field_name)
        if value is not None and not isinstance(value, list):
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_field_not_list",
                    f"Field '{field_name}' must be a JSON array.",
                    source_ref=source_ref,
                    details={"field": field_name},
                )
            )
    return diagnostics


def _validate_permission_state_shape(
    value: Any,
    source_ref: str,
    *,
    field_path: str,
    owner: str,
) -> list[GenerationDiagnostic]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [
            authoring_diagnostic(
                "authoring_permission_state_contract_invalid",
                "required_permission_state must be a YAML array of objects.",
                source_ref=source_ref,
                details={"field": field_path, "owner": owner},
            )
        ]
    diagnostics: list[GenerationDiagnostic] = []
    for item_index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_permission_state_contract_invalid",
                    "Each required_permission_state entry must be a YAML object.",
                    source_ref=source_ref,
                    details={"field": field_path, "owner": owner, "item_index": item_index},
                )
            )
            continue
        if not str(item.get("key") or item.get("permission") or item.get("name") or "").strip():
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_permission_state_contract_invalid",
                    "Each required_permission_state entry must include key, permission, or name.",
                    source_ref=source_ref,
                    details={"field": field_path, "owner": owner, "item_index": item_index},
                )
            )
    return diagnostics


def _validate_state_change_field(
    value: Any,
    source_ref: str,
    *,
    field_path: str,
    owner: str,
) -> list[GenerationDiagnostic]:
    normalized = normalize_state_change_value(value)
    if not normalized:
        return []
    if AuthoringStateChange.from_raw(value) is not None:
        return []
    return [
        authoring_diagnostic(
            "authoring_unknown_state_change",
            f"Authoring case state_change must be one of {AUTHORING_STATE_CHANGE_ALLOWED_TEXT}.",
            source_ref=source_ref,
            details={
                "field": field_path,
                "owner": owner,
                "state_change": value,
                "allowed_values": list(AuthoringStateChange.allowed_values()),
            },
        )
    ]


def _validate_scenario_variables_shape(
    value: Any,
    source_ref: str,
    *,
    field_path: str,
    owner: str | None = None,
) -> list[GenerationDiagnostic]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [
            authoring_diagnostic(
                "authoring_scenario_variable_entry_invalid",
                "scenario_variables must be a YAML array of strings.",
                source_ref=source_ref,
                details={"field": field_path, **({} if owner is None else {"owner": owner})},
            )
        ]
    diagnostics: list[GenerationDiagnostic] = []
    for item_index, item in enumerate(value, start=1):
        if isinstance(item, str):
            continue
        diagnostics.append(
            authoring_diagnostic(
                "authoring_scenario_variable_entry_invalid",
                (
                    "Each scenario_variables entry must be a string. Quote the whole variable definition and use "
                    "source prefixes without a space, for example "
                    "'\"display_name = template:Invalid Update {{run_suffix}}\"'."
                ),
                source_ref=source_ref,
                details={
                    "field": f"{field_path}[{item_index}]",
                    "entry_type": type(item).__name__,
                    **({} if owner is None else {"owner": owner}),
                },
            )
        )
    return diagnostics
