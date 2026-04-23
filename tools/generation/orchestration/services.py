"""Backward-compatible facade for Phase 1 test-plan generation."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tools.generation.domain.models import GenerationSourceInput
from tools.generation.read_models.results import GenerationRunResult

if TYPE_CHECKING:
    from tools.generation.application.use_cases import GenerateTestPlanUseCase
    from tools.generation.domain.contracts import GenerationArtifactStore
    from tools.generation.normalization.prose import ProseSourceNormalizer


class GenerationPipelineService:
    """Compatibility facade over the stable GenerateTestPlanUseCase boundary."""

    def __init__(
        self,
        *,
        artifact_store: "GenerationArtifactStore | None" = None,
        source_normalizer: "ProseSourceNormalizer | None" = None,
        use_case: "GenerateTestPlanUseCase | None" = None,
    ) -> None:
        self._artifact_store = artifact_store
        self._source_normalizer = source_normalizer
        self._use_case = use_case

    def run(
        self,
        source_input: GenerationSourceInput,
        workspace_root: Path | None = None,
    ) -> GenerationRunResult:
        from tools.generation.application.models import GenerateTestPlanRequest
        from tools.generation.application.use_cases import GenerateTestPlanUseCase
        from tools.generation.intake.source import SourceIntakeService
        from tools.generation.planning.assembly import NormalizedTestPlanAssembler

        use_case_kwargs = {
            "source_intake": SourceIntakeService(),
            "plan_assembler": NormalizedTestPlanAssembler(),
        }
        if self._source_normalizer is not None:
            use_case_kwargs["prose_normalizer"] = self._source_normalizer
        if self._artifact_store is not None:
            use_case_kwargs["artifact_store"] = self._artifact_store
        use_case = self._use_case or GenerateTestPlanUseCase(**use_case_kwargs)
        return use_case.execute(
            GenerateTestPlanRequest(
                source_input=source_input,
                workspace_root=workspace_root,
            )
        )
