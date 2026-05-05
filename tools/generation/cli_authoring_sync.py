"""Support code for the generation CLI adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.common.io import write_text_file
from tools.generation.authoring_contract.models import (
    AuthoringDefaults,
    AuthoringEntityOperation,
    AuthoringEntitySpec,
    AuthoringOracle,
    AuthoringPlan,
    AuthoringRoute,
    AuthoringScope,
)
from tools.generation.cli_core import GenerationCliInputError
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic
from tools.generation.persistence import FileGenerationArtifactStore
from tools.generation.persistence.artifacts import AUTHORING_PLAN_FILENAME, load_generation_run_context_from_bundle_dir


def _sync_authoring_plan_from_inventories(
    *,
    existing_plan: AuthoringPlan,
    entity_inventory: dict[str, Any],
    operation_inventory: dict[str, Any],
) -> AuthoringPlan:
    entity_items = [
        item for item in entity_inventory.get("entities", []) if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    route_specs = _route_specs_by_key(operation_inventory)
    existing_entities = dict(existing_plan.entities)
    synced_entities: dict[str, AuthoringEntitySpec] = {}
    for entity_item in entity_items:
        entity_name = str(entity_item.get("name") or "").strip()
        existing_entity = existing_entities.get(entity_name, AuthoringEntitySpec())
        synced_entities[entity_name] = AuthoringEntitySpec(
            id_field=str(entity_item.get("id_field") or existing_entity.id_field or "").strip(),
            key_fields=_string_list_from_payload(entity_item.get("key_fields"), fallback=existing_entity.key_fields),
            operations={},
        )

    for operation_item in operation_inventory.get("entity_operations", []):
        if not isinstance(operation_item, dict):
            continue
        entity_name = str(operation_item.get("entity") or "").strip()
        operation_name = str(operation_item.get("operation") or "").strip()
        if not entity_name or not operation_name or entity_name not in synced_entities:
            continue
        existing_operation = existing_entities.get(entity_name, AuthoringEntitySpec()).operations.get(
            operation_name,
            AuthoringEntityOperation(),
        )
        synced_entities[entity_name].operations[operation_name] = _sync_route_operation_from_inventory(
            existing_operation=existing_operation,
            operation_item=operation_item,
            route_specs=route_specs,
        )

    for verification_item in operation_inventory.get("db_verifications", []):
        if not isinstance(verification_item, dict):
            continue
        entity_name = str(verification_item.get("entity") or "").strip()
        operation_name = str(verification_item.get("operation") or "").strip()
        if not entity_name or not operation_name or entity_name not in synced_entities:
            continue
        existing_operation = existing_entities.get(entity_name, AuthoringEntitySpec()).operations.get(
            operation_name,
            AuthoringEntityOperation(),
        )
        synced_entities[entity_name].operations[operation_name] = _sync_db_operation_from_inventory(
            existing_operation=existing_operation,
            verification_item=verification_item,
        )

    surface = str(operation_inventory.get("surface") or entity_inventory.get("surface") or existing_plan.scope.surface)
    route_includes = [
        f"{str(item.get('method') or '').strip().upper()} {str(item.get('path') or '').strip()}"
        for item in operation_inventory.get("routes", [])
        if isinstance(item, dict) and str(item.get("method") or "").strip() and str(item.get("path") or "").strip()
    ]
    cases = [] if _has_only_placeholder_cases(existing_plan) else list(existing_plan.cases)
    return AuthoringPlan(
        version=existing_plan.version,
        source_id=str(entity_inventory.get("source_id") or operation_inventory.get("source_id") or existing_plan.source_id),
        project=str(entity_inventory.get("project") or operation_inventory.get("project") or existing_plan.project),
        title=existing_plan.title,
        goal=existing_plan.goal,
        scope=AuthoringScope(
            surface=surface,
            style=existing_plan.scope.style,
            include=route_includes or list(existing_plan.scope.include),
        ),
        defaults=_sync_defaults_from_entity_inventory(existing_plan.defaults, entity_inventory),
        entities=synced_entities,
        cases=cases,
        assumptions=[] if _has_placeholder_notes(existing_plan.assumptions) else list(existing_plan.assumptions),
        open_questions=[] if _has_placeholder_notes(existing_plan.open_questions) else list(existing_plan.open_questions),
        metadata={
            **dict(existing_plan.metadata),
            "authoring_workflow": "staged-v1",
            "synced_from_inventories": True,
        },
    )



def _sync_route_operation_from_inventory(
    *,
    existing_operation: AuthoringEntityOperation,
    operation_item: dict[str, Any],
    route_specs: dict[tuple[str, str], dict[str, Any]],
) -> AuthoringEntityOperation:
    route_payload = operation_item.get("route") if isinstance(operation_item.get("route"), dict) else None
    method = str((route_payload or {}).get("method") or operation_item.get("method") or "").strip().upper()
    path = str((route_payload or {}).get("path") or operation_item.get("path") or "").strip()
    route = AuthoringRoute(method=method, path=path) if method and path else existing_operation.route
    route_spec = route_specs.get((route.method.strip().upper(), route.path.strip())) if route is not None else None
    status_code = _maybe_int((operation_item.get("oracle") or {}).get("status_code") if isinstance(operation_item.get("oracle"), dict) else None)
    if status_code is None and route_spec is not None:
        status_code = _maybe_int(route_spec.get("success_status"))
    existing_oracle = existing_operation.oracle or AuthoringOracle()
    oracle = AuthoringOracle(
        status_code=status_code if status_code is not None else existing_oracle.status_code,
        business_checks=_string_list_from_payload(
            (operation_item.get("oracle") or {}).get("business_checks") if isinstance(operation_item.get("oracle"), dict) else None,
            fallback=existing_oracle.business_checks or (["response JSON exists"] if status_code and status_code != 204 else []),
        ),
        captures=_capture_rules_from_inventory(operation_item.get("captures"), fallback=existing_oracle.captures),
        persisted_state=existing_oracle.persisted_state,
    )
    return AuthoringEntityOperation(
        route=route,
        request_headers=dict(operation_item.get("request_headers") or operation_item.get("headers") or existing_operation.request_headers),
        request_params=dict(operation_item.get("request_params") or operation_item.get("params") or existing_operation.request_params),
        request_body=operation_item.get("request_body", existing_operation.request_body),
        request_constraints=_dict_list_from_payload(
            operation_item.get("request_constraints"),
            fallback=existing_operation.request_constraints,
        ),
        auth_strategy=_string_list_from_payload(operation_item.get("auth_strategy"), fallback=existing_operation.auth_strategy),
        oracle=oracle,
        sql=existing_operation.sql,
        params=dict(existing_operation.params),
        expected_outcomes=list(existing_operation.expected_outcomes),
        captures=_capture_rules_from_inventory(operation_item.get("captures"), fallback=existing_operation.captures),
        column_types=dict(existing_operation.column_types),
        permission_state_effects=_dict_list_from_payload(
            operation_item.get("permission_state_effects"),
            fallback=existing_operation.permission_state_effects,
        ),
    )



def _sync_db_operation_from_inventory(
    *,
    existing_operation: AuthoringEntityOperation,
    verification_item: dict[str, Any],
) -> AuthoringEntityOperation:
    return AuthoringEntityOperation(
        route=existing_operation.route,
        request_headers=dict(existing_operation.request_headers),
        request_params=dict(existing_operation.request_params),
        request_body=existing_operation.request_body,
        request_constraints=list(existing_operation.request_constraints),
        auth_strategy=list(existing_operation.auth_strategy),
        oracle=existing_operation.oracle,
        sql=str(verification_item.get("sql") or existing_operation.sql or ""),
        params=dict(verification_item.get("params") or existing_operation.params),
        expected_outcomes=_string_list_from_payload(
            verification_item.get("expected_outcomes"),
            fallback=existing_operation.expected_outcomes,
        ),
        captures=_string_list_from_payload(verification_item.get("captures"), fallback=existing_operation.captures),
        column_types={
            str(key): str(value)
            for key, value in dict(verification_item.get("column_types") or existing_operation.column_types).items()
        },
        permission_state_effects=list(existing_operation.permission_state_effects),
    )



def _sync_defaults_from_entity_inventory(
    existing_defaults: AuthoringDefaults,
    entity_inventory: dict[str, Any],
) -> AuthoringDefaults:
    auth_contract = entity_inventory.get("auth_contract") if isinstance(entity_inventory.get("auth_contract"), dict) else {}
    actor = str(auth_contract.get("actor") or existing_defaults.actor or "")
    return AuthoringDefaults(
        environment=existing_defaults.environment,
        auth=existing_defaults.auth,
        actor=actor,
        headers=dict(existing_defaults.headers),
        scenario_variables=list(existing_defaults.scenario_variables),
    )



def _route_specs_by_key(operation_inventory: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    specs: dict[tuple[str, str], dict[str, Any]] = {}
    for item in operation_inventory.get("routes", []):
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "").strip().upper()
        path = str(item.get("path") or "").strip()
        if method and path:
            specs[(method, path)] = item
    return specs



def _capture_rules_from_inventory(value: Any, *, fallback: list[str]) -> list[str]:
    captures = _string_list_from_payload(value, fallback=fallback)
    rules: list[str] = []
    for capture in captures:
        normalized = capture.strip()
        if not normalized:
            continue
        if "->" in normalized:
            rules.append(normalized)
        else:
            rules.append(f"response.json.{normalized} -> {normalized}")
    return rules



def _string_list_from_payload(value: Any, *, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return list(fallback)


def _dict_list_from_payload(value: Any, *, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return [dict(item) for item in fallback]



def _maybe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None



def _has_only_placeholder_cases(plan: AuthoringPlan) -> bool:
    return len(plan.cases) == 1 and plan.cases[0].id == "create-primary-entity"



def _has_placeholder_notes(values: list[str]) -> bool:
    return bool(values) and all(value.strip().lower().startswith("replace with") for value in values)



def _write_synced_authoring_plan(bundle_dir: Path, authoring_plan: AuthoringPlan) -> Path:
    run_context = load_generation_run_context_from_bundle_dir(bundle_dir)
    if run_context is not None:
        return FileGenerationArtifactStore().write_authoring_plan(run_context, authoring_plan)
    target_path = bundle_dir / AUTHORING_PLAN_FILENAME
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise GenerationCliInputError(
            [
                GenerationDiagnostic(
                    code="adapter_sync_authoring_plan_yaml_dependency_missing",
                    message="PyYAML is required to write synced authoring-plan YAML.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(target_path),
                )
            ]
        ) from exc
    write_text_file(target_path, yaml.safe_dump(authoring_plan.to_dict(), allow_unicode=True, sort_keys=False))
    return target_path

