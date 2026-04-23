"""Minimal orchestration skeleton for Phase 1 generation foundation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tools.common.statuses import StepStatus
from tools.generation.domain.contracts import GenerationArtifactStore
from tools.generation.domain.models import (
    DiagnosticSeverity,
    GenerationDiagnostic,
    GenerationSourceInput,
    NormalizedTestPlan,
    PlannedTestCase,
    TraceabilityLink,
    TraceabilityMap,
)
from tools.generation.persistence.artifacts import FileGenerationArtifactStore
from tools.generation.read_models.results import GenerationRunResult

from .context import initialize_generation_run_context


@dataclass(slots=True)
class GenerationPipelineService:
    """Phase 1 vertical slice for capture, normalization shell, and persistence."""

    artifact_store: GenerationArtifactStore = field(default_factory=FileGenerationArtifactStore)

    def run(
        self,
        source_input: GenerationSourceInput,
        workspace_root: Path | None = None,
    ) -> GenerationRunResult:
        run_context = initialize_generation_run_context(source_input, workspace_root)
        diagnostics = self._validate_source_input(source_input)
        normalized_plan = self._build_minimal_normalized_plan(source_input)
        traceability_map = self._build_traceability_map(source_input, normalized_plan)
        final_status = self._derive_status(diagnostics)
        message = self._build_message(final_status, diagnostics)

        artifact_paths = {
            "context": self.artifact_store.write_context(run_context),
            "source_input": self.artifact_store.write_source_input(run_context, source_input),
            "normalized_plan": self.artifact_store.write_normalized_plan(run_context, normalized_plan),
            "traceability_map": self.artifact_store.write_traceability_map(
                run_context,
                traceability_map,
            ),
            "diagnostics": self.artifact_store.write_diagnostics(run_context, diagnostics),
        }

        result = GenerationRunResult(
            run_context=run_context,
            final_status=final_status,
            message=message,
            normalized_plan=normalized_plan,
            traceability_map=traceability_map,
            diagnostics=diagnostics,
            artifact_paths=artifact_paths,
            details={"phase": "foundation", "scenario_synthesis": "out_of_scope"},
        )
        artifact_paths["summary"] = self.artifact_store.write_summary(run_context, result.to_dict())
        return result

    @staticmethod
    def _validate_source_input(source_input: GenerationSourceInput) -> list[GenerationDiagnostic]:
        diagnostics = [
            GenerationDiagnostic(
                code="source_input_captured",
                message="Source input accepted as a typed generation model.",
                severity=DiagnosticSeverity.INFO,
                source_ref=source_input.source_id,
            )
        ]
        if not source_input.content.strip() and source_input.source_path is None:
            diagnostics.append(
                GenerationDiagnostic(
                    code="source_content_empty",
                    message="Source input has no inline content or source path.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=source_input.source_id,
                )
            )
        return diagnostics

    @staticmethod
    def _build_minimal_normalized_plan(source_input: GenerationSourceInput) -> NormalizedTestPlan:
        title = source_input.name or source_input.source_id
        test_cases: list[PlannedTestCase] = []
        if source_input.content.strip() or source_input.source_path is not None:
            test_cases.append(
                PlannedTestCase(
                    case_id="tc-001",
                    title=title,
                    objective="Preserve source intent for later planner expansion.",
                    source_refs=[source_input.source_id],
                    metadata={"foundation_generated": True},
                )
            )

        return NormalizedTestPlan(
            plan_id=f"plan-{source_input.source_id}",
            source_id=source_input.source_id,
            project=source_input.project,
            title=title,
            test_cases=test_cases,
            assumptions=[
                "Phase 1 captures a minimal normalized shell only; full planning is out of scope."
            ],
            metadata={"generation_phase": "foundation"},
        )

    @staticmethod
    def _build_traceability_map(
        source_input: GenerationSourceInput,
        normalized_plan: NormalizedTestPlan,
    ) -> TraceabilityMap:
        links = [
            TraceabilityLink(
                source_ref=source_input.source_id,
                target_ref=normalized_plan.plan_id,
                relation="source_to_plan",
            )
        ]
        links.extend(
            TraceabilityLink(
                source_ref=source_ref,
                target_ref=test_case.case_id,
                relation="source_to_test_case",
            )
            for test_case in normalized_plan.test_cases
            for source_ref in test_case.source_refs
        )
        return TraceabilityMap(source_id=source_input.source_id, links=links)

    @staticmethod
    def _derive_status(diagnostics: list[GenerationDiagnostic]) -> StepStatus:
        if any(diagnostic.severity == DiagnosticSeverity.ERROR for diagnostic in diagnostics):
            return StepStatus.ERROR
        return StepStatus.PASS

    @staticmethod
    def _build_message(status: StepStatus, diagnostics: list[GenerationDiagnostic]) -> str:
        warning_count = sum(
            1 for diagnostic in diagnostics if diagnostic.severity == DiagnosticSeverity.WARNING
        )
        if status == StepStatus.ERROR:
            return "Generation foundation run failed with errors."
        if warning_count:
            return f"Generation foundation run completed with {warning_count} warning(s)."
        return "Generation foundation run completed."
