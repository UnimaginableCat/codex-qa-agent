"""Draft promotion services."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tools.common.statuses import StepStatus
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic, GenerationRunContext
from tools.generation.persistence.artifacts import FileGenerationArtifactStore

from .review import ScenarioDraftReviewService
from ..artifacts import (
    _load_render_result,
    _load_run_context,
    _run_context_consistency_diagnostics,
)
from ..drafts import (
    _find_draft,
    _find_review_item,
    _find_validation,
    _promotion_batch_status,
    _promotion_review_gate_diagnostics,
)
from ..promotion_paths import (
    _promotion_header,
    _promotion_target_dir,
    _promoted_scenario_filename,
    _purge_target_dir,
    _resolve_target_dir,
)
from ..models import (
    ScenarioPromotionBatchRequest,
    ScenarioPromotionBatchResult,
    ScenarioPromotionRequest,
    ScenarioPromotionResult,
)


@dataclass(slots=True)
class ScenarioDraftPromotionService:
    """Promote explicitly selected parser-valid drafts into scenarios/."""

    review_service: ScenarioDraftReviewService = field(default_factory=ScenarioDraftReviewService)
    artifact_store: FileGenerationArtifactStore = field(default_factory=FileGenerationArtifactStore)

    def promote(self, request: ScenarioPromotionRequest) -> ScenarioPromotionResult:
        diagnostics: list[GenerationDiagnostic] = []
        try:
            run_context = _load_run_context(request.workspace_root, request.run_id)
            render_result = _load_render_result(run_context)
        except Exception as exc:  # noqa: BLE001
            result = ScenarioPromotionResult(
                run_id=request.run_id,
                draft_id=request.draft_id,
                status=StepStatus.ERROR,
                diagnostics=[
                    GenerationDiagnostic(
                        code="scenario_promotion_artifacts_unavailable",
                        message=f"Could not load generation draft artifacts: {exc}",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=request.run_id,
                    )
                ],
            )
            return result
        context_diagnostics = _run_context_consistency_diagnostics(run_context)
        if context_diagnostics:
            return self._finalize(run_context, request, StepStatus.BLOCKED, context_diagnostics)

        draft = _find_draft(render_result, request.draft_id)
        validation = _find_validation(render_result, request.draft_id)
        if draft is None:
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_draft_missing",
                    message="Selected draft id does not exist in this generation run.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=request.draft_id,
                )
            )
            return self._finalize(run_context, request, StepStatus.ERROR, diagnostics)

        source_path = run_context.artifact_dir / draft.relative_path
        if not source_path.exists():
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_source_missing",
                    message="Selected draft file is missing from generation artifacts.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(source_path),
                )
            )
            return self._finalize(
                run_context,
                request,
                StepStatus.ERROR,
                diagnostics,
                source_path=source_path,
            )
        if validation is None or not validation.parse_valid:
            if not request.allow_invalid:
                diagnostics.append(
                    GenerationDiagnostic(
                        code="scenario_promotion_invalid_draft",
                        message="Selected draft is not parser-valid; use allow_invalid only after operator review.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=request.draft_id,
                    )
                )
                return self._finalize(
                    run_context,
                    request,
                    StepStatus.ERROR,
                    diagnostics,
                    source_path=source_path,
                )
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_invalid_override",
                    message="Invalid draft promotion was allowed by explicit override.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=request.draft_id,
                )
            )

        try:
            review_set = self.review_service.review(request.run_id, workspace_root=request.workspace_root)
            review_item = _find_review_item(review_set, request.draft_id)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_review_unavailable",
                    message=f"Could not load draft review data before promotion: {exc}",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=request.draft_id,
                )
            )
            return self._finalize(
                run_context,
                request,
                StepStatus.ERROR,
                diagnostics,
                source_path=source_path,
            )
        review_gate_diagnostics = _promotion_review_gate_diagnostics(
            review_item,
            allow_known_gaps=request.allow_known_gaps,
            known_gaps_reviewed=request.known_gaps_reviewed,
        )
        diagnostics.extend(review_gate_diagnostics)
        if review_gate_diagnostics and (
            not request.allow_known_gaps
            or any(diagnostic.severity == DiagnosticSeverity.ERROR for diagnostic in review_gate_diagnostics)
        ):
            return self._finalize(
                run_context,
                request,
                StepStatus.BLOCKED,
                diagnostics,
                source_path=source_path,
            )

        try:
            target_dir = _resolve_target_dir(request.workspace_root, request.target_dir)
        except ValueError as exc:
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_invalid_target_dir",
                    message=str(exc),
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(request.target_dir),
                )
            )
            return self._finalize(
                run_context,
                request,
                StepStatus.ERROR,
                diagnostics,
                source_path=source_path,
            )
        target_dir = _promotion_target_dir(target_dir, run_context)
        if request.purge_target_dir:
            _purge_target_dir(target_dir)
        target_path = target_dir / _promoted_scenario_filename(run_context.source_id, request.draft_id)
        if target_path.exists():
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_target_exists",
                    message=(
                        "Promotion target already exists; existing scenario files are never overwritten. "
                        "For an intentional rerender/re-promote cycle, rerun promotion with --purge-target-dir "
                        "or choose a new --target-dir."
                    ),
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(target_path),
                )
            )
            return self._finalize(
                run_context,
                request,
                StepStatus.ERROR,
                diagnostics,
                source_path=source_path,
                target_path=target_path,
            )

        target_dir.mkdir(parents=True, exist_ok=True)
        draft_content = source_path.read_text(encoding="utf-8")
        target_path.write_text(_promotion_header(run_context.run_id, request.draft_id) + draft_content, encoding="utf-8")
        return self._finalize(
            run_context,
            request,
            StepStatus.PASS,
            diagnostics,
            source_path=source_path,
            target_path=target_path,
        )

    def _finalize(
        self,
        run_context: GenerationRunContext,
        request: ScenarioPromotionRequest,
        status: StepStatus,
        diagnostics: list[GenerationDiagnostic],
        *,
        source_path: Path | None = None,
        target_path: Path | None = None,
    ) -> ScenarioPromotionResult:
        result = ScenarioPromotionResult(
            run_id=request.run_id,
            draft_id=request.draft_id,
            status=status,
            source_path=source_path,
            target_path=target_path,
            diagnostics=diagnostics,
        )
        promotion_result_path = self.artifact_store.write_promotion_result(run_context, result)
        result.promotion_result_path = promotion_result_path
        return result


@dataclass(slots=True)
class ScenarioDraftBatchPromotionService:
    """Promote multiple drafts from one generation run into scenarios/."""

    promotion_service: ScenarioDraftPromotionService = field(default_factory=ScenarioDraftPromotionService)
    artifact_store: FileGenerationArtifactStore = field(default_factory=FileGenerationArtifactStore)

    def promote(self, request: ScenarioPromotionBatchRequest) -> ScenarioPromotionBatchResult:
        diagnostics: list[GenerationDiagnostic] = []
        try:
            run_context = _load_run_context(request.workspace_root, request.run_id)
            render_result = _load_render_result(run_context)
        except Exception as exc:  # noqa: BLE001
            return ScenarioPromotionBatchResult(
                run_id=request.run_id,
                status=StepStatus.ERROR,
                diagnostics=[
                    GenerationDiagnostic(
                        code="scenario_promotion_artifacts_unavailable",
                        message=f"Could not load generation draft artifacts: {exc}",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=request.run_id,
                    )
                ],
            )
        context_diagnostics = _run_context_consistency_diagnostics(run_context)
        if context_diagnostics:
            return self._finalize(
                run_context,
                request,
                StepStatus.BLOCKED,
                diagnostics=context_diagnostics,
                results=[],
                target_dir=None,
                promoted_count=0,
                error_count=0,
                blocked_count=0,
            )

        draft_ids = request.draft_ids or [draft.draft_id for draft in render_result.draft_set.drafts]
        if not draft_ids:
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_empty_draft_set",
                    message="No scenario drafts were found for this generation run.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=request.run_id,
                )
            )
            return self._finalize(
                run_context,
                request,
                StepStatus.ERROR,
                diagnostics=diagnostics,
                results=[],
            )

        try:
            target_dir = _promotion_target_dir(_resolve_target_dir(request.workspace_root, request.target_dir), run_context)
        except ValueError as exc:
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_invalid_target_dir",
                    message=str(exc),
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(request.target_dir),
                )
            )
            target_dir = None
            status = StepStatus.ERROR
            return self._finalize(
                run_context,
                request,
                status,
                diagnostics=diagnostics,
                results=[],
                target_dir=target_dir,
                promoted_count=0,
                error_count=0,
            )
        if request.purge_target_dir:
            _purge_target_dir(target_dir)
        results = [
            self.promotion_service.promote(
                ScenarioPromotionRequest(
                    run_id=request.run_id,
                    draft_id=draft_id,
                    workspace_root=request.workspace_root,
                    target_dir=request.target_dir,
                    allow_invalid=request.allow_invalid,
                    allow_known_gaps=request.allow_known_gaps,
                    known_gaps_reviewed=request.known_gaps_reviewed,
                    purge_target_dir=False,
                )
            )
            for draft_id in draft_ids
        ]
        promoted_count = sum(1 for item in results if item.status == StepStatus.PASS)
        error_count = sum(1 for item in results if item.status == StepStatus.ERROR)
        blocked_count = sum(1 for item in results if item.status == StepStatus.BLOCKED)
        status = _promotion_batch_status(results)
        diagnostics.extend(
            diagnostic
            for item in results
            for diagnostic in item.diagnostics
        )
        return self._finalize(
            run_context,
            request,
            status,
            diagnostics=diagnostics,
            results=results,
            target_dir=target_dir,
            promoted_count=promoted_count,
            error_count=error_count,
            blocked_count=blocked_count,
        )

    def _finalize(
        self,
        run_context: GenerationRunContext,
        request: ScenarioPromotionBatchRequest,
        status: StepStatus,
        *,
        diagnostics: list[GenerationDiagnostic],
        results: list[ScenarioPromotionResult],
        target_dir: Path | None = None,
        promoted_count: int = 0,
        error_count: int = 0,
        blocked_count: int = 0,
    ) -> ScenarioPromotionBatchResult:
        result = ScenarioPromotionBatchResult(
            run_id=request.run_id,
            status=status,
            requested_count=len(request.draft_ids) if request.draft_ids else len(results),
            promoted_count=promoted_count,
            error_count=error_count,
            blocked_count=blocked_count,
            target_dir=target_dir,
            results=results,
            diagnostics=diagnostics,
        )
        promotion_result_path = self.artifact_store.write_promotion_result(run_context, result)
        result.promotion_result_path = promotion_result_path
        return result
