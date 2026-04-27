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
    PlannedWorkflowStep,
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
                **dict(agent_plan.metadata),
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
        case = PlannedTestCase(
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
            workflow_steps=[],
            requires_db_verification=False,
            priority=draft.priority,
            assumptions=list(draft.assumptions),
            open_questions=list(draft.open_questions),
            gaps=_infer_case_gaps(draft.open_questions, source="prose_normalized"),
            tags=list(draft.tags),
            db_verification=None,
            metadata={
                "source": "prose-normalizer-v1",
                "draft_steps": list(draft.steps),
            },
        )
        case.steps = _normalized_execution_outline(case)
        case.metadata["step_outline_version"] = "planned-execution-outline-v1"
        return case

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
            "authored_actions": list(case_input.actions),
            **_agent_plan_default_metadata(agent_plan),
            **dict(case_input.metadata),
        }
        case = PlannedTestCase(
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
            workflow_steps=[PlannedWorkflowStep.from_dict(step.to_dict()) for step in case_input.workflow_steps],
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
        case.steps = _normalized_execution_outline(case)
        case.metadata["step_outline_version"] = "planned-execution-outline-v1"
        return case


def _infer_case_gaps(messages: list[str], *, source: str) -> list[PlannedCaseGap]:
    gaps: list[PlannedCaseGap] = []
    for message in messages:
        normalized = message.lower()
        if any(marker in normalized for marker in ("api endpoint", "which endpoint", "endpoint should", "executable detail")):
            category = GapCategory.ENDPOINT_DETAIL
        elif any(marker in normalized for marker in ("api, ui action, data setup", "concrete api", "concrete executable detail")):
            category = GapCategory.EXECUTABLE_DETAIL
        elif any(
            marker in normalized
            for marker in (
                "runner variable",
                "variable declaration",
                "variable declarations",
                "generated variable",
                "generated variables",
                "machine-readable",
                "run_suffix",
                "email_suffix",
                "missing_user_id",
            )
        ):
            category = GapCategory.EXECUTABLE_DETAIL
        elif any(marker in normalized for marker in ("auth", "authorization", "credentials fixture")):
            category = GapCategory.AUTH_STRATEGY
        elif any(marker in normalized for marker in ("environment", "env", "fixture")):
            category = GapCategory.ENVIRONMENT
        elif any(marker in normalized for marker in ("assert", "expected result")):
            category = GapCategory.ASSERTION_DETAIL
        elif any(
            marker in normalized
            for marker in (
                "data setup",
                "fixture",
                "seed",
                "seeded",
                "must be supplied",
                "must be generated",
                "must be selected",
                "previously created",
                "pre-existing",
                "guaranteed absent",
                "setup step",
            )
        ):
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


def _normalized_execution_outline(test_case: PlannedTestCase) -> list[str]:
    if test_case.workflow_steps:
        return _workflow_execution_outline(test_case)
    authored_steps = [step.strip() for step in test_case.steps if step and step.strip()]
    outline: list[str] = []

    if _needs_preparation_step(test_case, authored_steps):
        outline.append(_preparation_step(test_case))

    if authored_steps:
        outline.extend(authored_steps)
    else:
        outline.append(_default_execution_step(test_case))

    if test_case.capture and not _has_capture_step(authored_steps):
        outline.append(
            "Capture the response values needed for later checks: "
            + ", ".join(test_case.capture)
            + "."
        )

    if _needs_verification_step(test_case, authored_steps):
        outline.append(_verification_step(test_case))

    if (test_case.db_verification is not None or test_case.requires_db_verification) and not _has_db_step(authored_steps):
        outline.append(_db_verification_step(test_case))

    return _dedupe_preserve_order(outline)


def _workflow_execution_outline(test_case: PlannedTestCase) -> list[str]:
    outline: list[str] = []
    for index, workflow_step in enumerate(test_case.workflow_steps, start=1):
        step_kind = workflow_step.step_type.strip().lower()
        if step_kind == "api":
            route = workflow_step.route
            title = workflow_step.title.strip()
            if route is not None and route.http_method.strip() and route.endpoint_path.strip():
                summary = f"{route.http_method.strip().upper()} {route.endpoint_path.strip()}"
            else:
                summary = title or f"API step {index}"
            outline.append(f"Step {index}: execute {summary}.")
        elif step_kind == "db":
            title = workflow_step.title.strip() or f"DB step {index}"
            outline.append(f"Step {index}: run DB verification {title}.")
        else:
            title = workflow_step.title.strip() or f"workflow step {index}"
            outline.append(f"Step {index}: {title}.")
        if workflow_step.capture:
            outline.append(
                "Capture the values needed for later workflow steps: "
                + ", ".join(workflow_step.capture)
                + "."
            )
    if test_case.expected_results:
        outline.append(_verification_step(test_case))
    return _dedupe_preserve_order(outline)


def _needs_preparation_step(test_case: PlannedTestCase, steps: list[str]) -> bool:
    if _has_preparation_step(steps):
        return False
    return bool(
        test_case.planned_route is not None
        or test_case.request_headers
        or test_case.request_params
        or test_case.request_body is not None
        or test_case.requires_request_body
        or test_case.auth_strategy
        or test_case.requires_auth_strategy
    )


def _preparation_step(test_case: PlannedTestCase) -> str:
    request_target = "API request"
    if test_case.planned_route is not None:
        method = test_case.planned_route.http_method.strip().upper()
        path = test_case.planned_route.endpoint_path.strip()
        if method and path:
            request_target = f"{method} {path}"
    details: list[str] = []
    if test_case.auth_strategy or test_case.requires_auth_strategy:
        details.append("auth context")
    if test_case.request_body is not None or test_case.requires_request_body:
        details.append("request body")
    if test_case.request_params:
        details.append("request parameters")
    if test_case.request_headers:
        details.append("request headers")
    if details:
        return f"Prepare {request_target} with " + ", ".join(details) + "."
    return f"Prepare {request_target}."


def _default_execution_step(test_case: PlannedTestCase) -> str:
    if test_case.planned_route is not None:
        method = test_case.planned_route.http_method.strip().upper()
        path = test_case.planned_route.endpoint_path.strip()
        if method and path:
            return f"Execute {method} {path}."
    objective = test_case.objective.strip() or test_case.title.strip() or "the planned case"
    return f"Execute the flow for {objective}."


def _needs_verification_step(test_case: PlannedTestCase, steps: list[str]) -> bool:
    if _has_verification_step(steps):
        return False
    return bool(test_case.expected_results or test_case.observable_outcomes)


def _verification_step(test_case: PlannedTestCase) -> str:
    if test_case.observable_outcomes:
        return "Verify the observable outcomes and response contract."
    return "Verify the expected outcomes and response contract."


def _db_verification_step(test_case: PlannedTestCase) -> str:
    if test_case.db_verification is not None:
        name = test_case.db_verification.name.strip()
        if name:
            return f"Run DB verification: {name}."
    return "Run the required DB verification."


def _has_preparation_step(steps: list[str]) -> bool:
    return any(any(token in step.lower() for token in ("prepare", "build request", "resolve auth")) for step in steps)


def _has_verification_step(steps: list[str]) -> bool:
    return any(any(token in step.lower() for token in ("verify", "assert", "check", "expect", "validate")) for step in steps)


def _has_capture_step(steps: list[str]) -> bool:
    return any(any(token in step.lower() for token in ("capture", "extract", "store response")) for step in steps)


def _has_db_step(steps: list[str]) -> bool:
    return any(any(token in step.lower() for token in ("db", "database", "sql", "persist")) for step in steps)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _agent_plan_default_metadata(agent_plan: AgentTestPlanInput) -> dict[str, str]:
    defaults = agent_plan.metadata.get("defaults")
    if not isinstance(defaults, dict):
        return {}
    metadata: dict[str, str] = {}
    for source_key, target_key in (
        ("default_environment", "default_environment"),
        ("environment", "default_environment"),
        ("default_actor", "default_actor"),
        ("actor", "default_actor"),
        ("default_auth", "default_auth"),
        ("auth", "default_auth"),
    ):
        value = defaults.get(source_key)
        if isinstance(value, str) and value.strip() and target_key not in metadata:
            metadata[target_key] = value.strip()
    return metadata

