"""Read models for generation run outcomes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.domain.models import (
    GenerationDiagnostic,
    GenerationRunContext,
    NormalizedProseSource,
    NormalizedTestPlan,
    TraceabilityMap,
)
from tools.generation.enrichment.models import EnrichedTestPlanResult
from tools.generation.evidence.models import GenerationEvidenceBundle
from tools.generation.rendering.models import ScenarioRenderResult


@dataclass(slots=True)
class GenerationRunResult:
    """Structured service result for one generation foundation run."""

    run_context: GenerationRunContext
    final_status: StepStatus
    message: str
    normalized_plan: NormalizedTestPlan
    traceability_map: TraceabilityMap
    normalized_source: NormalizedProseSource | None = None
    evidence_bundle: GenerationEvidenceBundle | None = None
    enrichment_result: EnrichedTestPlanResult | None = None
    scenario_render_result: ScenarioRenderResult | None = None
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)
    artifact_paths: dict[str, Path] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = to_json_safe(asdict(self))
        payload["status"] = self.final_status.value
        return payload
