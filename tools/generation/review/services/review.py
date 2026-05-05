"""Draft review service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic

from ..artifacts import (
    _load_render_result,
    _load_run_context,
    _run_context_consistency_diagnostics,
)
from ..drafts import (
    _build_deferred_review_item,
    _build_review_item,
    _group_render_diagnostics,
    _group_unsupported_checks,
)
from ..models import ScenarioDraftReviewSet


@dataclass(slots=True)
class ScenarioDraftReviewService:
    """Load generated draft artifacts and expose operator-facing review data."""

    def review(self, run_id: str, *, workspace_root: Path = Path(".")) -> ScenarioDraftReviewSet:
        run_context = _load_run_context(workspace_root, run_id)
        render_result = _load_render_result(run_context)
        validation_by_id = {
            validation.draft_id: validation for validation in render_result.validation_results
        }
        unsupported_by_case_id = _group_unsupported_checks(render_result)
        deferred_by_case_id = {item.case_id: item for item in render_result.draft_set.deferred_items}
        render_diagnostics_by_case_id = _group_render_diagnostics(render_result)
        items = [
            _build_review_item(
                run_context,
                draft,
                validation_by_id.get(draft.draft_id),
                unsupported_by_case_id.get(draft.case_id, []),
                deferred_by_case_id.get(draft.case_id),
                render_diagnostics_by_case_id.get(draft.case_id, []),
            )
            for draft in render_result.draft_set.drafts
        ]
        deferred_items = [
            _build_deferred_review_item(item, unsupported_by_case_id.get(item.case_id, []))
            for item in render_result.draft_set.deferred_items
        ]
        diagnostics: list[GenerationDiagnostic] = _run_context_consistency_diagnostics(run_context)
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
            deferred_items=deferred_items,
            diagnostics=diagnostics,
        )
