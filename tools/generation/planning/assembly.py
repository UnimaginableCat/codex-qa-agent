"""Assembly of canonical test-plan domain models from normalized source models."""

from __future__ import annotations

from tools.generation.domain.models import (
    AgentPlannedTestCaseInput,
    AgentTestPlanInput,
    GapCategory,
    GenerationSourceInput,
    NormalizedProseSource,
    NormalizedTestPlan,
    PlannedCaseGap,
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

    def assemble_from_agent_plan(self, agent_plan: AgentTestPlanInput) -> NormalizedTestPlan:
        """Build a canonical plan from an agent-authored structured plan draft."""

        return NormalizedTestPlan(
            plan_id=f"plan-{agent_plan.source_id}",
            source_id=agent_plan.source_id,
            project=agent_plan.project,
            title=agent_plan.title,
            test_cases=[
                self._planned_case_from_agent_case(agent_plan, case_input, index)
                for index, case_input in enumerate(agent_plan.planned_test_cases, start=1)
            ],
            assumptions=list(agent_plan.assumptions),
            metadata={
                "generation_phase": "agent_plan_generation",
                "input_mode": "agent_plan",
                "normalizer": "agent-plan-adapter-v1",
                "scenario_synthesis": "out_of_scope",
                "goal": agent_plan.goal,
                "open_questions": list(agent_plan.open_questions),
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

    def build_agent_plan_traceability_map(
        self,
        agent_plan: AgentTestPlanInput,
        normalized_plan: NormalizedTestPlan,
    ) -> TraceabilityMap:
        links = [
            TraceabilityLink(
                source_ref=agent_plan.source_id,
                target_ref=normalized_plan.plan_id,
                relation="agent_plan_to_plan",
            )
        ]
        links.extend(
            TraceabilityLink(
                source_ref=source_ref,
                target_ref=test_case.case_id,
                relation="agent_plan_case_to_test_case",
                metadata={"input_mode": "agent_plan"},
            )
            for test_case in normalized_plan.test_cases
            for source_ref in test_case.source_refs
        )
        return TraceabilityMap(
            source_id=agent_plan.source_id,
            links=links,
            metadata={"input_mode": "agent_plan"},
        )

    @staticmethod
    def _planned_case_from_draft(draft: ProseTestCaseDraft) -> PlannedTestCase:
        return PlannedTestCase(
            case_id=draft.draft_id,
            title=draft.title,
            objective=draft.objective,
            source_refs=[draft.source_ref],
            preconditions=list(draft.preconditions),
            steps=list(draft.steps),
            auth_strategy=[],
            requires_auth_strategy=False,
            request_headers={},
            request_params={},
            request_body=None,
            requires_request_body=False,
            observable_outcomes=[],
            expected_results=list(draft.expected_results),
            capture=[],
            requires_db_verification=False,
            priority=draft.priority,
            assumptions=list(draft.assumptions),
            open_questions=list(draft.open_questions),
            gaps=_infer_case_gaps(draft.open_questions, source="prose_normalized"),
            tags=list(draft.tags),
            db_verification=None,
            metadata={"source": "prose-normalizer-v1"},
        )

    @staticmethod
    def _planned_case_from_agent_case(
        agent_plan: AgentTestPlanInput,
        case_input: AgentPlannedTestCaseInput,
        index: int,
    ) -> PlannedTestCase:
        case_id = case_input.case_id.strip() or f"tc-{index:03d}"
        source_ref = f"{agent_plan.source_id}#case-{index:03d}"
        metadata = {
            "source": "agent-plan-v1",
            "input_mode": "agent_plan",
            "kind": case_input.kind,
            "requires_auth_strategy": case_input.requires_auth_strategy,
            "requires_db_verification": case_input.requires_db_verification,
            "requires_request_body": case_input.requires_request_body,
            **dict(case_input.metadata),
        }
        return PlannedTestCase(
            case_id=case_id,
            title=case_input.title,
            objective=case_input.objective,
            source_refs=[source_ref],
            preconditions=list(case_input.preconditions),
            steps=list(case_input.actions),
            auth_strategy=list(case_input.auth_strategy),
            requires_auth_strategy=case_input.requires_auth_strategy,
            request_headers=dict(case_input.request_headers),
            request_params=dict(case_input.request_params),
            request_body=case_input.request_body,
            requires_request_body=case_input.requires_request_body,
            observable_outcomes=list(case_input.observable_outcomes),
            expected_results=list(case_input.expected_outcomes),
            capture=list(case_input.capture),
            requires_db_verification=case_input.requires_db_verification,
            priority=case_input.priority,
            assumptions=list(case_input.assumptions),
            open_questions=list(case_input.unresolved_items),
            gaps=list(case_input.gaps) or _infer_case_gaps(case_input.unresolved_items, source="agent_authored"),
            tags=list(case_input.tags),
            planned_route=None if case_input.route is None else case_input.route,
            db_verification=None if case_input.db_verification is None else case_input.db_verification,
            metadata=metadata,
        )


def _infer_case_gaps(messages: list[str], *, source: str) -> list[PlannedCaseGap]:
    gaps: list[PlannedCaseGap] = []
    for message in messages:
        normalized = message.lower()
        if any(marker in normalized for marker in ("api endpoint", "which endpoint", "endpoint should", "executable detail")):
            category = GapCategory.ENDPOINT_DETAIL
        elif any(marker in normalized for marker in ("api, ui action, data setup", "concrete api", "concrete executable detail")):
            category = GapCategory.EXECUTABLE_DETAIL
        elif any(marker in normalized for marker in ("auth", "authorization", "credentials fixture")):
            category = GapCategory.AUTH_STRATEGY
        elif any(marker in normalized for marker in ("environment", "env", "fixture")):
            category = GapCategory.ENVIRONMENT
        elif any(marker in normalized for marker in ("assert", "expected result")):
            category = GapCategory.ASSERTION_DETAIL
        elif any(marker in normalized for marker in ("data setup", "fixture", "seed")):
            category = GapCategory.DATA_SETUP
        else:
            category = GapCategory.UNKNOWN
        gaps.append(
            PlannedCaseGap(
                category=category,
                message=message,
                source=source,
            )
        )
    return gaps

