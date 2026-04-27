"""Deterministic compiler from compact authoring-plan into AgentTestPlanInput."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tools.generation.authoring import validate_agent_plan_input
from tools.generation.domain.models import (
    AgentPlannedTestCaseInput,
    AgentTestPlanInput,
    GenerationDiagnostic,
    PlannedDbVerification,
    PlannedRouteIntent,
    PlannedWorkflowStep,
)

from .diagnostics import authoring_diagnostic, build_authoring_message, derive_authoring_status
from .loaders import AuthoringPlanLoader
from .models import (
    AuthoringCase,
    AuthoringEntityOperation,
    AuthoringPlan,
    AuthoringPlanCompileResult,
    AuthoringPlanLoadResult,
    AuthoringSetupStep,
)

_PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")
_VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MUTATING_STATE_CHANGES = {"create", "update", "delete", "mutate"}
_READ_ONLY_STATE_CHANGES = {"none", "read_only", "readonly"}
_SUPPORTED_STATE_CHANGES = _MUTATING_STATE_CHANGES | _READ_ONLY_STATE_CHANGES
_SUPPORTED_CASE_KINDS = {"api", "workflow", "db-check"}


class AuthoringPlanCompiler:
    """Compile compact authoring DSL into the current internal IR."""

    def __init__(self, loader: AuthoringPlanLoader | None = None) -> None:
        self.loader = loader or AuthoringPlanLoader()

    def load(self, file_path: Path) -> AuthoringPlanLoadResult:
        return self.loader.load(file_path)

    def validate(self, authoring_plan: AuthoringPlan, *, file_path: Path | None = None) -> AuthoringPlanCompileResult:
        return self._compile(authoring_plan, file_path=file_path, validation_only=True)

    def validate_file(self, file_path: Path) -> AuthoringPlanCompileResult:
        load_result = self.load(file_path)
        if load_result.authoring_plan is None:
            status = derive_authoring_status(load_result.diagnostics)
            return AuthoringPlanCompileResult(
                status=status,
                message=build_authoring_message(status, load_result.diagnostics, compiled=False),
                file_path=file_path,
                diagnostics=load_result.diagnostics,
            )
        result = self.validate(load_result.authoring_plan, file_path=file_path)
        result.diagnostics = [*load_result.diagnostics, *result.diagnostics]
        result.message = build_authoring_message(result.status, result.diagnostics, compiled=False)
        return result

    def compile(self, authoring_plan: AuthoringPlan, *, file_path: Path | None = None) -> AuthoringPlanCompileResult:
        return self._compile(authoring_plan, file_path=file_path, validation_only=False)

    def compile_file(self, file_path: Path) -> AuthoringPlanCompileResult:
        load_result = self.load(file_path)
        if load_result.authoring_plan is None:
            status = derive_authoring_status(load_result.diagnostics)
            return AuthoringPlanCompileResult(
                status=status,
                message=build_authoring_message(status, load_result.diagnostics, compiled=True),
                file_path=file_path,
                diagnostics=load_result.diagnostics,
            )
        result = self.compile(load_result.authoring_plan, file_path=file_path)
        result.diagnostics = [*load_result.diagnostics, *result.diagnostics]
        result.message = build_authoring_message(result.status, result.diagnostics, compiled=True)
        return result

    def _compile(
        self,
        authoring_plan: AuthoringPlan,
        *,
        file_path: Path | None,
        validation_only: bool,
    ) -> AuthoringPlanCompileResult:
        source_ref = str(file_path) if file_path is not None else authoring_plan.source_id
        diagnostics = self._validate_top_level(authoring_plan, source_ref)
        compiled_cases: list[AgentPlannedTestCaseInput] = []
        for index, case in enumerate(authoring_plan.cases, start=1):
            compiled_case, case_diagnostics = self._compile_case(authoring_plan, case, index=index)
            diagnostics.extend(case_diagnostics)
            if compiled_case is not None:
                compiled_cases.append(compiled_case)
        status = derive_authoring_status(diagnostics)
        compiled_plan: AgentTestPlanInput | None = None
        if status == derive_authoring_status([]):
            compiled_plan = AgentTestPlanInput(
                source_id=authoring_plan.source_id,
                project=authoring_plan.project,
                title=authoring_plan.title,
                goal=authoring_plan.goal,
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
            diagnostics.extend(validate_agent_plan_input(compiled_plan, source_ref))
            status = derive_authoring_status(diagnostics)
        message = build_authoring_message(status, diagnostics, compiled=not validation_only)
        return AuthoringPlanCompileResult(
            status=status,
            message=message,
            file_path=file_path,
            authoring_plan=authoring_plan,
            compiled_plan=compiled_plan,
            diagnostics=diagnostics,
            case_count=len(authoring_plan.cases),
        )

    def _validate_top_level(
        self,
        authoring_plan: AuthoringPlan,
        source_ref: str,
    ) -> list[GenerationDiagnostic]:
        diagnostics: list[GenerationDiagnostic] = []
        if authoring_plan.version != 1:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_unsupported_version",
                    "Only authoring contract version=1 is supported.",
                    source_ref=source_ref,
                    details={"version": authoring_plan.version},
                )
            )
        if not authoring_plan.source_id.strip():
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_missing_source_id",
                    "Authoring plan must include source_id.",
                    source_ref=source_ref,
                )
            )
        if not authoring_plan.project.strip():
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_missing_project",
                    "Authoring plan must include project.",
                    source_ref=source_ref,
                )
            )
        if not authoring_plan.title.strip():
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_missing_title",
                    "Authoring plan must include title.",
                    source_ref=source_ref,
                )
            )
        if not authoring_plan.goal.strip():
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_missing_goal",
                    "Authoring plan must include goal.",
                    source_ref=source_ref,
                )
            )
        if not authoring_plan.scope.surface.strip():
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_missing_scope",
                    "Authoring plan must include scope.surface.",
                    source_ref=source_ref,
                )
            )
        if not authoring_plan.cases:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_missing_cases",
                    "Authoring plan must include at least one case.",
                    source_ref=source_ref,
                )
            )
        for entity_name, entity_spec in authoring_plan.entities.items():
            normalized_id_field = entity_spec.id_field.strip()
            if normalized_id_field and not _VARIABLE_NAME_PATTERN.fullmatch(normalized_id_field):
                diagnostics.append(
                    authoring_diagnostic(
                        "authoring_invalid_entity_id_field",
                        "Entity id_field must be a machine-readable variable name such as user_id.",
                        source_ref=entity_name,
                        details={"entity": entity_name, "id_field": entity_spec.id_field},
                    )
                )
        seen_case_ids: dict[str, int] = {}
        for index, case in enumerate(authoring_plan.cases, start=1):
            normalized_case_id = case.id.strip()
            if not normalized_case_id:
                continue
            first_index = seen_case_ids.get(normalized_case_id)
            if first_index is not None:
                diagnostics.append(
                    authoring_diagnostic(
                        "authoring_duplicate_case_id",
                        "Authoring plan case ids must be unique.",
                        source_ref=normalized_case_id,
                        details={
                            "case_id": normalized_case_id,
                            "first_case_index": first_index,
                            "duplicate_case_index": index,
                        },
                    )
                )
                continue
            seen_case_ids[normalized_case_id] = index
        return diagnostics

    def _compile_case(
        self,
        authoring_plan: AuthoringPlan,
        case: AuthoringCase,
        *,
        index: int,
    ) -> tuple[AgentPlannedTestCaseInput | None, list[GenerationDiagnostic]]:
        diagnostics: list[GenerationDiagnostic] = []
        case_ref = case.id.strip() or f"{authoring_plan.source_id}#case-{index:03d}"
        kind = case.kind.strip().lower()
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
        elif kind not in _SUPPORTED_CASE_KINDS:
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
        if not case.state_change.strip():
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_case_missing_state_change",
                    "Authoring case must include state_change.",
                    source_ref=case_ref,
                    details={"case_index": index},
                )
            )
        elif case.state_change.strip().lower() not in _SUPPORTED_STATE_CHANGES:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_unknown_state_change",
                    "Authoring case state_change must be one of create, update, delete, mutate, none, read_only, or readonly.",
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

        setup_steps, setup_diagnostics, setup_captures = self._expand_setup_steps(authoring_plan, case, case_ref)
        diagnostics.extend(setup_diagnostics)

        persisted_verification, persistence_diagnostics, persistence_placeholders = self._build_db_verification(
            authoring_plan,
            case,
            case_ref,
        )
        diagnostics.extend(persistence_diagnostics)

        if case.execute is not None and case.execute.route is not None:
            unresolved_placeholders = sorted(
                placeholder
                for placeholder in _extract_placeholders(case.execute.route.path)
                if placeholder not in setup_captures
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
        available_after_execute = set(setup_captures)
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

        if diagnostics:
            status = derive_authoring_status(diagnostics)
            if status != derive_authoring_status([]):
                return None, diagnostics

        title = case.title.strip() or case.objective.strip()
        route_intent = _build_route_intent(case.execute)
        expected_outcomes = [] if case.oracle is None else _api_expected_outcomes(case.oracle)
        auth_strategy = self._resolve_auth_strategy(
            explicit_auth_strategy=[] if case.execute is None else case.execute.auth_strategy,
            authoring_plan=authoring_plan,
        )
        metadata = {
            **dict(case.metadata),
            "authoring_case_id": case.id,
            "authoring_kind": case.kind,
            "state_change": case.state_change,
            **_authoring_defaults_metadata(authoring_plan),
        }

        if kind == "workflow":
            workflow_steps = [*setup_steps]
            if case.execute is not None and route_intent is not None:
                workflow_steps.append(
                    PlannedWorkflowStep(
                        step_type="api",
                        title=title,
                        route=route_intent,
                        request_headers=dict(case.execute.headers),
                        request_params=dict(case.execute.params),
                        request_body=case.execute.body,
                        requires_request_body=case.execute.body is not None,
                        auth_strategy=auth_strategy,
                        capture=case_captures,
                        expected_outcomes=expected_outcomes,
                    )
                )
            return (
                AgentPlannedTestCaseInput(
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
                    db_verification=persisted_verification,
                    metadata=metadata,
                ),
                diagnostics,
            )

        if kind == "db-check":
            db_expected_outcomes = []
            if persisted_verification is not None:
                db_expected_outcomes = list(persisted_verification.expected_outcomes)
            return (
                AgentPlannedTestCaseInput(
                    title=title,
                    objective=case.objective,
                    kind="db",
                    case_id=case.id,
                    expected_outcomes=db_expected_outcomes,
                    requires_db_verification=persisted_verification is not None,
                    priority=case.priority,
                    tags=list(case.tags),
                    db_verification=persisted_verification,
                    metadata=metadata,
                ),
                diagnostics,
            )

        return (
            AgentPlannedTestCaseInput(
                title=title,
                objective=case.objective,
                kind="api",
                case_id=case.id,
                actions=[] if route_intent is None else [f"{route_intent.http_method} {route_intent.endpoint_path}"],
                auth_strategy=auth_strategy,
                request_headers={} if case.execute is None else dict(case.execute.headers),
                request_params={} if case.execute is None else dict(case.execute.params),
                request_body=None if case.execute is None else case.execute.body,
                requires_request_body=bool(case.execute is not None and case.execute.body is not None),
                expected_outcomes=expected_outcomes,
                capture=case_captures,
                requires_db_verification=persisted_verification is not None,
                priority=case.priority,
                tags=list(case.tags),
                route=route_intent,
                db_verification=persisted_verification,
                metadata=metadata,
            ),
            diagnostics,
        )

    def _expand_setup_steps(
        self,
        authoring_plan: AuthoringPlan,
        case: AuthoringCase,
        case_ref: str,
    ) -> tuple[list[PlannedWorkflowStep], list[GenerationDiagnostic], set[str]]:
        workflow_steps: list[PlannedWorkflowStep] = []
        diagnostics: list[GenerationDiagnostic] = []
        available_captures: set[str] = set()
        for step_index, setup_step in enumerate(case.setup, start=1):
            operation, lookup_diagnostics = self._resolve_entity_operation(
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
            if entity_id_field and _operation_uses_placeholder(operation, entity_id_field) and entity_id_field not in available_captures:
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
                        request_headers=dict(operation.request_headers),
                        request_params=dict(operation.request_params),
                        request_body=operation.request_body,
                        requires_request_body=operation.request_body is not None,
                        auth_strategy=self._resolve_auth_strategy(
                            explicit_auth_strategy=operation.auth_strategy,
                            authoring_plan=authoring_plan,
                        ),
                        capture=list(operation.captures or ([] if operation.oracle is None else operation.oracle.captures)),
                        metadata=_authoring_defaults_metadata(authoring_plan),
                    )
                )
                available_captures.update(
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
                available_captures.update(_capture_targets(operation.captures))
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
        return workflow_steps, diagnostics, available_captures

    def _build_db_verification(
        self,
        authoring_plan: AuthoringPlan,
        case: AuthoringCase,
        case_ref: str,
    ) -> tuple[PlannedDbVerification | None, list[GenerationDiagnostic], set[str]]:
        diagnostics: list[GenerationDiagnostic] = []
        if case.oracle is None or case.oracle.persisted_state is None:
            return None, diagnostics, set()
        state_ref = case.oracle.persisted_state
        entity_name = state_ref.entity.strip()
        operation_name = state_ref.operation.strip()
        entity_spec = authoring_plan.entities.get(entity_name)
        if entity_spec is None:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_unknown_entity",
                    "Persisted-state reference uses an unknown entity.",
                    source_ref=case_ref,
                    details={"entity": entity_name},
                )
            )
            return None, diagnostics, set()
        operation = entity_spec.operations.get(operation_name)
        if operation is None:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_unknown_entity_operation",
                    "Persisted-state reference uses an unknown entity operation.",
                    source_ref=case_ref,
                    details={"entity": entity_name, "operation": operation_name},
                )
            )
            return None, diagnostics, set()
        if not operation.sql.strip():
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_persisted_state_template_missing",
                    "Persisted-state reference must resolve to a DB verification template with sql.",
                    source_ref=case_ref,
                    details={"entity": entity_name, "operation": operation_name},
                )
            )
            return None, diagnostics, set()
        expected_outcomes = list(operation.expected_outcomes)
        if not expected_outcomes and operation.oracle is not None:
            expected_outcomes = list(operation.oracle.business_checks)
        if not expected_outcomes:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_persisted_state_template_missing",
                    "Persisted-state verification template must define expected_outcomes.",
                    source_ref=case_ref,
                    details={"entity": entity_name, "operation": operation_name},
                )
            )
            return None, diagnostics, set()
        placeholders = set(_extract_placeholders(operation.sql))
        placeholders.update(_extract_placeholders_from_value(operation.params))
        entity_id_field = entity_spec.id_field.strip()
        if entity_id_field and entity_id_field not in placeholders:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_persisted_state_id_field_missing",
                    "Persisted-state template must reference the entity id_field so verification is scoped to the authored entity instance.",
                    source_ref=case_ref,
                    details={
                        "entity": entity_name,
                        "operation": operation_name,
                        "id_field": entity_id_field,
                    },
                )
            )
            return None, diagnostics, set()
        return (
            PlannedDbVerification(
                name=f"Verify {entity_name}.{operation_name}",
                sql=operation.sql,
                params=dict(operation.params),
                expected_outcomes=expected_outcomes,
                capture=list(operation.captures),
            ),
            diagnostics,
            placeholders,
        )

    def _resolve_entity_operation(
        self,
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

    @staticmethod
    def _resolve_auth_strategy(
        *,
        explicit_auth_strategy: list[str],
        authoring_plan: AuthoringPlan,
    ) -> list[str]:
        if explicit_auth_strategy:
            return list(explicit_auth_strategy)
        if authoring_plan.defaults.auth.strip():
            return [authoring_plan.defaults.auth.strip()]
        return []


def _build_route_intent(execute: Any) -> PlannedRouteIntent | None:
    if execute is None or execute.route is None:
        return None
    return PlannedRouteIntent(
        http_method=execute.route.method.upper(),
        endpoint_path=execute.route.path,
    )


def _api_expected_outcomes(oracle: Any) -> list[str]:
    if oracle is None:
        return []
    outcomes: list[str] = []
    if oracle.status_code is not None:
        outcomes.append(f"HTTP {oracle.status_code}")
    outcomes.extend(str(item) for item in oracle.business_checks)
    return outcomes


def _capture_targets(capture_rules: list[str]) -> set[str]:
    targets: set[str] = set()
    for rule in capture_rules:
        if "->" not in rule:
            continue
        _, variable_name = rule.split("->", 1)
        normalized = variable_name.strip()
        if normalized:
            targets.add(normalized)
    return targets


def _extract_placeholders(value: Any) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, str):
        return set()
    return {match.group(1).strip() for match in _PLACEHOLDER_PATTERN.finditer(value)}


def _extract_placeholders_from_value(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return _extract_placeholders(value)
    if isinstance(value, dict):
        placeholders: set[str] = set()
        for nested_value in value.values():
            placeholders.update(_extract_placeholders_from_value(nested_value))
        return placeholders
    if isinstance(value, (list, tuple, set)):
        placeholders: set[str] = set()
        for nested_value in value:
            placeholders.update(_extract_placeholders_from_value(nested_value))
        return placeholders
    return set()


def _operation_uses_placeholder(operation: AuthoringEntityOperation, variable_name: str) -> bool:
    placeholders: set[str] = set()
    if operation.route is not None:
        placeholders.update(_extract_placeholders(operation.route.path))
    placeholders.update(_extract_placeholders_from_value(operation.request_headers))
    placeholders.update(_extract_placeholders_from_value(operation.request_params))
    placeholders.update(_extract_placeholders_from_value(operation.request_body))
    placeholders.update(_extract_placeholders(operation.sql))
    placeholders.update(_extract_placeholders_from_value(operation.params))
    return variable_name in placeholders


def _requires_persistence(state_change: str) -> bool:
    normalized = state_change.strip().lower()
    if not normalized:
        return False
    if normalized in _READ_ONLY_STATE_CHANGES:
        return False
    return normalized in _MUTATING_STATE_CHANGES


def _authoring_defaults_metadata(authoring_plan: AuthoringPlan) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if authoring_plan.defaults.environment.strip():
        metadata["default_environment"] = authoring_plan.defaults.environment.strip()
    if authoring_plan.defaults.actor.strip():
        metadata["default_actor"] = authoring_plan.defaults.actor.strip()
    if authoring_plan.defaults.auth.strip():
        metadata["default_auth"] = authoring_plan.defaults.auth.strip()
    return metadata
