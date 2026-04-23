"""Services for reviewing and promoting generated scenario drafts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from tools.common.io import read_json_file
from tools.common.statuses import StepStatus
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic, GenerationRunContext
from tools.generation.persistence.artifacts import (
    GENERATION_RUNS_DIRNAME,
    FileGenerationArtifactStore,
)
from tools.generation.rendering.models import ScenarioDraft, ScenarioDraftValidationResult, ScenarioRenderResult

from .models import (
    ScenarioDraftParseStatus,
    ScenarioDraftReviewItem,
    ScenarioDraftReviewSet,
    ScenarioPromotionRequest,
    ScenarioPromotionResult,
)


@dataclass(slots=True)
class ScenarioDraftReviewService:
    """Load generated draft artifacts and expose operator-facing review data."""

    def review(self, run_id: str, *, workspace_root: Path = Path(".")) -> ScenarioDraftReviewSet:
        run_context = _load_run_context(workspace_root, run_id)
        render_result = _load_render_result(run_context)
        validation_by_id = {
            validation.draft_id: validation for validation in render_result.validation_results
        }
        unsupported_case_ids = {check.case_id for check in render_result.unsupported_checks}
        deferred_case_ids = {item.case_id for item in render_result.draft_set.deferred_items}
        items = [
            _build_review_item(
                run_context,
                draft,
                validation_by_id.get(draft.draft_id),
                draft.case_id in unsupported_case_ids,
                draft.case_id in deferred_case_ids,
            )
            for draft in render_result.draft_set.drafts
        ]
        diagnostics: list[GenerationDiagnostic] = []
        if not items:
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_draft_review_empty",
                    message="No scenario drafts were found for this generation run.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=run_id,
                )
            )
        return ScenarioDraftReviewSet(
            run_id=run_context.run_id,
            source_id=run_context.source_id,
            artifact_dir=run_context.artifact_dir,
            items=items,
            diagnostics=diagnostics,
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
        target_path = target_dir / f"{_slugify(run_context.source_id)}-{_slugify(request.draft_id)}.md"
        if target_path.exists():
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_target_exists",
                    message="Promotion target already exists; existing scenario files are never overwritten.",
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
        self.artifact_store.write_promotion_result(run_context, result)
        return result


def _load_run_context(workspace_root: Path, run_id: str) -> GenerationRunContext:
    context_path = workspace_root / GENERATION_RUNS_DIRNAME / run_id / "context.json"
    payload = read_json_file(context_path, "Generation run context")
    return GenerationRunContext.from_dict(dict(payload))


def _load_render_result(run_context: GenerationRunContext) -> ScenarioRenderResult:
    payload = read_json_file(run_context.artifact_dir / "scenario-render-result.json", "Scenario render result")
    return ScenarioRenderResult.from_dict(dict(payload))


def _build_review_item(
    run_context: GenerationRunContext,
    draft: ScenarioDraft,
    validation: ScenarioDraftValidationResult | None,
    has_unsupported_items: bool,
    has_deferred_items: bool,
) -> ScenarioDraftReviewItem:
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
    return ScenarioDraftReviewItem(
        draft_id=draft.draft_id,
        file_path=run_context.artifact_dir / draft.relative_path,
        parse_status=parse_status,
        diagnostics_summary=diagnostics_summary,
        has_unsupported_items=has_unsupported_items,
        has_deferred_items=has_deferred_items,
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


def _resolve_target_dir(workspace_root: Path, target_dir: Path) -> Path:
    target = target_dir if target_dir.is_absolute() else workspace_root / target_dir
    scenarios_root = (workspace_root / "scenarios").resolve()
    resolved = target.resolve()
    if resolved != scenarios_root and scenarios_root not in resolved.parents:
        raise ValueError("Promotion target directory must be under scenarios/.")
    return target


def _promotion_header(run_id: str, draft_id: str) -> str:
    return (
        "<!--\n"
        "generated_by: codex-qa-agent\n"
        f"generation_run_id: {run_id}\n"
        f"draft_id: {draft_id}\n"
        "source: draft-rendering-preview\n"
        "-->\n\n"
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug.lower() or "scenario"
