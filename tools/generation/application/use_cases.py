"""Application use case for Phase 1 test-plan generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tools.generation.domain.contracts import GenerationArtifactStore
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic
from tools.generation.enrichment import EvidenceToPlanEnricher, TestPlanEnricher
from tools.generation.evidence import (
    ApiSurfaceFactsExtractor,
    CodeFactsExtractor,
    CodeFactsScope,
    GenerationEvidenceBundle,
)
from tools.generation.intake.source import SourceIntakeService
from tools.generation.normalization.prose import ProseSourceNormalizer
from tools.generation.orchestration.context import initialize_generation_run_context
from tools.generation.persistence.artifacts import FileGenerationArtifactStore
from tools.generation.planning.assembly import NormalizedTestPlanAssembler
from tools.generation.read_models.results import GenerationRunResult
from tools.generation.rendering import ScenarioDraftPreviewService

from .models import GenerateTestPlanRequest, GenerationOutputMode
from .validation import build_generation_message, derive_generation_status


@dataclass(slots=True)
class GenerateTestPlanUseCase:
    """Stable application boundary for Phase 1 test-plan generation."""

    source_intake: SourceIntakeService = field(default_factory=SourceIntakeService)
    prose_normalizer: ProseSourceNormalizer = field(default_factory=ProseSourceNormalizer)
    plan_assembler: NormalizedTestPlanAssembler = field(default_factory=NormalizedTestPlanAssembler)
    artifact_store: GenerationArtifactStore = field(default_factory=FileGenerationArtifactStore)
    code_facts_extractor: CodeFactsExtractor = field(default_factory=ApiSurfaceFactsExtractor)
    test_plan_enricher: TestPlanEnricher = field(default_factory=EvidenceToPlanEnricher)
    scenario_draft_preview: ScenarioDraftPreviewService = field(default_factory=ScenarioDraftPreviewService)

    def execute(self, request: GenerateTestPlanRequest) -> GenerationRunResult:
        run_context = initialize_generation_run_context(
            request.source_input,
            workspace_root=request.workspace_root,
        )
        diagnostics = self._validate_request(request)

        intake_result = self.source_intake.resolve(request.source_input)
        diagnostics.extend(intake_result.diagnostics)

        normalization_result = self.prose_normalizer.normalize(
            intake_result.resolved_source_input,
            intake_result.content,
        )
        diagnostics.extend(normalization_result.diagnostics)

        normalized_plan = self.plan_assembler.assemble(
            intake_result.resolved_source_input,
            normalization_result.normalized_source,
        )
        traceability_map = self.plan_assembler.build_traceability_map(
            request.source_input,
            normalized_plan,
        )
        evidence_bundle = self._collect_evidence(request) if request.options.collect_code_facts else None
        enrichment_result = None
        if request.options.enrichment_enabled and evidence_bundle is not None:
            enrichment_result = self.test_plan_enricher.enrich(normalized_plan, evidence_bundle)
            normalized_plan = enrichment_result.enriched_plan
            traceability_map.links.extend(enrichment_result.traceability_links)
            diagnostics.extend(enrichment_result.diagnostics)
        scenario_render_result = None
        scenario_render_paths = {}
        if request.options.render_scenario_drafts and request.options.persist_artifacts:
            scenario_render_result, scenario_render_paths = self.scenario_draft_preview.render_and_persist(
                normalized_plan,
                run_context,
                self.artifact_store,
            )
            diagnostics.extend(scenario_render_result.diagnostics)

        final_status = derive_generation_status(
            diagnostics,
            allow_empty_plan=request.options.allow_empty_plan,
        )
        message = build_generation_message(final_status, diagnostics)
        artifact_paths = {}

        result = GenerationRunResult(
            run_context=run_context,
            final_status=final_status,
            message=message,
            normalized_plan=normalized_plan,
            traceability_map=traceability_map,
            normalized_source=normalization_result.normalized_source,
            evidence_bundle=evidence_bundle,
            enrichment_result=enrichment_result,
            scenario_render_result=scenario_render_result,
            diagnostics=diagnostics,
            artifact_paths=artifact_paths,
            details={
                "phase": "prose_plan_generation",
                "application_use_case": "GenerateTestPlanUseCase",
                "output_mode": request.output_mode.value,
                "scenario_synthesis": "out_of_scope",
                "enrichment": _enrichment_state(request, enrichment_result),
                "code_facts": "collected" if evidence_bundle is not None else "not_requested",
                "scenario_rendering": _scenario_rendering_state(request, scenario_render_result),
            },
        )

        if request.options.persist_artifacts:
            artifact_paths.update(
                {
                    "context": self.artifact_store.write_context(run_context),
                    "source_input": self.artifact_store.write_source_input(
                        run_context,
                        intake_result.resolved_source_input,
                    ),
                    "normalized_source": self.artifact_store.write_normalized_source(
                        run_context,
                        normalization_result.normalized_source,
                    ),
                    "normalized_plan": self.artifact_store.write_normalized_plan(
                        run_context,
                        normalized_plan,
                    ),
                    "traceability_map": self.artifact_store.write_traceability_map(
                        run_context,
                        traceability_map,
                    ),
                    "diagnostics": self.artifact_store.write_diagnostics(run_context, diagnostics),
                }
            )
            if evidence_bundle is not None:
                artifact_paths["evidence"] = self.artifact_store.write_evidence_bundle(
                    run_context,
                    evidence_bundle,
                )
            if enrichment_result is not None:
                artifact_paths["enriched_plan"] = self.artifact_store.write_enriched_plan(
                    run_context,
                    normalized_plan,
                )
                artifact_paths["enrichment_result"] = self.artifact_store.write_enrichment_result(
                    run_context,
                    enrichment_result,
                )
                artifact_paths["traceability_map"] = self.artifact_store.write_traceability_map(
                    run_context,
                    traceability_map,
                )
            artifact_paths.update(scenario_render_paths)
            artifact_paths["summary"] = self.artifact_store.write_summary(run_context, result.to_dict())

        return result

    def _collect_evidence(self, request: GenerateTestPlanRequest) -> GenerationEvidenceBundle:
        scope = request.evidence_scope or CodeFactsScope(scope_id=f"{request.source_input.source_id}-evidence")
        return self.code_facts_extractor.extract(
            self._resolve_project_path(request),
            scope,
        )

    @staticmethod
    def _validate_request(request: GenerateTestPlanRequest) -> list[GenerationDiagnostic]:
        diagnostics: list[GenerationDiagnostic] = []
        if request.output_mode != GenerationOutputMode.TEST_PLAN:
            diagnostics.append(
                GenerationDiagnostic(
                    code="unsupported_output_mode",
                    message="Only test-plan output is supported in this generation phase.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=request.source_input.source_id,
                    details={"output_mode": request.output_mode.value},
                )
            )
        if request.options.enrichment_enabled and not request.options.collect_code_facts:
            diagnostics.append(
                GenerationDiagnostic(
                    code="enrichment_requires_evidence",
                    message="Evidence-based enrichment requires collect_code_facts=True.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=request.source_input.source_id,
                )
            )
        if request.options.render_scenario_drafts and not request.options.persist_artifacts:
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_rendering_requires_persistence",
                    message="Scenario draft rendering preview requires artifact persistence.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=request.source_input.source_id,
                )
            )
        return diagnostics

    @staticmethod
    def _resolve_project_path(request: GenerateTestPlanRequest) -> Path:
        if request.project_path is not None:
            return request.project_path
        project_path = Path(request.source_input.project)
        if project_path.is_absolute():
            return project_path
        if request.workspace_root is not None:
            return request.workspace_root / project_path
        return project_path


def _enrichment_state(request: GenerateTestPlanRequest, enrichment_result: object | None) -> str:
    if enrichment_result is not None:
        return "applied"
    if request.options.enrichment_enabled:
        return "skipped_no_evidence"
    return "not_requested"


def _scenario_rendering_state(request: GenerateTestPlanRequest, render_result: object | None) -> str:
    if render_result is not None:
        return "rendered"
    if request.options.render_scenario_drafts:
        return "skipped_no_persistence"
    return "not_requested"
