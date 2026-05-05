"""Scenario revalidation services."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tools.common.statuses import StepStatus
from tools.generation.rendering.models import ScenarioDraft, ScenarioDraftValidationResult
from tools.scenario_runner.parser import MarkdownScenarioParser

from ..common import _slugify
from ..drafts import (
    _build_draft_checklist,
    _build_edit_targets,
    _draft_readiness_category,
    _promotion_advisory,
    _revalidation_gap_summary,
    _route_binding_from_scenario,
)
from ..revalidation_batch import (
    _batch_revalidation_is_failure,
    _batch_revalidation_readiness_key,
    _promotion_metadata,
    _revalidation_title,
)
from ..validation import (
    _merge_compile_gaps,
    _merge_preflight_gaps,
    _parser_only_readiness,
)
from .validation import ScenarioCompileValidationService, ScenarioPreflightValidationService
from ..models import (
    ScenarioDirectoryRevalidationRequest,
    ScenarioDirectoryRevalidationResult,
    ScenarioDraftParseStatus,
    ScenarioRevalidationRequest,
    ScenarioRevalidationResult,
)


@dataclass(slots=True)
class ScenarioRevalidationService:
    """Parser-only validation for manually edited draft or promoted scenario files."""

    parser: MarkdownScenarioParser = field(default_factory=MarkdownScenarioParser)
    compile_validator: "ScenarioCompileValidationService" = field(default_factory=lambda: ScenarioCompileValidationService())
    preflight_validator: "ScenarioPreflightValidationService" = field(default_factory=lambda: ScenarioPreflightValidationService())

    def validate(self, request: ScenarioRevalidationRequest) -> ScenarioRevalidationResult:
        file_path = Path(request.file_path)
        markdown = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        parse_result = self.parser.parse_result(file_path)
        parse_status = (
            ScenarioDraftParseStatus.INVALID
            if parse_result.has_errors
            else ScenarioDraftParseStatus.VALID
        )
        metadata = _promotion_metadata(markdown)
        draft_id = metadata.get("draft_id") or _slugify(file_path.stem)
        draft = ScenarioDraft(
            draft_id=draft_id,
            case_id=draft_id,
            title=_revalidation_title(parse_result.scenario, file_path),
            markdown=markdown,
            relative_path=file_path,
            metadata={},
        )
        route_binding = _route_binding_from_scenario(parse_result.scenario)
        validation = ScenarioDraftValidationResult(
            draft_id=draft.draft_id,
            case_id=draft.case_id,
            path=file_path,
            parse_valid=parse_status == ScenarioDraftParseStatus.VALID,
            diagnostics=[diagnostic.to_dict() for diagnostic in parse_result.diagnostics],
        )
        gap_summary = _revalidation_gap_summary(
            draft,
            validation,
            route_binding=route_binding,
            scenario=parse_result.scenario,
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
            has_unsupported_items=False,
            has_deferred_items=False,
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
        compile_validation = None
        execution_readiness = _parser_only_readiness(parse_status, checklist)
        preflight_validation = None
        environment_readiness = None
        if request.validation_mode in {"compile", "preflight"}:
            compile_validation = self.compile_validator.validate(
                file_path=file_path,
                parse_status=parse_status,
                scenario=parse_result.scenario,
                checklist=checklist,
            )
            execution_readiness = compile_validation.readiness_category
            gap_summary = _merge_compile_gaps(gap_summary, compile_validation)
            edit_targets = _build_edit_targets(
                draft,
                checklist=checklist,
                gap_summary=gap_summary,
                parse_status=parse_status,
                route_binding=route_binding,
            )
        if request.validation_mode == "preflight":
            preflight_validation = self.preflight_validator.validate(
                file_path=file_path,
                workspace_root=Path(request.workspace_root),
                parse_status=parse_status,
                scenario=parse_result.scenario,
            )
            environment_readiness = preflight_validation.readiness_category
            gap_summary = _merge_preflight_gaps(gap_summary, preflight_validation)
            edit_targets = _build_edit_targets(
                draft,
                checklist=checklist,
                gap_summary=gap_summary,
                parse_status=parse_status,
                route_binding=route_binding,
            )

        return ScenarioRevalidationResult(
            file_path=file_path,
            parse_status=parse_status,
            diagnostics=[diagnostic.to_dict() for diagnostic in parse_result.diagnostics],
            checklist=checklist,
            gap_summary=gap_summary,
            edit_targets=edit_targets,
            promotion_advisory=promotion_advisory,
            completeness_ratio=checklist.completeness_ratio,
            based_on_generated_draft=bool(metadata),
            generation_run_id=metadata.get("generation_run_id", ""),
            draft_id=draft_id,
            validation_mode=request.validation_mode,
            compile_validation=compile_validation,
            preflight_validation=preflight_validation,
            execution_readiness_category=execution_readiness,
            environment_readiness_category=environment_readiness,
        )


@dataclass(slots=True)
class ScenarioDirectoryRevalidationService:
    """Batch revalidation for one promoted/generated scenario directory."""

    file_service: ScenarioRevalidationService = field(default_factory=ScenarioRevalidationService)

    def validate(self, request: ScenarioDirectoryRevalidationRequest) -> ScenarioDirectoryRevalidationResult:
        directory_path = Path(request.directory_path)
        scenario_files = sorted(directory_path.glob("*.md"))
        if not scenario_files:
            return ScenarioDirectoryRevalidationResult(
                directory_path=directory_path,
                validation_mode=request.validation_mode,
                status=StepStatus.ERROR,
                scenario_count=0,
                failure_count=0,
                readiness_counts={},
                failure_items=[],
                results=[],
            )
        results = [
            self.file_service.validate(
                ScenarioRevalidationRequest(
                    file_path=path,
                    validation_mode=request.validation_mode,
                    workspace_root=request.workspace_root,
                )
            )
            for path in scenario_files
        ]
        readiness_counts: dict[str, int] = {}
        failure_items: list[dict[str, object]] = []
        for result in results:
            readiness = _batch_revalidation_readiness_key(result)
            readiness_counts[readiness] = readiness_counts.get(readiness, 0) + 1
            if _batch_revalidation_is_failure(result, request.validation_mode):
                failure_items.append(
                    {
                        "file_path": result.file_path,
                        "parse_status": result.parse_status.value,
                        "readiness_category": readiness,
                        "compile_status": (
                            None if result.compile_validation is None else result.compile_validation.compile_status.value
                        ),
                        "preflight_status": (
                            None if result.preflight_validation is None else result.preflight_validation.preflight_status.value
                        ),
                        "gap_codes": list(result.gap_summary.gap_codes),
                    }
                )
        status = StepStatus.PASS if not failure_items else StepStatus.ERROR
        return ScenarioDirectoryRevalidationResult(
            directory_path=directory_path,
            validation_mode=request.validation_mode,
            status=status,
            scenario_count=len(results),
            failure_count=len(failure_items),
            readiness_counts=readiness_counts,
            failure_items=failure_items,
            results=results,
        )
