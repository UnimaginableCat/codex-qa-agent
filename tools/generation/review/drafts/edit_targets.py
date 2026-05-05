"""Operator-facing draft edit target construction."""

from __future__ import annotations

from tools.generation.rendering.models import ScenarioDraft
from tools.generation.review.models import (
    DraftChecklistResult,
    DraftEditTarget,
    DraftEditTargetList,
    DraftEditTargetType,
    DraftGapSummary,
    ScenarioDraftParseStatus,
    ScenarioRequirementStatus,
)
from tools.generation.review.templates import PatchTemplateCatalogService

from .checklist import _diff_line
from ..common import _slugify


def _build_edit_targets(
    draft: ScenarioDraft,
    *,
    checklist: DraftChecklistResult,
    gap_summary: DraftGapSummary,
    parse_status: ScenarioDraftParseStatus,
    route_binding: dict[str, object],
) -> DraftEditTargetList:
    targets: list[DraftEditTarget] = []
    if parse_status == ScenarioDraftParseStatus.INVALID:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.FIX_PARSER_ERRORS,
                section_name="Scenario root",
                reason="Draft is not parser-valid.",
                related_requirements=["parser_valid"],
                priority="high",
                suggested_minimum_patch="Fix parser errors so the draft becomes valid scenario markdown before further edits.",
            )
        )

    status_by_requirement = {
        check.requirement.requirement_id: check.status for check in checklist.checks
    }
    gap_codes = set(gap_summary.gap_codes)

    if "compile_unsupported_expectation" in gap_codes:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_EXPECTED_ASSERTION,
                section_name="Final expectations",
                reason="Compile validation found unsupported expectation DSL.",
                related_requirements=["assertions"],
                priority="high",
                suggested_minimum_patch="Replace unsupported expectation text with a runner-supported deterministic assertion.",
            )
        )

    if gap_codes & {
        "compile_capture_rule_invalid",
        "compile_capture_variable_invalid",
        "compile_step_self_capture_dependency",
        "compile_future_capture_dependency",
    }:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_CAPTURE,
                section_name="Steps",
                reason="Compile validation found an invalid or unresolved capture contract.",
                related_requirements=["captures"],
                priority="high",
                suggested_minimum_patch="Fix capture syntax or reorder steps so referenced captured variables exist before use.",
            )
        )

    if "stateful_intercase_precondition" in gap_codes:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Preconditions",
                reason="Scenario appears to depend on state created by another scenario or a prior ordered run.",
                related_requirements=["data_setup"],
                priority="high",
                suggested_minimum_patch=(
                    "Make the scenario self-contained, move the setup into the scenario, or mark it deferred "
                    "instead of promoting it as independently runnable."
                ),
            )
        )

    if "external_inputs_required" in gap_codes:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Variables",
                reason="Compile validation found external variable inputs required before execution.",
                related_requirements=[],
                priority="normal",
                suggested_minimum_patch="Declare the variable source in Variables or ensure the environment provides it before runner execution.",
            )
        )

    if gap_codes & {"missing_environment", "missing_project", "missing_dependency", "workspace_output"}:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Preconditions",
                reason="Preflight validation found workspace or environment readiness issues.",
                related_requirements=[],
                priority="high",
                suggested_minimum_patch="Resolve the referenced environment file, target project path, dependency, or writable output directory before execution.",
            )
        )

    if "external_variable" in gap_codes:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Variables",
                reason="Preflight validation found unresolved external variables.",
                related_requirements=[],
                priority="high",
                suggested_minimum_patch="Provide the required variable through the Variables section or selected environment before execution.",
            )
        )

    if status_by_requirement.get("request_structure") == ScenarioRequirementStatus.MISSING:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_REQUEST_BODY,
                section_name="Steps",
                reason="Request structure is missing for the rendered API step.",
                related_requirements=["request_structure"],
                priority="high",
                suggested_minimum_patch="Add a minimal request body or request shape under the API step so the operator can execute the route intentionally.",
            )
        )

    assertions_status = status_by_requirement.get("assertions")
    if assertions_status in {
        ScenarioRequirementStatus.MISSING,
        ScenarioRequirementStatus.PARTIALLY_SATISFIED,
    }:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_EXPECTED_ASSERTION,
                section_name="Final expectations",
                reason="Expected assertions are missing or only partially defined.",
                related_requirements=["assertions"],
                priority="high",
                suggested_minimum_patch="Add at least one deterministic assertion describing the expected HTTP outcome or observable behavior.",
            )
        )

    if status_by_requirement.get("auth_strategy") == ScenarioRequirementStatus.PARTIALLY_SATISFIED:
        section_name = "Preconditions" if "auth_headers_unresolved" in gap_codes else "Steps"
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_AUTH_HEADERS,
                section_name=section_name,
                reason="Auth or header requirements are unresolved.",
                related_requirements=["auth_strategy"],
                priority="normal",
                suggested_minimum_patch="State the required auth/header strategy in Preconditions or add the required headers directly to the API step.",
            )
        )

    if status_by_requirement.get("db_verification") == ScenarioRequirementStatus.PARTIALLY_SATISFIED:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_DB_VERIFICATION,
                section_name="Notes",
                reason="DB verification is absent and may be needed for persisted-state checks.",
                related_requirements=["db_verification"],
                priority="normal",
                suggested_minimum_patch="Add a note or follow-up verification target that states what persisted state must be checked after execution.",
            )
        )

    if status_by_requirement.get("captures") == ScenarioRequirementStatus.PARTIALLY_SATISFIED:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_CAPTURE,
                section_name="Steps",
                reason="Captures are not defined for values that may be needed later.",
                related_requirements=["captures"],
                priority="low",
                suggested_minimum_patch="Add a capture only if later steps or checks need a value from the current API response.",
            )
        )

    if "environment_unresolved" in gap_codes and not _has_edit_target(
        targets,
        DraftEditTargetType.CLARIFY_NOTES_ONLY,
        "Preconditions",
    ):
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Preconditions",
                reason="Environment requirements remain unresolved in the canonical test-plan gap model.",
                related_requirements=[],
                priority="high",
                suggested_minimum_patch="State which environment, env file, or workspace dependency must be selected before execution.",
            )
        )

    if "data_setup_unresolved" in gap_codes and not _has_edit_target(
        targets,
        DraftEditTargetType.CLARIFY_NOTES_ONLY,
        "Preconditions",
    ):
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Preconditions",
                reason="Data setup requirements remain unresolved in the canonical test-plan gap model.",
                related_requirements=[],
                priority="normal",
                suggested_minimum_patch="Describe the minimum fixture, seed data, or pre-existing entity state required before execution.",
            )
        )

    if "auth_strategy_unresolved" in gap_codes and not _has_edit_target(
        targets,
        DraftEditTargetType.ADD_AUTH_HEADERS,
        "Preconditions",
    ):
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_AUTH_HEADERS,
                section_name="Preconditions",
                reason="Auth strategy remains unresolved in the canonical test-plan gap model.",
                related_requirements=["auth_strategy"],
                priority="normal",
                suggested_minimum_patch="State the required auth strategy or headers before trying to execute the API step.",
            )
        )

    if "assertion_detail_unresolved" in gap_codes and not _has_edit_target(
        targets,
        DraftEditTargetType.ADD_EXPECTED_ASSERTION,
        "Final expectations",
    ):
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_EXPECTED_ASSERTION,
                section_name="Final expectations",
                reason="Assertion detail remains unresolved in the canonical test-plan gap model.",
                related_requirements=["assertions"],
                priority="high",
                suggested_minimum_patch="Add at least one deterministic assertion that closes the unresolved expected-behavior gap.",
            )
        )

    if gap_codes & {"endpoint_detail_unresolved", "executable_detail_unresolved"} and not route_binding and not _has_edit_target(
        targets,
        DraftEditTargetType.CLARIFY_NOTES_ONLY,
        "Notes",
    ):
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Notes",
                reason="Executable endpoint detail is unresolved in the canonical test-plan gap model.",
                related_requirements=["endpoint_path", "http_method"],
                priority="high",
                suggested_minimum_patch="Clarify the exact route and execution detail in Notes or upstream plan data before trying to render or execute the scenario.",
            )
        )

    if not targets and "non_route_requirements_remaining" in gap_codes and str(route_binding.get("readiness") or "") == "route_resolved":
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Notes",
                reason="Route is resolved, but the draft still carries non-route gaps.",
                related_requirements=[],
                priority="low",
                suggested_minimum_patch="Clarify in Notes which remaining environment, auth, or business details must be supplied before execution.",
            )
        )

    return DraftEditTargetList(draft_id=draft.draft_id, targets=targets)

def _build_deferred_edit_targets(draft_id: str, gap_summary: DraftGapSummary) -> DraftEditTargetList:
    targets: list[DraftEditTarget] = []
    gap_codes = set(gap_summary.gap_codes)
    if "ambiguous_route_mapping" in gap_codes or "missing_planned_route" in gap_codes or "missing_endpoint_evidence" in gap_codes:
        targets.append(
            _edit_target(
                draft_id=draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Notes",
                reason="Draft cannot be rendered safely because route binding is missing or ambiguous.",
                related_requirements=["endpoint_path", "http_method"],
                priority="high",
                suggested_minimum_patch="Clarify the exact route and method in Notes or upstream plan metadata before trying to render or promote the scenario.",
            )
        )
    if not targets:
        targets.append(
            _edit_target(
                draft_id=draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Notes",
                reason="Draft preview is unsupported and requires clarification before promotion.",
                related_requirements=[],
                priority="normal",
                suggested_minimum_patch="Document the missing scenario details in Notes before promoting or executing anything.",
            )
        )
    return DraftEditTargetList(draft_id=draft_id, targets=targets)

def _edit_target(
    *,
    draft_id: str,
    target_type: DraftEditTargetType,
    section_name: str,
    reason: str,
    related_requirements: list[str],
    priority: str,
    suggested_minimum_patch: str,
) -> DraftEditTarget:
    target_id = f"{draft_id}:{target_type.value}:{_slugify(section_name)}"
    return DraftEditTarget(
        target_id=target_id,
        draft_id=draft_id,
        section_name=section_name,
        target_type=target_type,
        reason=reason,
        related_requirements=related_requirements,
        priority=priority,
        suggested_minimum_patch=suggested_minimum_patch,
        patch_suggestion=PatchTemplateCatalogService().suggestion_for(target_type),
    )

def _has_edit_target(
    targets: list[DraftEditTarget],
    target_type: DraftEditTargetType,
    section_name: str,
) -> bool:
    return any(target.target_type == target_type and target.section_name == section_name for target in targets)
