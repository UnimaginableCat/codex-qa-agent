"""Review item assembly and render-result lookup helpers."""

from __future__ import annotations

from pathlib import Path

from tools.common.statuses import StepStatus
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic, GenerationRunContext
from tools.generation.rendering.models import ScenarioDraft, ScenarioDraftValidationResult, ScenarioRenderResult
from tools.generation.review.models import (
    DeferredDraftReviewItem,
    DraftEditTarget,
    DraftPromotionAdvisory,
    DraftReviewDiagnosticsSummary,
    ScenarioDraftParseStatus,
    ScenarioDraftReviewItem,
    ScenarioDraftReviewSet,
    ScenarioPromotionResult,
)

from .checklist import _build_deferred_checklist, _build_draft_checklist
from .edit_targets import _build_deferred_edit_targets, _build_edit_targets
from .gaps import (
    _deferred_gap_summary,
    _draft_gap_summary,
    _draft_readiness_category,
    _expectation_contract_gap_summary_from_file,
    _merge_gap_summaries,
    _promotion_advisory,
    _route_status,
)
from .scenario_introspection import _route_binding_from_draft_metadata


def _build_review_item(
    run_context: GenerationRunContext,
    draft: ScenarioDraft,
    validation: ScenarioDraftValidationResult | None,
    unsupported_checks: list[object],
    deferred_item: object | None,
    render_diagnostics: list[GenerationDiagnostic],
) -> ScenarioDraftReviewItem:
    source_path = run_context.artifact_dir / draft.relative_path
    parse_status = (
        ScenarioDraftParseStatus.VALID
        if validation is not None and validation.parse_valid
        else ScenarioDraftParseStatus.INVALID
    )
    diagnostics_summary = []
    if validation is None:
        diagnostics_summary.append("No parser validation result was found for this draft.")
    else:
        diagnostics_summary.extend(str(item.get("message", "")) for item in validation.diagnostics if item.get("message"))
    route_binding = _route_binding_from_draft_metadata(draft)
    gap_summary = _draft_gap_summary(
        draft,
        validation,
        route_binding=route_binding,
        render_diagnostics=render_diagnostics,
        has_unsupported_items=bool(unsupported_checks),
        has_deferred_items=deferred_item is not None,
    )
    gap_summary = _merge_gap_summaries(
        gap_summary,
        _expectation_contract_gap_summary_from_file(source_path, draft.metadata),
    )
    diagnostics_details = DraftReviewDiagnosticsSummary(
        parse_diagnostics_count=0 if validation is None else len(validation.diagnostics),
        render_diagnostics_count=len(render_diagnostics),
        parse_messages=diagnostics_summary,
        render_codes=[diagnostic.code for diagnostic in render_diagnostics],
    )
    checklist = _build_draft_checklist(
        draft,
        parse_status=parse_status,
        route_binding=route_binding,
        gap_summary=gap_summary,
    )
    readiness_category = _draft_readiness_category(parse_status, route_binding, gap_summary)
    promotion_advisory = _promotion_advisory(
        parse_status=parse_status,
        readiness_category=readiness_category,
        has_unsupported_items=bool(unsupported_checks),
        has_deferred_items=deferred_item is not None,
        checklist=checklist,
        gap_summary=gap_summary,
    )
    edit_targets = _build_edit_targets(
        draft,
        checklist=checklist,
        gap_summary=gap_summary,
        parse_status=parse_status,
        route_binding=route_binding,
    )
    return ScenarioDraftReviewItem(
        draft_id=draft.draft_id,
        case_id=draft.case_id,
        title=draft.title,
        file_path=source_path,
        parse_status=parse_status,
        diagnostics_summary=diagnostics_summary,
        has_unsupported_items=bool(unsupported_checks),
        has_deferred_items=deferred_item is not None,
        readiness_category=readiness_category,
        route_status=_route_status(route_binding),
        gap_summary=gap_summary,
        promotion_advisory=promotion_advisory,
        diagnostics_details=diagnostics_details,
        checklist=checklist,
        edit_targets=edit_targets,
        edit_target_count=len(edit_targets.targets),
    )

def _build_deferred_review_item(
    deferred_item: object,
    unsupported_checks: list[object],
) -> DeferredDraftReviewItem:
    gap_summary = _deferred_gap_summary(unsupported_checks)
    edit_targets = _build_deferred_edit_targets(deferred_item.case_id, gap_summary)
    return DeferredDraftReviewItem(
        case_id=deferred_item.case_id,
        title=deferred_item.title,
        reason_code=deferred_item.reason_code,
        message=deferred_item.message,
        gap_summary=gap_summary,
        promotion_advisory=DraftPromotionAdvisory.NOT_RECOMMENDED_FOR_PROMOTION,
        checklist=_build_deferred_checklist(gap_summary),
        edit_targets=edit_targets,
        edit_target_count=len(edit_targets.targets),
    )

def _find_draft(render_result: ScenarioRenderResult, draft_id: str) -> ScenarioDraft | None:
    for draft in render_result.draft_set.drafts:
        if draft.draft_id == draft_id:
            return draft
    return None

def _find_validation(
    render_result: ScenarioRenderResult,
    draft_id: str,
) -> ScenarioDraftValidationResult | None:
    for validation in render_result.validation_results:
        if validation.draft_id == draft_id:
            return validation
    return None

def _find_review_item(review_set: ScenarioDraftReviewSet, draft_id: str) -> ScenarioDraftReviewItem | None:
    for item in review_set.items:
        if item.draft_id == draft_id:
            return item
    return None

def _promotion_review_gate_diagnostics(
    review_item: ScenarioDraftReviewItem | None,
    *,
    allow_known_gaps: bool,
    known_gaps_reviewed: bool,
) -> list[GenerationDiagnostic]:
    if review_item is None:
        return [
            GenerationDiagnostic(
                code="scenario_promotion_review_item_missing",
                message="Selected draft could not be found in review output; promotion requires a review-backed gate.",
                severity=DiagnosticSeverity.ERROR,
            )
        ]

    high_priority_targets = [
        target for target in review_item.edit_targets.targets if target.priority == "high"
    ]
    all_targets = list(review_item.edit_targets.targets)
    advisory_blocks = review_item.promotion_advisory in {
        DraftPromotionAdvisory.SAFE_PREVIEW_ONLY,
        DraftPromotionAdvisory.NOT_RECOMMENDED_FOR_PROMOTION,
        DraftPromotionAdvisory.INVALID_DRAFT,
    }
    if not all_targets and not advisory_blocks:
        return []
    if allow_known_gaps and not known_gaps_reviewed:
        return [
            GenerationDiagnostic(
                code="scenario_promotion_known_gaps_confirmation_missing",
                message=(
                    "Draft promotion has review gaps. --allow-known-gaps requires "
                    "--known-gaps-reviewed after the operator has inspected the concrete findings."
                ),
                severity=DiagnosticSeverity.ERROR,
                source_ref=review_item.draft_id,
                details={
                    "promotion_advisory": review_item.promotion_advisory.value,
                    "edit_target_count": review_item.edit_target_count,
                    "high_priority_edit_target_count": len(high_priority_targets),
                    "edit_targets": _review_edit_target_details(all_targets),
                },
            )
        ]

    diagnostic = GenerationDiagnostic(
        code=(
            "scenario_promotion_known_gaps_override"
            if allow_known_gaps
            else "scenario_promotion_review_gate_blocked"
        ),
        message=(
            "Draft promotion has known review gaps and was allowed by explicit override."
            if allow_known_gaps
            else (
                "Draft promotion is blocked by review findings. Resolve high-priority edit targets "
                "or rerun with --allow-known-gaps after explicit operator review."
            )
        ),
        severity=DiagnosticSeverity.WARNING if allow_known_gaps else DiagnosticSeverity.ERROR,
        source_ref=review_item.draft_id,
        details={
            "promotion_advisory": review_item.promotion_advisory.value,
            "edit_target_count": review_item.edit_target_count,
            "high_priority_edit_target_count": len(high_priority_targets),
            "edit_targets": _review_edit_target_details(all_targets),
            "high_priority_edit_targets": _review_edit_target_details(high_priority_targets),
        },
    )
    return [diagnostic]

def _review_edit_target_details(targets: list[DraftEditTarget]) -> list[dict[str, str]]:
    return [
        {
            "target_id": target.target_id,
            "target_type": target.target_type.value,
            "section_name": target.section_name,
            "priority": target.priority,
            "reason": target.reason,
            "suggested_minimum_patch": target.suggested_minimum_patch,
        }
        for target in targets
    ]

def _promotion_batch_status(results: list[ScenarioPromotionResult]) -> StepStatus:
    statuses = [item.status for item in results]
    if StepStatus.ERROR in statuses:
        return StepStatus.ERROR
    if StepStatus.BLOCKED in statuses:
        return StepStatus.BLOCKED
    if StepStatus.FAIL in statuses:
        return StepStatus.FAIL
    return StepStatus.PASS

def _group_unsupported_checks(render_result: ScenarioRenderResult) -> dict[str, list[object]]:
    grouped: dict[str, list[object]] = {}
    for check in render_result.unsupported_checks:
        grouped.setdefault(check.case_id, []).append(check)
    return grouped

def _group_render_diagnostics(render_result: ScenarioRenderResult) -> dict[str, list[GenerationDiagnostic]]:
    grouped: dict[str, list[GenerationDiagnostic]] = {}
    for diagnostic in render_result.diagnostics:
        if diagnostic.source_ref:
            grouped.setdefault(diagnostic.source_ref, []).append(diagnostic)
    return grouped
