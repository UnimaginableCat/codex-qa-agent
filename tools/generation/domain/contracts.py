"""Persistence contracts for generation pipeline artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import (
    GenerationDiagnostic,
    GenerationRunContext,
    GenerationSourceInput,
    NormalizedTestPlan,
    TraceabilityMap,
)


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

    def write_summary(self, run_context: GenerationRunContext, summary: dict[str, object]) -> Path:
        """Persist the run summary read model."""
        ...
