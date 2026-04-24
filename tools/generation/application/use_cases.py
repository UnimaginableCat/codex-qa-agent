"""Application use case for Phase 1 test-plan generation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from tools.generation.authoring import validate_agent_plan_input
from tools.generation.domain.contracts import GenerationArtifactStore
from tools.generation.domain.models import (
    AgentTestPlanInput,
    DiagnosticSeverity,
    GenerationDiagnostic,
    GenerationSourceInput,
    NormalizedProseSource,
    NormalizedTestPlan,
    SourceInputFormat,
    TraceabilityMap,
)
from tools.generation.enrichment import EvidenceToPlanEnricher, TestPlanEnricher
from tools.generation.enrichment.models import CoverageAssessmentResult
from tools.generation.enrichment.services import TestPlanCoverageAnalyzer
from tools.generation.evidence import (
    CodeFactsExtractionService,
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

from .models import GenerateTestPlanRequest, GenerationInputMode, GenerationOutputMode
from .validation import build_generation_message, derive_generation_status


@dataclass(slots=True)
class GenerateTestPlanUseCase:
    """Stable application boundary for Phase 1 test-plan generation."""

    source_intake: SourceIntakeService = field(default_factory=SourceIntakeService)
    prose_normalizer: ProseSourceNormalizer = field(default_factory=ProseSourceNormalizer)
    plan_assembler: NormalizedTestPlanAssembler = field(default_factory=NormalizedTestPlanAssembler)
    artifact_store: GenerationArtifactStore = field(default_factory=FileGenerationArtifactStore)
    code_facts_extraction_service: CodeFactsExtractionService = field(default_factory=CodeFactsExtractionService)
    test_plan_enricher: TestPlanEnricher = field(default_factory=EvidenceToPlanEnricher)
    coverage_analyzer: TestPlanCoverageAnalyzer = field(default_factory=TestPlanCoverageAnalyzer)
    scenario_draft_preview: ScenarioDraftPreviewService = field(default_factory=ScenarioDraftPreviewService)

    def execute(self, request: GenerateTestPlanRequest) -> GenerationRunResult:
        run_context = initialize_generation_run_context(
            request.source_input,
            workspace_root=request.workspace_root,
        )
        diagnostics = self._validate_request(request)

        source_input_for_persistence = request.source_input
        if request.input_mode == GenerationInputMode.AGENT_PLAN:
            if request.agent_plan is None:
                normalized_source = _empty_agent_plan_source_projection(request)
                normalized_plan = _empty_agent_plan(request)
                traceability_map = TraceabilityMap(source_id=request.source_input.source_id)
            else:
                source_input_for_persistence = _source_input_from_agent_plan(
                    request.source_input,
                    request.agent_plan,
                )
                normalized_source = _normalized_source_from_agent_plan(request.agent_plan)
                normalized_plan = self.plan_assembler.assemble_from_agent_plan(request.agent_plan)
                traceability_map = self.plan_assembler.build_agent_plan_traceability_map(
                    request.agent_plan,
                    normalized_plan,
                )
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_input_captured",
                        message="Agent-authored plan input accepted as a typed generation model.",
                        severity=DiagnosticSeverity.INFO,
                        source_ref=request.agent_plan.source_id,
                    )
                )
        else:
            intake_result = self.source_intake.resolve(request.source_input)
            diagnostics.extend(intake_result.diagnostics)

            normalization_result = self.prose_normalizer.normalize(
                intake_result.resolved_source_input,
                intake_result.content,
            )
            diagnostics.extend(normalization_result.diagnostics)

            normalized_source = normalization_result.normalized_source
            source_input_for_persistence = intake_result.resolved_source_input
            normalized_plan = self.plan_assembler.assemble(
                intake_result.resolved_source_input,
                normalized_source,
            )
            traceability_map = self.plan_assembler.build_traceability_map(
                request.source_input,
                normalized_plan,
            )
        evidence_bundle = self._collect_evidence(request) if request.options.collect_code_facts else None
        coverage_assessment = None
        if evidence_bundle is not None:
            coverage_assessment = self.coverage_analyzer.assess(normalized_plan, evidence_bundle)
            diagnostics.extend(coverage_assessment.diagnostics)
            diagnostics.extend(_coverage_guardrail_diagnostics(request, coverage_assessment))
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
            normalized_source=normalized_source,
            evidence_bundle=evidence_bundle,
            coverage_assessment=coverage_assessment,
            enrichment_result=enrichment_result,
            scenario_render_result=scenario_render_result,
            diagnostics=diagnostics,
            artifact_paths=artifact_paths,
            details={
                "phase": _generation_phase(request),
                "application_use_case": "GenerateTestPlanUseCase",
                "input_mode": request.input_mode.value,
                "output_mode": request.output_mode.value,
                "scenario_synthesis": "out_of_scope",
                "enrichment": _enrichment_state(request, enrichment_result),
                "code_facts": "collected" if evidence_bundle is not None else "not_requested",
                "coverage": _coverage_state(coverage_assessment),
                "coverage_summary": _coverage_summary(coverage_assessment),
                "coverage_guardrail": _coverage_guardrail_state(request, coverage_assessment),
                "scenario_rendering": _scenario_rendering_state(request, scenario_render_result),
            },
        )

        if request.options.persist_artifacts:
            artifact_paths.update(
                {
                    "bundle": run_context.artifact_dir,
                    "context": self.artifact_store.write_context(run_context),
                    **(
                        {}
                        if request.agent_plan is None
                        else {"agent_plan": self.artifact_store.write_agent_plan(run_context, request.agent_plan)}
                    ),
                    "source_input": self.artifact_store.write_source_input(
                        run_context,
                        source_input_for_persistence,
                    ),
                    "normalized_source": self.artifact_store.write_normalized_source(
                        run_context,
                        normalized_source,
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
            if coverage_assessment is not None:
                artifact_paths["coverage_assessment"] = self.artifact_store.write_coverage_assessment(
                    run_context,
                    coverage_assessment,
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
        scope = _resolved_evidence_scope(request)
        return self.code_facts_extraction_service.extract(
            self._resolve_project_path(request),
            scope,
        )

    @staticmethod
    def _validate_request(request: GenerateTestPlanRequest) -> list[GenerationDiagnostic]:
        diagnostics: list[GenerationDiagnostic] = []
        if request.input_mode == GenerationInputMode.AGENT_PLAN:
            diagnostics.extend(validate_agent_plan_input(request.agent_plan, request.source_input.source_id))
        elif request.input_mode == GenerationInputMode.PROSE:
            pass
        else:
            diagnostics.append(
                GenerationDiagnostic(
                    code="unsupported_input_mode",
                    message="Only agent_plan and prose input modes are supported.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=request.source_input.source_id,
                    details={"input_mode": str(request.input_mode)},
                )
            )
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
        if request.options.strict_coverage and not request.options.collect_code_facts:
            diagnostics.append(
                GenerationDiagnostic(
                    code="strict_coverage_requires_evidence",
                    message="Strict coverage guardrail requires collect_code_facts=True and an explicit evidence scope.",
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


def _coverage_state(coverage_assessment: CoverageAssessmentResult | None) -> str:
    if coverage_assessment is None:
        return "not_requested"
    if coverage_assessment.uncovered_case_ids or coverage_assessment.uncovered_fact_ids:
        return "gaps_detected"
    if coverage_assessment.ambiguous_case_ids or coverage_assessment.duplicated_fact_ids:
        return "overlaps_detected"
    return "aligned"


def _coverage_summary(coverage_assessment: CoverageAssessmentResult | None) -> dict[str, int] | str:
    if coverage_assessment is None:
        return "not_requested"
    return {
        "api_case_count": coverage_assessment.api_case_count,
        "api_fact_count": coverage_assessment.api_fact_count,
        "covered_case_count": len(coverage_assessment.covered_case_ids),
        "uncovered_case_count": len(coverage_assessment.uncovered_case_ids),
        "covered_fact_count": len(coverage_assessment.covered_fact_ids),
        "uncovered_fact_count": len(coverage_assessment.uncovered_fact_ids),
        "ambiguous_case_count": len(coverage_assessment.ambiguous_case_ids),
        "duplicated_fact_count": len(coverage_assessment.duplicated_fact_ids),
        "weak_fact_count": len(coverage_assessment.weak_fact_ids),
    }


def _coverage_guardrail_state(
    request: GenerateTestPlanRequest,
    coverage_assessment: CoverageAssessmentResult | None,
) -> str:
    if not request.options.strict_coverage:
        return "not_requested"
    if coverage_assessment is None:
        return "requires_evidence"
    if coverage_assessment.uncovered_case_ids or coverage_assessment.uncovered_fact_ids:
        return "blocked"
    return "satisfied"


def _coverage_guardrail_diagnostics(
    request: GenerateTestPlanRequest,
    coverage_assessment: CoverageAssessmentResult | None,
) -> list[GenerationDiagnostic]:
    if not request.options.strict_coverage or coverage_assessment is None:
        return []
    diagnostics: list[GenerationDiagnostic] = []
    if coverage_assessment.uncovered_case_ids:
        diagnostics.append(
            GenerationDiagnostic(
                code="coverage_guardrail_uncovered_cases",
                message="Strict coverage guardrail requires every authored API case to match at least one extracted endpoint fact.",
                severity=DiagnosticSeverity.WARNING,
                source_ref=request.source_input.source_id,
                details={"uncovered_case_ids": coverage_assessment.uncovered_case_ids},
            )
        )
    if coverage_assessment.uncovered_fact_ids:
        diagnostics.append(
            GenerationDiagnostic(
                code="coverage_guardrail_uncovered_facts",
                message="Strict coverage guardrail requires every extracted endpoint fact to be covered by at least one authored API case.",
                severity=DiagnosticSeverity.WARNING,
                source_ref=request.source_input.source_id,
                details={"uncovered_fact_ids": coverage_assessment.uncovered_fact_ids},
            )
        )
    return diagnostics


def _generation_phase(request: GenerateTestPlanRequest) -> str:
    if request.input_mode == GenerationInputMode.AGENT_PLAN:
        return "agent_plan_generation"
    return "prose_plan_generation"


def _resolved_evidence_scope(request: GenerateTestPlanRequest) -> CodeFactsScope:
    if request.evidence_scope is not None:
        return request.evidence_scope
    if request.agent_plan is not None and request.agent_plan.evidence_scope:
        payload = dict(request.agent_plan.evidence_scope)
        scope_id = str(payload.get("scope_id") or f"{request.source_input.source_id}-evidence")
        stack_hint = payload.get("stack_hint")
        stack_hint_value = None
        if stack_hint not in {None, ""}:
            try:
                stack_hint_value = CodeFactsScope.from_dict(
                    {"scope_id": scope_id, "stack_hint": stack_hint}
                ).stack_hint
            except ValueError:
                stack_hint_value = None
        file_patterns = payload.get("file_patterns", ["*.py", "*.java"])
        if not isinstance(file_patterns, list):
            file_patterns = ["*.py", "*.java"]
        paths = payload.get("paths", [])
        if not isinstance(paths, list):
            paths = []
        max_files = payload.get("max_files", 20)
        try:
            max_files_value = int(max_files)
        except (TypeError, ValueError):
            max_files_value = 20
        return CodeFactsScope(
            scope_id=scope_id,
            paths=[Path(str(item)) for item in paths],
            file_patterns=[str(item) for item in file_patterns],
            max_files=max_files_value,
            stack_hint=stack_hint_value,
        )
    return CodeFactsScope(scope_id=f"{request.source_input.source_id}-evidence")


def _source_input_from_agent_plan(
    original_source_input: GenerationSourceInput,
    agent_plan: AgentTestPlanInput,
) -> GenerationSourceInput:
    return GenerationSourceInput(
        source_id=agent_plan.source_id,
        project=agent_plan.project,
        input_format=SourceInputFormat.STRUCTURED,
        name=agent_plan.title,
        content=json.dumps(agent_plan.to_dict(), ensure_ascii=False),
        source_path=original_source_input.source_path,
        metadata={
            **dict(original_source_input.metadata),
            "input_mode": GenerationInputMode.AGENT_PLAN.value,
        },
    )


def _normalized_source_from_agent_plan(agent_plan: AgentTestPlanInput) -> NormalizedProseSource:
    """Project agent-authored input into the existing normalized-source artifact slot."""

    return NormalizedProseSource(
        source_id=agent_plan.source_id,
        project=agent_plan.project,
        title=agent_plan.title,
        normalized_text=agent_plan.goal,
        test_case_drafts=[],
        assumptions=list(agent_plan.assumptions),
        open_questions=list(agent_plan.open_questions),
        metadata={
            "normalizer": "agent-plan-adapter-v1",
            "input_mode": "agent_plan",
            "planned_case_count": len(agent_plan.planned_test_cases),
        },
    )


def _empty_agent_plan_source_projection(request: GenerateTestPlanRequest) -> NormalizedProseSource:
    return NormalizedProseSource(
        source_id=request.source_input.source_id,
        project=request.source_input.project,
        title=request.source_input.name,
        normalized_text="",
        test_case_drafts=[],
        metadata={
            "normalizer": "agent-plan-adapter-v1",
            "input_mode": "agent_plan",
            "planned_case_count": 0,
        },
    )


def _empty_agent_plan(request: GenerateTestPlanRequest) -> NormalizedTestPlan:
    return NormalizedTestPlan(
        plan_id=f"plan-{request.source_input.source_id}",
        source_id=request.source_input.source_id,
        project=request.source_input.project,
        title=request.source_input.name,
        test_cases=[],
        metadata={
            "generation_phase": "agent_plan_generation",
            "input_mode": "agent_plan",
            "normalizer": "agent-plan-adapter-v1",
            "scenario_synthesis": "out_of_scope",
        },
    )
