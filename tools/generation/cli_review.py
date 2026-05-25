"""Support code for the generation CLI adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.common.io import write_text_file
from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.cli_core import GenerationCliInputError
from tools.generation.cli_diagnostics import (
    _patch_template_adapter_diagnostics,
    _promotion_adapter_diagnostics,
    _review_adapter_diagnostics,
    _revalidation_adapter_diagnostics,
    _revalidation_dir_adapter_diagnostics,
)
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic
from tools.generation.review import (
    DraftEditTargetType,
    PatchTemplateCatalogService,
    ScenarioDraftBatchPromotionService,
    ScenarioDraftPromotionService,
    ScenarioDraftReviewService,
    ScenarioDirectoryRevalidationRequest,
    ScenarioDirectoryRevalidationService,
    ScenarioPromotionBatchRequest,
    ScenarioPromotionRequest,
    ScenarioPreflightStatus,
    ScenarioRevalidationRequest,
    ScenarioRevalidationService,
)


def run_review(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _review_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    review_set = ScenarioDraftReviewService().review(
        str(args.run_id),
        workspace_root=Path(args.workspace_root),
    )
    review_result_path = Path(review_set.artifact_dir) / "review-result.json"
    payload = to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "run_id": review_set.run_id,
            "source_id": review_set.source_id,
            "artifact_dir": review_set.artifact_dir,
            "review_result_path": review_result_path,
            "draft_count": len(review_set.items),
            "valid_draft_count": sum(1 for item in review_set.items if item.parse_status.value == "valid"),
            "invalid_draft_count": sum(1 for item in review_set.items if item.parse_status.value == "invalid"),
            "partial_draft_count": sum(
                1
                for item in review_set.items
                if item.readiness_category.value == "parser_valid_partial"
            ),
            "strongly_supported_draft_count": sum(
                1
                for item in review_set.items
                if item.readiness_category.value == "parser_valid_strongly_supported"
            ),
            "deferred_item_count": len(review_set.deferred_items),
            "drafts_with_edit_targets": sum(1 for item in review_set.items if item.edit_target_count > 0),
            "total_edit_targets": sum(item.edit_target_count for item in review_set.items),
            "drafts_with_high_priority_edit_targets": sum(
                1
                for item in review_set.items
                if any(target.priority == "high" for target in item.edit_targets.targets)
            ),
            "high_priority_edit_target_count": sum(
                1
                for item in review_set.items
                for target in item.edit_targets.targets
                if target.priority == "high"
            ),
            "average_completeness_ratio": _average_completeness_ratio(review_set),
            "close_to_runnable_count": _close_to_runnable_count(review_set),
            "review_set": review_set.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in review_set.diagnostics],
        }
    )
    write_text_file(review_result_path, json.dumps(payload, ensure_ascii=False, indent=2))
    return payload



def run_promotion(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _promotion_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    if args.promote_all_drafts:
        result = ScenarioDraftBatchPromotionService().promote(
            ScenarioPromotionBatchRequest(
                run_id=str(args.run_id),
                workspace_root=Path(args.workspace_root),
                target_dir=Path(args.target_dir),
                allow_invalid=args.allow_invalid,
                allow_known_gaps=args.allow_known_gaps,
                known_gaps_reviewed=args.known_gaps_reviewed,
                purge_target_dir=args.purge_target_dir,
            )
        )
        return to_json_safe(
            {
                "status": result.status.value,
                "run_id": result.run_id,
                "requested_count": result.requested_count,
                "promoted_count": result.promoted_count,
                "error_count": result.error_count,
                "blocked_count": result.blocked_count,
                "target_dir": result.target_dir,
                "promotion_result_path": result.promotion_result_path,
                "results": [item.to_dict() for item in result.results],
                "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
            }
        )
    result = ScenarioDraftPromotionService().promote(
        ScenarioPromotionRequest(
            run_id=str(args.run_id),
            draft_id=str(args.draft_id),
            workspace_root=Path(args.workspace_root),
            target_dir=Path(args.target_dir),
            allow_invalid=args.allow_invalid,
            allow_known_gaps=args.allow_known_gaps,
            known_gaps_reviewed=args.known_gaps_reviewed,
            purge_target_dir=args.purge_target_dir,
        )
    )
    return to_json_safe(
        {
            "status": result.status.value,
            "run_id": result.run_id,
            "draft_id": result.draft_id,
            "source_path": result.source_path,
            "target_path": result.target_path,
            "promotion_result_path": result.promotion_result_path,
            "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
        }
    )



def run_list_patch_templates(args: argparse.Namespace) -> dict[str, Any]:
    catalog = PatchTemplateCatalogService().list_templates()
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "catalog_version": catalog.catalog_version,
            "template_count": len(catalog.templates),
            "templates": [template.to_dict() for template in catalog.templates],
        }
    )



def run_show_patch_template(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _patch_template_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    target_type = DraftEditTargetType(str(args.target_type))
    template = PatchTemplateCatalogService().get_template(target_type)
    if template is None:
        raise GenerationCliInputError(
            [
                GenerationDiagnostic(
                    code="adapter_patch_template_missing",
                    message=f"No patch template exists for target type {target_type.value}.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=target_type.value,
                )
            ]
        )
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "template": template.to_dict(),
        }
    )



def run_validate_scenario(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _revalidation_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    result = ScenarioRevalidationService().validate(
        ScenarioRevalidationRequest(
            file_path=Path(args.path),
            validation_mode=args.mode,
            workspace_root=Path(args.workspace_root),
        )
    )
    compile_validation = result.compile_validation
    preflight_validation = result.preflight_validation
    readiness_category = (
        result.environment_readiness_category.value
        if result.environment_readiness_category is not None
        else result.execution_readiness_category.value
    )
    validation_notes = _validation_notes_for_result(result.validation_mode, compile_validation, preflight_validation)
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "file_path": result.file_path,
            "parse_status": result.parse_status.value,
            "validation_mode": result.validation_mode,
            "diagnostics": result.diagnostics,
            "checklist": result.checklist.to_dict(),
            "gap_summary": result.gap_summary.to_dict(),
            "edit_targets": result.edit_targets.to_dict(),
            "edit_target_count": len(result.edit_targets.targets),
            "promotion_advisory": result.promotion_advisory.value,
            "completeness_ratio": result.completeness_ratio,
            "compile_status": None if compile_validation is None else compile_validation.compile_status.value,
            "preflight_status": None if preflight_validation is None else preflight_validation.preflight_status.value,
            "execution_readiness_category": result.execution_readiness_category.value,
            "environment_readiness_category": (
                None
                if result.environment_readiness_category is None
                else result.environment_readiness_category.value
            ),
            "readiness_category": readiness_category,
            "compile_validation": None if compile_validation is None else compile_validation.to_dict(),
            "preflight_validation": None if preflight_validation is None else preflight_validation.to_dict(),
            "validation_notes": validation_notes,
            "based_on_generated_draft": result.based_on_generated_draft,
            "generation_run_id": result.generation_run_id,
            "draft_id": result.draft_id,
        }
    )



def run_validate_scenario_dir(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _revalidation_dir_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    result = ScenarioDirectoryRevalidationService().validate(
        ScenarioDirectoryRevalidationRequest(
            directory_path=Path(args.path),
            validation_mode=args.mode,
            workspace_root=Path(args.workspace_root),
        )
    )
    validation_notes = _validation_notes_for_directory(result.validation_mode, result.results)
    return to_json_safe(
        {
            "status": result.status.value,
            "directory_path": result.directory_path,
            "validation_mode": result.validation_mode,
            "scenario_count": result.scenario_count,
            "failure_count": result.failure_count,
            "readiness_counts": result.readiness_counts,
            "failure_items": result.failure_items,
            "validation_notes": validation_notes,
            "results": [item.to_dict() for item in result.results],
        }
    )



def _validation_notes_for_result(
    validation_mode: str,
    compile_validation: Any,
    preflight_validation: Any,
) -> list[str]:
    if validation_mode == "compile" and compile_validation is not None:
        warnings = getattr(compile_validation, "warnings", [])
        if warnings:
            return [
                "Compile mode is structural only: env-backed external inputs are declared but not resolved here.",
                "Run --mode preflight to verify that the selected environment file resolves all required external variables.",
            ]
    if validation_mode == "preflight" and preflight_validation is not None:
        preflight_status = getattr(preflight_validation, "preflight_status", None)
        if preflight_status == ScenarioPreflightStatus.SUCCESS:
            return [
                "Preflight mode includes environment resolution and dependency checks in addition to compile validation."
            ]
        if preflight_status == ScenarioPreflightStatus.FAILED:
            return _preflight_blocked_notes()
    return []



def _validation_notes_for_directory(validation_mode: str, results: list[Any]) -> list[str]:
    if validation_mode == "preflight":
        for item in results:
            preflight_validation = getattr(item, "preflight_validation", None)
            if (
                preflight_validation is not None
                and getattr(preflight_validation, "preflight_status", None) == ScenarioPreflightStatus.FAILED
            ):
                return _preflight_blocked_notes()
        return []
    if validation_mode == "compile":
        for item in results:
            compile_validation = getattr(item, "compile_validation", None)
            warnings = [] if compile_validation is None else getattr(compile_validation, "warnings", [])
            if warnings:
                return [
                    "Compile directory validation is structural only: env-backed external inputs remain unresolved by design.",
                    "Use --mode preflight for environment-aware validation of the promoted scenario directory.",
                ]
    return []


def _preflight_blocked_notes() -> list[str]:
    return [
        (
            "Preflight blockers are environment/readiness evidence. Resolve env/config/dependencies first, "
            "or get explicit operator approval before changing authored coverage scope."
        ),
        (
            "Do not remove env-backed variables, request fields, assertions, or DB verification only to make "
            "preflight pass unless implementation/schema evidence proves they are unnecessary."
        ),
    ]



def _average_completeness_ratio(review_set: Any) -> float:
    if not review_set.items:
        return 0.0
    total = sum(item.checklist.completeness_ratio for item in review_set.items)
    return round(total / len(review_set.items), 3)



def _close_to_runnable_count(review_set: Any) -> int:
    return sum(
        1
        for item in review_set.items
        if item.parse_status.value == "valid"
        and item.checklist.completeness_ratio >= 0.6
        and item.route_status.startswith("resolved")
    )

