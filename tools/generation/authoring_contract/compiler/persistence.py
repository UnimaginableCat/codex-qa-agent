"""Persisted-state DB verification compilation."""

from __future__ import annotations

from tools.generation.domain.models import GenerationDiagnostic, PlannedDbVerification

from ..diagnostics import authoring_diagnostic
from ..helpers import (
    _extract_placeholders,
    _extract_placeholders_from_value,
    _persistance_template_mixes_primary_key_and_entity_id,
)
from ..models import AuthoringCase, AuthoringPlan


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
