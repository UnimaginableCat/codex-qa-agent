"""Workflow setup compilation for authoring cases."""

from __future__ import annotations

from tools.generation.domain.models import GenerationDiagnostic, PlannedRouteIntent, PlannedWorkflowStep

from ..diagnostics import authoring_diagnostic
from ..helpers import (
    _authoring_defaults_metadata,
    _capture_targets,
    _merge_default_headers,
    _operation_uses_placeholder,
)
from ..models import AuthoringEntityOperation, AuthoringPlan, AuthoringSetupStep
from .auth import resolve_auth_strategy


def expand_setup_steps(
    authoring_plan: AuthoringPlan,
    setup_steps: list[AuthoringSetupStep],
    case_ref: str,
    *,
    available_variables: set[str] | None = None,
) -> tuple[list[PlannedWorkflowStep], list[GenerationDiagnostic], set[str]]:
    workflow_steps: list[PlannedWorkflowStep] = []
    diagnostics: list[GenerationDiagnostic] = []
    available_names = set(available_variables or set())
    for step_index, setup_step in enumerate(setup_steps, start=1):
        if setup_step.actor.strip():
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_setup_step_actor_unsupported",
                    (
                        "Setup step actor overrides are not supported by the current runner contract. "
                        "Make the scenario single-actor, split the workflow, or keep it deferred until "
                        "multi-actor workflow execution is implemented end-to-end."
                    ),
                    source_ref=case_ref,
                    details={
                        "entity": setup_step.use_entity,
                        "operation": setup_step.operation,
                        "step_index": step_index,
                        "actor": setup_step.actor,
                    },
                )
            )
        operation, lookup_diagnostics = resolve_entity_operation(
            authoring_plan,
            setup_step,
            case_ref,
            step_index=step_index,
        )
        diagnostics.extend(lookup_diagnostics)
        if operation is None:
            continue
        entity_spec = authoring_plan.entities.get(setup_step.use_entity.strip())
        entity_id_field = "" if entity_spec is None else entity_spec.id_field.strip()
        if entity_id_field and _operation_uses_placeholder(operation, entity_id_field) and entity_id_field not in available_names:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_setup_entity_id_field_unresolved",
                    "Setup operation depends on the entity id_field, but no earlier setup step captured it.",
                    source_ref=case_ref,
                    details={
                        "entity": setup_step.use_entity,
                        "operation": setup_step.operation,
                        "step_index": step_index,
                        "id_field": entity_id_field,
                    },
                )
            )
        if operation.route is not None:
            workflow_steps.append(
                PlannedWorkflowStep(
                    step_type="api",
                    title=f"Setup {setup_step.use_entity}.{setup_step.operation}",
                    route=PlannedRouteIntent(
                        http_method=operation.route.method.upper(),
                        endpoint_path=operation.route.path,
                    ),
                    request_headers=_merge_default_headers(authoring_plan, operation.request_headers),
                    request_params=dict(operation.request_params),
                    request_body=operation.request_body,
                    requires_request_body=operation.request_body is not None,
                    auth_strategy=resolve_auth_strategy(
                        explicit_auth_strategy=operation.auth_strategy,
                        authoring_plan=authoring_plan,
                    ),
                    capture=list(operation.captures or ([] if operation.oracle is None else operation.oracle.captures)),
                    metadata={
                        **_authoring_defaults_metadata(authoring_plan),
                        "request_constraints": [dict(item) for item in operation.request_constraints],
                    },
                )
            )
            available_names.update(
                _capture_targets(operation.captures or ([] if operation.oracle is None else operation.oracle.captures))
            )
            continue
        if operation.sql.strip():
            expected_outcomes = list(operation.expected_outcomes)
            if not expected_outcomes and operation.oracle is not None:
                expected_outcomes = list(operation.oracle.business_checks)
            workflow_steps.append(
                PlannedWorkflowStep(
                    step_type="db",
                    title=f"Setup {setup_step.use_entity}.{setup_step.operation}",
                    sql=operation.sql,
                    params=dict(operation.params),
                    expected_outcomes=expected_outcomes,
                    capture=list(operation.captures),
                    metadata=_authoring_defaults_metadata(authoring_plan),
                )
            )
            available_names.update(_capture_targets(operation.captures))
            continue
        diagnostics.append(
            authoring_diagnostic(
                "authoring_setup_reference_unresolved",
                "Setup reference did not resolve to an executable entity operation.",
                source_ref=case_ref,
                details={
                    "entity": setup_step.use_entity,
                    "operation": setup_step.operation,
                    "step_index": step_index,
                },
            )
        )
    return workflow_steps, diagnostics, available_names


def resolve_entity_operation(
    authoring_plan: AuthoringPlan,
    setup_step: AuthoringSetupStep,
    case_ref: str,
    *,
    step_index: int,
) -> tuple[AuthoringEntityOperation | None, list[GenerationDiagnostic]]:
    diagnostics: list[GenerationDiagnostic] = []
    entity_name = setup_step.use_entity.strip()
    operation_name = setup_step.operation.strip()
    entity_spec = authoring_plan.entities.get(entity_name)
    if entity_spec is None:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_unknown_entity",
                "Setup references an unknown entity.",
                source_ref=case_ref,
                details={"entity": entity_name, "step_index": step_index},
            )
        )
        diagnostics.append(
            authoring_diagnostic(
                "authoring_setup_reference_unresolved",
                "Setup reference could not be resolved.",
                source_ref=case_ref,
                details={"entity": entity_name, "operation": operation_name, "step_index": step_index},
            )
        )
        return None, diagnostics
    operation = entity_spec.operations.get(operation_name)
    if operation is None:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_unknown_entity_operation",
                "Setup references an unknown entity operation.",
                source_ref=case_ref,
                details={"entity": entity_name, "operation": operation_name, "step_index": step_index},
            )
        )
        diagnostics.append(
            authoring_diagnostic(
                "authoring_setup_reference_unresolved",
                "Setup reference could not be resolved.",
                source_ref=case_ref,
                details={"entity": entity_name, "operation": operation_name, "step_index": step_index},
            )
        )
        return None, diagnostics
    return operation, diagnostics
