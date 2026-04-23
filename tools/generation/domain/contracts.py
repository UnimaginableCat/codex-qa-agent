"""Persistence contracts for generation pipeline artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import (
    GenerationDiagnostic,
    GenerationRunContext,
    GenerationSourceInput,
    NormalizedProseSource,
    NormalizedTestPlan,
    TraceabilityMap,
)
from tools.generation.enrichment.models import EnrichedTestPlanResult
from tools.generation.evidence.models import GenerationEvidenceBundle
from tools.generation.rendering.models import ScenarioDraftSet, ScenarioRenderResult
from tools.generation.review.models import ScenarioPromotionResult


class GenerationArtifactStore(Protocol):
    """Contract for durable generation run and artifact persistence."""

    def write_context(self, run_context: GenerationRunContext) -> Path:
        """Persist the generation run context."""
        ...

    def write_source_input(
        self,
        run_context: GenerationRunContext,
        source_input: GenerationSourceInput,
    ) -> Path:
        """Persist the typed source input captured for the run."""
        ...

    def write_normalized_source(
        self,
        run_context: GenerationRunContext,
        normalized_source: NormalizedProseSource,
    ) -> Path:
        """Persist the normalized prose source artifact."""
        ...

    def write_normalized_plan(
        self,
        run_context: GenerationRunContext,
        normalized_plan: NormalizedTestPlan,
    ) -> Path:
        """Persist the normalized test plan artifact."""
        ...

    def write_traceability_map(
        self,
        run_context: GenerationRunContext,
        traceability_map: TraceabilityMap,
    ) -> Path:
        """Persist source-to-plan traceability links."""
        ...

    def write_diagnostics(
        self,
        run_context: GenerationRunContext,
        diagnostics: list[GenerationDiagnostic],
    ) -> Path:
        """Persist generation diagnostics."""
        ...

    def write_evidence_bundle(
        self,
        run_context: GenerationRunContext,
        evidence_bundle: GenerationEvidenceBundle,
    ) -> Path:
        """Persist typed code facts and evidence diagnostics."""
        ...

    def write_enriched_plan(
        self,
        run_context: GenerationRunContext,
        normalized_plan: NormalizedTestPlan,
    ) -> Path:
        """Persist the enriched normalized plan as an explicit artifact."""
        ...

    def write_enrichment_result(
        self,
        run_context: GenerationRunContext,
        enrichment_result: EnrichedTestPlanResult,
    ) -> Path:
        """Persist enrichment result and applied/unapplied evidence projections."""
        ...

    def write_scenario_drafts(
        self,
        run_context: GenerationRunContext,
        draft_set: ScenarioDraftSet,
    ) -> list[Path]:
        """Persist generated scenario draft markdown files."""
        ...

    def write_scenario_render_result(
        self,
        run_context: GenerationRunContext,
        render_result: ScenarioRenderResult,
    ) -> Path:
        """Persist scenario render result, parser validation, and deferred items."""
        ...

    def write_promotion_result(
        self,
        run_context: GenerationRunContext,
        promotion_result: ScenarioPromotionResult,
    ) -> Path:
        """Persist scenario draft promotion outcome."""
        ...

    def write_summary(self, run_context: GenerationRunContext, summary: dict[str, object]) -> Path:
        """Persist the run summary read model."""
        ...
