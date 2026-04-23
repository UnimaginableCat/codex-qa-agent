"""Assembly of canonical test-plan domain models from normalized source models."""

from __future__ import annotations

from tools.generation.domain.models import (
    GenerationSourceInput,
    NormalizedProseSource,
    NormalizedTestPlan,
    PlannedTestCase,
    ProseTestCaseDraft,
    TraceabilityLink,
    TraceabilityMap,
)


class NormalizedTestPlanAssembler:
    """Build canonical plan and traceability models from normalized source drafts."""

    def assemble(
        self,
        source_input: GenerationSourceInput,
        normalized_source: NormalizedProseSource,
    ) -> NormalizedTestPlan:
        return NormalizedTestPlan(
            plan_id=f"plan-{source_input.source_id}",
            source_id=source_input.source_id,
            project=source_input.project,
            title=normalized_source.title,
            test_cases=[
                self._planned_case_from_draft(draft)
                for draft in normalized_source.test_case_drafts
            ],
            assumptions=list(normalized_source.assumptions),
            metadata={
                "generation_phase": "prose_plan_generation",
                "normalizer": normalized_source.metadata.get("normalizer", "unknown"),
                "scenario_synthesis": "out_of_scope",
            },
        )

    def build_traceability_map(
        self,
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
    def _planned_case_from_draft(draft: ProseTestCaseDraft) -> PlannedTestCase:
        return PlannedTestCase(
            case_id=draft.draft_id,
            title=draft.title,
            objective=draft.objective,
            source_refs=[draft.source_ref],
            preconditions=list(draft.preconditions),
            steps=list(draft.steps),
            expected_results=list(draft.expected_results),
            priority=draft.priority,
            assumptions=list(draft.assumptions),
            open_questions=list(draft.open_questions),
            tags=list(draft.tags),
            metadata={"source": "prose-normalizer-v1"},
        )

