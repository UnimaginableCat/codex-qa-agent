"""Diagnostics and status helpers for authoring-plan compilation."""

from __future__ import annotations

from tools.common.statuses import StepStatus
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic

AUTHORING_BLOCKING_CODES = {
    "authoring_missing_source_id",
    "authoring_missing_project",
    "authoring_project_must_target_code_subdir",
    "authoring_missing_title",
    "authoring_missing_goal",
    "authoring_missing_scope",
    "authoring_missing_cases",
    "authoring_case_missing_id",
    "authoring_case_missing_kind",
    "authoring_case_missing_objective",
    "authoring_case_missing_oracle",
    "authoring_case_missing_state_change",
    "authoring_unknown_state_change",
    "authoring_missing_route_hint",
    "authoring_unknown_case_kind",
    "authoring_duplicate_case_id",
    "authoring_unknown_entity",
    "authoring_unknown_entity_operation",
    "authoring_setup_reference_unresolved",
    "authoring_persisted_state_template_missing",
    "authoring_state_change_without_persistence_check",
    "authoring_case_kind_incompatible_with_setup",
    "authoring_capture_required_but_missing",
    "authoring_invalid_entity_id_field",
    "authoring_scenario_variable_entry_invalid",
    "authoring_setup_entity_id_field_unresolved",
    "authoring_persisted_state_id_field_missing",
    "authoring_persisted_state_id_field_semantic_mismatch",
    "authoring_created_entity_persistence_uses_fixture_id",
    "authoring_created_entity_capture_overwrites_fixture_variable",
    "authoring_case_boundary_contract_mismatch",
    "authoring_db_string_placeholder_requires_quotes",
    "authoring_request_constraint_unsatisfied",
    "authoring_request_body_evidence_required",
    "authoring_env_id_equality_type_ambiguous",
    "authoring_stage_inventory_missing",
    "authoring_stage_inventory_invalid",
    "authoring_stage_inventory_entity_mismatch",
    "authoring_stage_inventory_operation_mismatch",
    "authoring_stage_inventory_route_mismatch",
    "authoring_stage_inventory_status_mismatch",
    "authoring_stage_inventory_state_mismatch",
    "authoring_stage_inventory_same_state_behavior_required",
    "authoring_stage_inventory_same_state_mismatch",
    "authoring_stage_inventory_idempotency_persistence_missing",
    "authoring_env_backed_role_identity_disallowed",
    "authoring_visibility_claim_missing_required_assertion",
    "authoring_visibility_response_path_evidence_required",
    "authoring_collection_visibility_data_setup_required",
    "authoring_visibility_root_field_assertion_requires_path_evidence",
    "authoring_permission_negative_case_state_setup_required",
    "authoring_permission_negative_case_baseline_check_required",
    "authoring_permission_state_setup_required",
    "authoring_permission_state_contract_invalid",
    "authoring_permission_prerequisite_requires_required_state",
    "authoring_permission_actor_identity_binding_required",
    "authoring_case_readiness_evidence_missing",
    "authoring_open_question_blocks_promotion",
    "authoring_non_blocking_note_blocks_promotion",
    "authoring_scope_role_coverage_missing",
}


def authoring_diagnostic(
    code: str,
    message: str,
    *,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    source_ref: str | None = None,
    details: dict[str, object] | None = None,
) -> GenerationDiagnostic:
    return GenerationDiagnostic(
        code=code,
        message=message,
        severity=severity,
        source_ref=source_ref,
        details={} if details is None else dict(details),
    )


def derive_authoring_status(diagnostics: list[GenerationDiagnostic]) -> StepStatus:
    if any(diagnostic.code in AUTHORING_BLOCKING_CODES for diagnostic in diagnostics):
        return StepStatus.BLOCKED
    if any(diagnostic.severity == DiagnosticSeverity.ERROR for diagnostic in diagnostics):
        return StepStatus.ERROR
    return StepStatus.PASS


def build_authoring_message(
    status: StepStatus,
    diagnostics: list[GenerationDiagnostic],
    *,
    compiled: bool,
) -> str:
    if status == StepStatus.PASS:
        if compiled:
            return "Authoring plan compiled into AgentTestPlanInput."
        return "Authoring plan is structurally valid and compilable."
    if status == StepStatus.BLOCKED:
        return "Authoring plan is present but blocked by missing or unresolved authoring contract details."
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.severity == DiagnosticSeverity.ERROR)
    return f"Authoring plan validation failed with {error_count} error(s)."
