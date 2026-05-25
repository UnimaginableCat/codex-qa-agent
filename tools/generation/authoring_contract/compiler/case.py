"""Single-case compilation for compact authoring plans."""

from __future__ import annotations

from tools.generation.domain.models import AgentPlannedTestCaseInput, GenerationDiagnostic, PlannedWorkflowStep

from ..case_diagnostics.boundary import _boundary_case_diagnostics
from ..case_diagnostics.db_expectations import _db_string_placeholder_quoting_diagnostics
from ..case_diagnostics.email import _normalized_email_expectation_diagnostics
from ..case_diagnostics.lifecycle import (
    _workflow_same_state_contract_warning,
    _workflow_setup_state_mismatch_diagnostics,
)
from ..case_diagnostics.permission import _permission_state_contract_diagnostics
from ..case_diagnostics.readiness import _readiness_metadata_diagnostics
from ..case_diagnostics.request_constraints import _request_constraint_diagnostics
from ..case_diagnostics.response_fields import _response_field_contract_diagnostics
from ..case_diagnostics.variables import _env_backed_id_equality_diagnostics
from ..case_diagnostics.visibility import _visibility_claim_diagnostics
from ..diagnostics import authoring_diagnostic, derive_authoring_status
from ..helpers import (
    _api_expected_outcomes,
    _authoring_defaults_metadata,
    _build_route_intent,
    _capture_targets,
    _declared_variable_names,
    _extract_placeholders,
    _merge_default_headers,
    _requires_persistence,
)
from ..models import (
    AUTHORING_STATE_CHANGE_ALLOWED_TEXT,
    AuthoringCase,
    AuthoringPlan,
    AuthoringStateChange,
    normalize_state_change_value,
)
from .auth import resolve_auth_strategy
from .persistence import build_db_verification
from .setup import expand_setup_steps

SUPPORTED_CASE_KINDS = {"api", "workflow", "db-check"}


def compile_case(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    *,
    index: int,
) -> tuple[AgentPlannedTestCaseInput | None, list[GenerationDiagnostic]]:
    diagnostics: list[GenerationDiagnostic] = []
    case_ref = case.id.strip() or f"{authoring_plan.source_id}#case-{index:03d}"
    kind = case.kind.strip().lower()
    diagnostics.extend(_case_shape_diagnostics(case, case_ref, index=index, kind=kind))
    diagnostics.extend(_boundary_case_diagnostics(authoring_plan, case, case_ref, index=index))
    diagnostics.extend(_readiness_metadata_diagnostics(case, case_ref, index=index))
    diagnostics.extend(_visibility_claim_diagnostics(authoring_plan, case, case_ref, index=index))
    diagnostics.extend(_permission_state_contract_diagnostics(authoring_plan, case, case_ref, index=index))
    diagnostics.extend(_env_backed_id_equality_diagnostics(authoring_plan, case, case_ref, index=index))

    if _requires_persistence(case.state_change) and (
        case.oracle is None or case.oracle.persisted_state is None
    ):
        diagnostics.append(
            authoring_diagnostic(
                "authoring_state_change_without_persistence_check",
                "Mutating authoring case must define oracle.persisted_state.",
                source_ref=case_ref,
                details={"case_index": index, "state_change": case.state_change},
            )
        )

    declared_variable_names = _declared_variable_names(authoring_plan, case)
    setup_steps, setup_diagnostics, setup_captures = expand_setup_steps(
        authoring_plan,
        case.setup,
        case_ref,
        available_variables=declared_variable_names,
    )
    diagnostics.extend(setup_diagnostics)

    persisted_verification, persistence_diagnostics, persistence_placeholders = build_db_verification(
        authoring_plan,
        case,
        case_ref,
    )
    diagnostics.extend(persistence_diagnostics)
    diagnostics.extend(
        _normalized_email_expectation_diagnostics(
            authoring_plan=authoring_plan,
            case=case,
            case_ref=case_ref,
            setup_steps=setup_steps,
            persisted_verification=persisted_verification,
        )
    )
    diagnostics.extend(
        _request_constraint_diagnostics(
            authoring_plan=authoring_plan,
            case=case,
            case_ref=case_ref,
            setup_steps=setup_steps,
        )
    )
    diagnostics.extend(_response_field_contract_diagnostics(authoring_plan, case, case_ref))
    diagnostics.extend(
        _db_string_placeholder_quoting_diagnostics(
            authoring_plan=authoring_plan,
            case=case,
            case_ref=case_ref,
            persisted_verification=persisted_verification,
        )
    )
    diagnostics.extend(_workflow_setup_state_mismatch_diagnostics(case=case, case_ref=case_ref))
    diagnostics.extend(_workflow_same_state_contract_warning(case=case, case_ref=case_ref))

    diagnostics.extend(
        _unresolved_capture_diagnostics(
            authoring_plan=authoring_plan,
            case=case,
            case_ref=case_ref,
            index=index,
            declared_variable_names=declared_variable_names,
            setup_captures=setup_captures,
            persistence_placeholders=persistence_placeholders,
        )
    )

    if diagnostics:
        status = derive_authoring_status(diagnostics)
        if status != derive_authoring_status([]):
            return None, diagnostics

    return (
        _build_case_input(
            authoring_plan=authoring_plan,
            case=case,
            kind=kind,
            setup_steps=setup_steps,
            persisted_verification=persisted_verification,
        ),
        diagnostics,
    )


def _case_shape_diagnostics(
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
    kind: str,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not case.id.strip():
        diagnostics.append(
            authoring_diagnostic(
                "authoring_case_missing_id",
                "Authoring case must include id.",
                source_ref=case_ref,
                details={"case_index": index},
            )
        )
    if not kind:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_case_missing_kind",
                "Authoring case must include kind.",
                source_ref=case_ref,
                details={"case_index": index},
            )
        )
    elif kind not in SUPPORTED_CASE_KINDS:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_unknown_case_kind",
                "Authoring case kind must be one of api, workflow, or db-check.",
                source_ref=case_ref,
                details={"case_index": index, "kind": case.kind},
            )
        )
    if not case.objective.strip():
        diagnostics.append(
            authoring_diagnostic(
                "authoring_case_missing_objective",
                "Authoring case must include objective.",
                source_ref=case_ref,
                details={"case_index": index},
            )
        )
    normalized_state_change = normalize_state_change_value(case.state_change)
    if not normalized_state_change:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_case_missing_state_change",
                "Authoring case must include state_change.",
                source_ref=case_ref,
                details={"case_index": index},
            )
        )
    elif AuthoringStateChange.from_raw(case.state_change) is None:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_unknown_state_change",
                f"Authoring case state_change must be one of {AUTHORING_STATE_CHANGE_ALLOWED_TEXT}.",
                source_ref=case_ref,
                details={"case_index": index, "state_change": case.state_change},
            )
        )
    if case.oracle is None:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_case_missing_oracle",
                "Authoring case must include oracle.",
                source_ref=case_ref,
                details={"case_index": index},
            )
        )
    if kind == "api" and case.setup:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_case_kind_incompatible_with_setup",
                "API authoring case cannot use setup; use kind=workflow for setup-driven execution.",
                source_ref=case_ref,
                details={"case_index": index, "kind": kind},
            )
        )
    if kind in {"api", "workflow"}:
        route = None if case.execute is None else case.execute.route
        if route is None or not route.method.strip() or not route.path.strip():
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_missing_route_hint",
                    "Authoring case must include execute.route.method and execute.route.path.",
                    source_ref=case_ref,
                    details={"case_index": index, "kind": kind},
                )
            )
    return diagnostics


def _unresolved_capture_diagnostics(
    *,
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    index: int,
    declared_variable_names: set[str],
    setup_captures: set[str],
    persistence_placeholders: set[str],
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if case.execute is not None and case.execute.route is not None:
        unresolved_placeholders = sorted(
            placeholder
            for placeholder in _extract_placeholders(case.execute.route.path)
            if placeholder not in declared_variable_names and placeholder not in setup_captures
        )
        if unresolved_placeholders:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_capture_required_but_missing",
                    "Route placeholders depend on setup captures that were not resolved.",
                    source_ref=case_ref,
                    details={"case_index": index, "placeholders": unresolved_placeholders},
                )
            )

    case_captures = [] if case.oracle is None else list(case.oracle.captures)
    available_after_execute = set(declared_variable_names)
    available_after_execute.update(setup_captures)
    available_after_execute.update(_capture_targets(case_captures))
    unresolved_persistence_placeholders = sorted(
        placeholder
        for placeholder in persistence_placeholders
        if placeholder not in available_after_execute
    )
    if unresolved_persistence_placeholders:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_capture_required_but_missing",
                "Persisted-state verification depends on captures that are not produced by setup or execute.",
                source_ref=case_ref,
                details={"case_index": index, "placeholders": unresolved_persistence_placeholders},
            )
        )
    return diagnostics


def _build_case_input(
    *,
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    kind: str,
    setup_steps: list[PlannedWorkflowStep],
    persisted_verification: object,
) -> AgentPlannedTestCaseInput:
    title = case.title.strip() or case.objective.strip()
    route_intent = _build_route_intent(case.execute)
    expected_outcomes = [] if case.oracle is None else _api_expected_outcomes(case.oracle)
    auth_strategy = resolve_auth_strategy(
        explicit_auth_strategy=[] if case.execute is None else case.execute.auth_strategy,
        authoring_plan=authoring_plan,
    )
    case_captures = [] if case.oracle is None else list(case.oracle.captures)
    metadata = {
        **_authoring_defaults_metadata(authoring_plan),
        **dict(case.metadata),
        "authoring_case_id": case.id,
        "authoring_kind": case.kind,
        "state_change": case.state_change,
    }
    if kind == "api" and case.execute is not None and case.execute.actor.strip():
        metadata["default_actor"] = case.execute.actor.strip()

    if kind == "workflow":
        workflow_steps = [*setup_steps]
        if case.execute is not None and route_intent is not None:
            workflow_steps.append(
                PlannedWorkflowStep(
                    step_type="api",
                    title=title,
                    actor=_execute_actor(authoring_plan, case),
                    route=route_intent,
                    request_headers=_merge_default_headers(authoring_plan, case.execute.headers),
                    request_params=dict(case.execute.params),
                    request_body=case.execute.body,
                    requires_request_body=case.execute.body is not None,
                    auth_strategy=auth_strategy,
                    capture=case_captures,
                    expected_outcomes=expected_outcomes,
                )
            )
        return AgentPlannedTestCaseInput(
            title=title,
            objective=case.objective,
            kind="workflow",
            case_id=case.id,
            actions=[step.title for step in workflow_steps if step.title],
            auth_strategy=auth_strategy,
            capture=case_captures,
            workflow_steps=workflow_steps,
            requires_db_verification=persisted_verification is not None,
            priority=case.priority,
            tags=list(case.tags),
            scenario_variables=list(case.scenario_variables),
            db_verification=persisted_verification,
            metadata=metadata,
        )

    if kind == "db-check":
        db_expected_outcomes = []
        if persisted_verification is not None:
            db_expected_outcomes = list(persisted_verification.expected_outcomes)
        return AgentPlannedTestCaseInput(
            title=title,
            objective=case.objective,
            kind="db",
            case_id=case.id,
            expected_outcomes=db_expected_outcomes,
            requires_db_verification=persisted_verification is not None,
            priority=case.priority,
            tags=list(case.tags),
            scenario_variables=list(case.scenario_variables),
            db_verification=persisted_verification,
            metadata=metadata,
        )

    return AgentPlannedTestCaseInput(
        title=title,
        objective=case.objective,
        kind="api",
        case_id=case.id,
        actions=[] if route_intent is None else [f"{route_intent.http_method} {route_intent.endpoint_path}"],
        auth_strategy=auth_strategy,
        request_headers={} if case.execute is None else _merge_default_headers(authoring_plan, case.execute.headers),
        request_params={} if case.execute is None else dict(case.execute.params),
        request_body=None if case.execute is None else case.execute.body,
        requires_request_body=bool(case.execute is not None and case.execute.body is not None),
        expected_outcomes=expected_outcomes,
        capture=case_captures,
        requires_db_verification=persisted_verification is not None,
        priority=case.priority,
        tags=list(case.tags),
        scenario_variables=list(case.scenario_variables),
        route=route_intent,
        db_verification=persisted_verification,
        metadata=metadata,
    )


def _execute_actor(authoring_plan: AuthoringPlan, case: AuthoringCase) -> str:
    if case.execute is not None and case.execute.actor.strip():
        return case.execute.actor.strip()
    default_actor = case.metadata.get("default_actor")
    if isinstance(default_actor, str) and default_actor.strip():
        return default_actor.strip()
    return authoring_plan.defaults.actor.strip()
