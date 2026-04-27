"""Application use case for Phase 1 test-plan generation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

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
    scenario_draft_preview: ScenarioDraftPreviewService = field(default_factory=ScenarioDraftPreviewService)

    def execute(self, request: GenerateTestPlanRequest) -> GenerationRunResult:
        run_context = initialize_generation_run_context(
            request.source_input,
            workspace_root=request.workspace_root,
        )
        diagnostics = self._validate_request(request)

        source_input_for_persistence = request.source_input
        if request.input_mode in {GenerationInputMode.AGENT_PLAN, GenerationInputMode.AUTHORING_PLAN}:
            if request.agent_plan is None:
                normalized_source = _empty_agent_plan_source_projection(request)
                normalized_plan = _empty_agent_plan(request)
                traceability_map = TraceabilityMap(source_id=request.source_input.source_id)
            else:
                if request.input_mode == GenerationInputMode.AUTHORING_PLAN:
                    source_input_for_persistence = request.source_input
                else:
                    source_input_for_persistence = _source_input_from_agent_plan(
                        request.source_input,
                        request.agent_plan,
                    )
                normalized_source = _normalized_source_from_agent_plan(
                    request.agent_plan,
                    input_mode=request.input_mode.value,
                )
                normalized_plan = self.plan_assembler.assemble_from_agent_plan(request.agent_plan)
                traceability_map = self.plan_assembler.build_agent_plan_traceability_map(
                    request.agent_plan,
                    normalized_plan,
                )
                diagnostics.append(
                    GenerationDiagnostic(
                        code=(
                            "authoring_plan_compiled"
                            if request.input_mode == GenerationInputMode.AUTHORING_PLAN
                            else "agent_plan_input_captured"
                        ),
                        message=(
                            "Authoring plan compiled into the typed generation model."
                            if request.input_mode == GenerationInputMode.AUTHORING_PLAN
                            else "Agent-authored plan input accepted as a typed generation model."
                        ),
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
            scenario_render_result=scenario_render_result,
            diagnostics=diagnostics,
            artifact_paths=artifact_paths,
            details={
                "phase": _generation_phase(request),
                "application_use_case": "GenerateTestPlanUseCase",
                "input_mode": request.input_mode.value,
                "output_mode": request.output_mode.value,
                "scenario_synthesis": "out_of_scope",
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
            artifact_paths.update(scenario_render_paths)
            artifact_paths["summary"] = self.artifact_store.write_summary(run_context, result.to_dict())

        return result

    @staticmethod
    def _validate_request(request: GenerateTestPlanRequest) -> list[GenerationDiagnostic]:
        diagnostics: list[GenerationDiagnostic] = []
        if request.input_mode in {GenerationInputMode.AGENT_PLAN, GenerationInputMode.AUTHORING_PLAN}:
            diagnostics.extend(validate_agent_plan_input(request.agent_plan, request.source_input.source_id))
        elif request.input_mode == GenerationInputMode.PROSE:
            pass
        else:
            diagnostics.append(
                GenerationDiagnostic(
                    code="unsupported_input_mode",
                    message="Only authoring_plan, agent_plan, and prose input modes are supported.",
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


def _scenario_rendering_state(request: GenerateTestPlanRequest, render_result: object | None) -> str:
    if render_result is not None:
        return "rendered"
    if request.options.render_scenario_drafts:
        return "skipped_no_persistence"
    return "not_requested"


def _generation_phase(request: GenerateTestPlanRequest) -> str:
    if request.input_mode == GenerationInputMode.AUTHORING_PLAN:
        return "authoring_plan_generation"
    if request.input_mode == GenerationInputMode.AGENT_PLAN:
        return "agent_plan_generation"
    return "prose_plan_generation"


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


def _normalized_source_from_agent_plan(
    agent_plan: AgentTestPlanInput,
    *,
    input_mode: str = "agent_plan",
) -> NormalizedProseSource:
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
            "input_mode": input_mode,
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
