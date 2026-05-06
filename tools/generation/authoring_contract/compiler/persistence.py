"""Persisted-state DB verification compilation."""

from __future__ import annotations

from tools.generation.domain.models import GenerationDiagnostic, PlannedDbVerification
from tools.scenario_runner.domain.models import ScenarioVariableSource

from ..diagnostics import authoring_diagnostic
from ..helpers import (
    _capture_targets,
    _extract_placeholders,
    _extract_placeholders_from_value,
    _persistance_template_mixes_primary_key_and_entity_id,
    _requires_persistence,
)
from ..models import AuthoringCase, AuthoringPlan
from ..case_diagnostics.variables import _scenario_variable_definitions


def build_db_verification(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
) -> tuple[PlannedDbVerification | None, list[GenerationDiagnostic], set[str]]:
    diagnostics: list[GenerationDiagnostic] = []
    if case.oracle is None or case.oracle.persisted_state is None:
        return None, diagnostics, set()
    state_ref = case.oracle.persisted_state
    entity_name = state_ref.entity.strip()
    operation_name = state_ref.operation.strip()
    entity_spec = authoring_plan.entities.get(entity_name)
    if entity_spec is None:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_unknown_entity",
                "Persisted-state reference uses an unknown entity.",
                source_ref=case_ref,
                details={"entity": entity_name},
            )
        )
        return None, diagnostics, set()
    operation = entity_spec.operations.get(operation_name)
    if operation is None:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_unknown_entity_operation",
                "Persisted-state reference uses an unknown entity operation.",
                source_ref=case_ref,
                details={"entity": entity_name, "operation": operation_name},
            )
        )
        return None, diagnostics, set()
    if not operation.sql.strip():
        diagnostics.append(
            authoring_diagnostic(
                "authoring_persisted_state_template_missing",
                "Persisted-state reference must resolve to a DB verification template with sql.",
                source_ref=case_ref,
                details={"entity": entity_name, "operation": operation_name},
            )
        )
        return None, diagnostics, set()
    expected_outcomes = list(operation.expected_outcomes)
    if not expected_outcomes and operation.oracle is not None:
        expected_outcomes = list(operation.oracle.business_checks)
    if not expected_outcomes:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_persisted_state_template_missing",
                "Persisted-state verification template must define expected_outcomes.",
                source_ref=case_ref,
                details={"entity": entity_name, "operation": operation_name},
            )
        )
        return None, diagnostics, set()
    created_capture_diagnostic = _created_entity_capture_overwrites_fixture_variable_diagnostic(
        authoring_plan=authoring_plan,
        case=case,
        case_ref=case_ref,
    )
    if created_capture_diagnostic is not None:
        diagnostics.append(created_capture_diagnostic)
        return None, diagnostics, set()
    placeholders = set(_extract_placeholders(operation.sql))
    placeholders.update(_extract_placeholders_from_value(operation.params))
    entity_id_field = entity_spec.id_field.strip()
    entity_key_fields = [field_name.strip() for field_name in entity_spec.key_fields if field_name.strip()]
    has_id_scope = bool(entity_id_field and entity_id_field in placeholders)
    has_key_scope = bool(entity_key_fields and set(entity_key_fields).issubset(placeholders))
    if entity_id_field and not has_id_scope and not has_key_scope:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_persisted_state_id_field_missing",
                "Persisted-state template must reference the entity id_field or all declared key_fields so verification is scoped to the authored entity instance.",
                source_ref=case_ref,
                details={
                    "entity": entity_name,
                    "operation": operation_name,
                    "id_field": entity_id_field,
                    "key_fields": entity_key_fields,
                    "placeholders": sorted(placeholders),
                },
            )
        )
        return None, diagnostics, set()
    created_entity_diagnostic = _created_entity_persistence_uses_fixture_id_diagnostic(
        case=case,
        case_ref=case_ref,
        entity_name=entity_name,
        operation_name=operation_name,
        placeholders=placeholders,
    )
    if created_entity_diagnostic is not None:
        diagnostics.append(created_entity_diagnostic)
        return None, diagnostics, set()
    if _persistance_template_mixes_primary_key_and_entity_id(
        sql=operation.sql,
        expected_outcomes=expected_outcomes,
        entity_id_field=entity_id_field,
    ):
        diagnostics.append(
            authoring_diagnostic(
                "authoring_persisted_state_id_field_semantic_mismatch",
                (
                    "Persisted-state template mixes the DB primary key column `id` with the entity id_field. "
                    "Use one identifier consistently across capture, route placeholders, SQL filters, and DB expectations."
                ),
                source_ref=case_ref,
                details={
                    "entity": entity_name,
                    "operation": operation_name,
                    "id_field": entity_id_field,
                },
            )
        )
        return None, diagnostics, set()
    return (
        PlannedDbVerification(
            name=f"Verify {entity_name}.{operation_name}",
            sql=operation.sql,
            params=dict(operation.params),
            expected_outcomes=expected_outcomes,
            capture=list(operation.captures),
        ),
        diagnostics,
        placeholders,
    )


def _created_entity_persistence_uses_fixture_id_diagnostic(
    *,
    case: AuthoringCase,
    case_ref: str,
    entity_name: str,
    operation_name: str,
    placeholders: set[str],
) -> GenerationDiagnostic | None:
    if not _requires_persistence(case.state_change):
        return None
    if str(case.state_change or "").strip().lower() != "create":
        return None
    if case.oracle is None:
        return None

    captured_targets = _capture_targets(case.oracle.captures)
    created_id_targets = sorted(
        target for target in captured_targets if target.startswith("created_") and target.endswith("_id")
    )
    if not created_id_targets:
        return None

    fixture_scopes: list[dict[str, str]] = []
    for created_target in created_id_targets:
        canonical_target = created_target.removeprefix("created_")
        if canonical_target in placeholders and created_target not in placeholders:
            fixture_scopes.append(
                {
                    "created_capture": created_target,
                    "fixture_placeholder": canonical_target,
                }
            )
    if not fixture_scopes:
        return None

    return authoring_diagnostic(
        "authoring_created_entity_persistence_uses_fixture_id",
        (
            "Create-case persisted-state verification captures a new entity id but scopes the DB check with the "
            "pre-existing fixture id placeholder. This can validate the fixture row instead of the entity created "
            "by the case."
        ),
        source_ref=case_ref,
        details={
            "entity": entity_name,
            "operation": operation_name,
            "fixture_scopes": fixture_scopes,
            "placeholders": sorted(placeholders),
            "suggestion": (
                "Scope the DB verification by the captured created_* id, or model the created resource as a "
                "separate authored entity with an id_field matching the captured variable."
            ),
        },
    )


def _created_entity_capture_overwrites_fixture_variable_diagnostic(
    *,
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
) -> GenerationDiagnostic | None:
    if str(case.state_change or "").strip().lower() != "create":
        return None
    if case.oracle is None:
        return None

    variable_definitions = _scenario_variable_definitions(authoring_plan, case)
    overwritten_targets: list[dict[str, str]] = []
    for target in sorted(_capture_targets(case.oracle.captures)):
        if target.startswith("created_"):
            continue
        if not _looks_like_entity_identifier(target):
            continue
        definition = variable_definitions.get(target)
        if definition is None or definition.source in {ScenarioVariableSource.RUNTIME, ScenarioVariableSource.GENERATED}:
            continue
        overwritten_targets.append(
            {
                "capture_target": target,
                "source": str(definition.source.value),
                "source_name": definition.env_name or definition.source_name or "",
            }
        )

    if not overwritten_targets:
        return None

    return authoring_diagnostic(
        "authoring_created_entity_capture_overwrites_fixture_variable",
        (
            "Create-case captures a newly created entity id into a predeclared fixture/input variable. This can "
            "overwrite the stable value used by routes or DB verification and hide whether the check validated "
            "the created entity or the original fixture."
        ),
        source_ref=case_ref,
        details={
            "captures": overwritten_targets,
            "suggestion": (
                "Capture created ids into a distinct created_* variable and model DB verification against that "
                "captured id, or use a separate created-resource entity with matching key fields."
            ),
        },
    )


def _looks_like_entity_identifier(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return False
    return normalized.endswith("_id") or normalized.endswith("_guid") or normalized.endswith("_uuid")
