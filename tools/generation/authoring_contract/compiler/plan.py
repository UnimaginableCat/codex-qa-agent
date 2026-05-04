"""Agent plan construction for compiled authoring plans."""

from __future__ import annotations

from tools.generation.domain.models import AgentPlannedTestCaseInput, AgentTestPlanInput

from ..helpers import _authoring_defaults_metadata
from ..models import AuthoringPlan


def build_agent_plan(
    authoring_plan: AuthoringPlan,
    compiled_cases: list[AgentPlannedTestCaseInput],
) -> AgentTestPlanInput:
    return AgentTestPlanInput(
        source_id=authoring_plan.source_id,
        project=authoring_plan.project,
        title=authoring_plan.title,
        goal=authoring_plan.goal,
        scenario_variables=list(authoring_plan.defaults.scenario_variables),
        planned_test_cases=compiled_cases,
        assumptions=list(authoring_plan.assumptions),
        open_questions=list(authoring_plan.open_questions),
        metadata={
            **dict(authoring_plan.metadata),
            "authoring_contract_version": authoring_plan.version,
            "generation_phase": "authoring_plan_generation",
            "input_mode": "authoring_plan",
            "scope": authoring_plan.scope.to_dict(),
            "defaults": authoring_plan.defaults.to_dict(),
            **_authoring_defaults_metadata(authoring_plan),
        },
    )
