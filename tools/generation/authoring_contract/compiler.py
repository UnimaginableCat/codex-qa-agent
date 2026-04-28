"""Deterministic compiler from compact authoring-plan into AgentTestPlanInput."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tools.generation.authoring import validate_agent_plan_input
from tools.generation.persistence.artifacts import (
    ENTITY_INVENTORY_FILENAME,
    OPERATION_INVENTORY_FILENAME,
    managed_generation_artifacts_root_for_path,
)
from tools.generation.domain.models import (
    AgentPlannedTestCaseInput,
    AgentTestPlanInput,
    DiagnosticSeverity,
    GenerationDiagnostic,
    PlannedDbVerification,
    PlannedRouteIntent,
    PlannedWorkflowStep,
)
from tools.scenario_runner.domain.models import ScenarioVariableDefinition, ScenarioVariableSource
from tools.scenario_runner.parsing.variables.validation import build_variable_definition

from .diagnostics import authoring_diagnostic, build_authoring_message, derive_authoring_status
from .loaders import AuthoringPlanLoader
from .models import (
    AuthoringCase,
    AuthoringEntityOperation,
    AuthoringPlan,
    AuthoringPlanCompileResult,
    AuthoringPlanLoadResult,
    AuthoringSetupStep,
    _maybe_int,
)

_PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")
_EXACT_PLACEHOLDER_PATTERN = re.compile(r"^\s*{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}\s*$")
_VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXPECTATION_COMPARISON_RE = re.compile(
    r"^\s*(?:response\s+)?(?P<left>.+?)\s*(?P<operator>=|!=)\s*(?P<right>.+?)\s*$",
    re.IGNORECASE,
)
_STRING_LENGTH_OVERFLOW_PATTERN = re.compile(
    r"\b(?:longer than|more than|over|above)\s+(\d+)\s+characters?\b",
    re.IGNORECASE,
)
_NUMERIC_GREATER_THAN_PATTERN = re.compile(
    r"\b(?P<field>[A-Za-z_][A-Za-z0-9_-]*)\s+(?:greater than|more than|over|above)\s+(?P<threshold>-?\d+)\b",
    re.IGNORECASE,
)
_NEGATIVE_FIELD_PATTERN = re.compile(
    r"\bnegative\s+(?P<field>[A-Za-z_][A-Za-z0-9_-]*)\b",
    re.IGNORECASE,
)
_ZERO_FIELD_PATTERN = re.compile(
    r"\bzero\s+(?P<field>[A-Za-z_][A-Za-z0-9_-]*)\b",
    re.IGNORECASE,
)
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
        inventory_diagnostics = _required_stage_inventory_diagnostics(file_path)
        load_result.diagnostics = [*load_result.diagnostics, *inventory_diagnostics]
        if load_result.authoring_plan is None:
            status = derive_authoring_status(load_result.diagnostics)
            return AuthoringPlanCompileResult(
                status=status,
                message=build_authoring_message(status, load_result.diagnostics, compiled=False),
                file_path=file_path,
                diagnostics=load_result.diagnostics,
            )
        load_result.diagnostics.extend(
            _stage_inventory_contract_diagnostics(file_path=file_path, authoring_plan=load_result.authoring_plan)
        )
        result = self.validate(load_result.authoring_plan, file_path=file_path)
        result.diagnostics = [*load_result.diagnostics, *result.diagnostics]
        result.status = derive_authoring_status(result.diagnostics)
        result.message = build_authoring_message(result.status, result.diagnostics, compiled=False)
        return result

    def compile(self, authoring_plan: AuthoringPlan, *, file_path: Path | None = None) -> AuthoringPlanCompileResult:
        return self._compile(authoring_plan, file_path=file_path, validation_only=False)

    def compile_file(self, file_path: Path) -> AuthoringPlanCompileResult:
        load_result = self.load(file_path)
        inventory_diagnostics = _required_stage_inventory_diagnostics(file_path)
        load_result.diagnostics = [*load_result.diagnostics, *inventory_diagnostics]
        if load_result.authoring_plan is None:
            status = derive_authoring_status(load_result.diagnostics)
            return AuthoringPlanCompileResult(
                status=status,
                message=build_authoring_message(status, load_result.diagnostics, compiled=True),
                file_path=file_path,
                diagnostics=load_result.diagnostics,
            )
        load_result.diagnostics.extend(
            _stage_inventory_contract_diagnostics(file_path=file_path, authoring_plan=load_result.authoring_plan)
        )
        result = self.compile(load_result.authoring_plan, file_path=file_path)
        result.diagnostics = [*load_result.diagnostics, *result.diagnostics]
        result.status = derive_authoring_status(result.diagnostics)
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
        diagnostics.extend(_boundary_case_diagnostics(case, case_ref, index=index))

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

        setup_steps, setup_diagnostics, setup_captures = self._expand_setup_steps(
            authoring_plan,
            case,
            case_ref,
            available_variables=declared_variable_names,
        )
        diagnostics.extend(setup_diagnostics)

        persisted_verification, persistence_diagnostics, persistence_placeholders = self._build_db_verification(
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
        diagnostics.extend(_workflow_setup_state_mismatch_diagnostics(case=case, case_ref=case_ref))

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
                        request_headers=_merge_default_headers(authoring_plan, case.execute.headers),
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
                    scenario_variables=list(case.scenario_variables),
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
                    scenario_variables=list(case.scenario_variables),
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
            ),
            diagnostics,
        )

    def _expand_setup_steps(
        self,
        authoring_plan: AuthoringPlan,
        case: AuthoringCase,
        case_ref: str,
        *,
        available_variables: set[str] | None = None,
    ) -> tuple[list[PlannedWorkflowStep], list[GenerationDiagnostic], set[str]]:
        workflow_steps: list[PlannedWorkflowStep] = []
        diagnostics: list[GenerationDiagnostic] = []
        available_names = set(available_variables or set())
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
                        auth_strategy=self._resolve_auth_strategy(
                            explicit_auth_strategy=operation.auth_strategy,
                            authoring_plan=authoring_plan,
                        ),
                        capture=list(operation.captures or ([] if operation.oracle is None else operation.oracle.captures)),
                        metadata=_authoring_defaults_metadata(authoring_plan),
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
        if _persistance_template_mixes_primary_key_and_entity_id(
            sql=operation.sql,
            expected_outcomes=expected_outcomes,
            entity_id_field=entity_id_field,
        ):
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_persisted_state_id_field_semantic_mismatch",
                    (
                        "Persisted-state template mixes the DB primary key column `id` with the entity id_field. "
                        "Use one identifier consistently across capture, route placeholders, SQL filters, and DB expectations."
                    ),
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


def _merge_default_headers(authoring_plan: AuthoringPlan, authored_headers: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(authoring_plan.defaults.headers)
    merged.update(dict(authored_headers or {}))
    return merged


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


def _declared_variable_names(authoring_plan: AuthoringPlan, case: AuthoringCase) -> set[str]:
    return _scenario_variable_names(authoring_plan.defaults.scenario_variables) | _scenario_variable_names(
        case.scenario_variables
    )


def _scenario_variable_names(definitions: list[str]) -> set[str]:
    variable_names: set[str] = set()
    for definition in definitions:
        if not isinstance(definition, str) or "=" not in definition:
            continue
        variable_name = definition.split("=", 1)[0].strip().strip("`")
        if variable_name and _VARIABLE_NAME_PATTERN.fullmatch(variable_name):
            variable_names.add(variable_name)
    return variable_names


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


def _persistance_template_mixes_primary_key_and_entity_id(
    *,
    sql: str,
    expected_outcomes: list[str],
    entity_id_field: str,
) -> bool:
    normalized_id_field = entity_id_field.strip()
    if not normalized_id_field or normalized_id_field == "id":
        return False
    sql_pattern = re.compile(
        rf'(?i)(?:\b\w+\.)?"?id"?\s*=\s*:{re.escape(normalized_id_field)}\b'
    )
    if sql_pattern.search(sql) is None:
        return False
    expected_pattern = re.compile(
        rf"`{re.escape(normalized_id_field)}`\s*=\s*`{{{{\s*{re.escape(normalized_id_field)}\s*}}}}`"
    )
    return any(expected_pattern.search(outcome) for outcome in expected_outcomes)


def _boundary_case_diagnostics(
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if case.execute is None:
        return diagnostics
    body = case.execute.body
    params = case.execute.params
    case_text = " ".join(part.strip() for part in (case.title, case.objective) if part and part.strip())
    if not case_text:
        return diagnostics
    diagnostics.extend(_string_boundary_diagnostics(body, case_text, case_ref, index=index))
    diagnostics.extend(_numeric_boundary_diagnostics(params, body, case_text, case_ref, index=index))
    return diagnostics


def _string_length_overflow_threshold(value: str) -> int | None:
    match = _STRING_LENGTH_OVERFLOW_PATTERN.search(value)
    if match is None:
        return None
    return int(match.group(1))


def _collect_string_literals(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        collected: list[str] = []
        for nested_value in value.values():
            collected.extend(_collect_string_literals(nested_value))
        return collected
    if isinstance(value, (list, tuple, set)):
        collected: list[str] = []
        for nested_value in value:
            collected.extend(_collect_string_literals(nested_value))
        return collected
    return []


def _string_boundary_diagnostics(
    body: Any,
    case_text: str,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    threshold = _string_length_overflow_threshold(case_text)
    if threshold is None:
        return []
    string_lengths = [
        len(value)
        for value in _collect_string_literals(body)
        if value and not _extract_placeholders(value)
    ]
    if not string_lengths:
        return []
    actual_max_length = max(string_lengths)
    if actual_max_length > threshold:
        return []
    return [
        authoring_diagnostic(
            "authoring_case_boundary_mismatch",
            (
                "Case text indicates a string-overflow boundary, but the authored request body does not exceed it. "
                "Use a literal longer than the stated threshold."
            ),
            source_ref=case_ref,
            details={
                "case_index": index,
                "threshold": threshold,
                "actual_max_length": actual_max_length,
            },
        )
    ]


def _numeric_boundary_diagnostics(
    params: dict[str, Any],
    body: Any,
    case_text: str,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    numeric_literals = [
        (path, value)
        for path, value in _collect_numeric_literals({"params": params, "body": body})
        if not _numeric_path_has_placeholder(path)
    ]
    if not numeric_literals:
        return diagnostics

    for match in _NUMERIC_GREATER_THAN_PATTERN.finditer(case_text):
        field_name = match.group("field")
        threshold = int(match.group("threshold"))
        diagnostics.extend(
            _numeric_case_boundary_mismatch_diagnostics(
                numeric_literals,
                field_name=field_name,
                case_ref=case_ref,
                case_index=index,
                predicate=lambda value, limit=threshold: value > limit,
                message=(
                    "Case text indicates a numeric overflow boundary, but the authored value does not exceed it. "
                    "Use a literal greater than the stated threshold."
                ),
                details={"threshold": threshold, "field": field_name, "rule": "greater_than"},
            )
        )

    for match in _NEGATIVE_FIELD_PATTERN.finditer(case_text):
        field_name = match.group("field")
        diagnostics.extend(
            _numeric_case_boundary_mismatch_diagnostics(
                numeric_literals,
                field_name=field_name,
                case_ref=case_ref,
                case_index=index,
                predicate=lambda value: value < 0,
                message=(
                    "Case text indicates a negative numeric boundary, but the authored value is not negative. "
                    "Use a negative literal for the stated field."
                ),
                details={"field": field_name, "rule": "negative"},
            )
        )

    for match in _ZERO_FIELD_PATTERN.finditer(case_text):
        field_name = match.group("field")
        diagnostics.extend(
            _numeric_case_boundary_mismatch_diagnostics(
                numeric_literals,
                field_name=field_name,
                case_ref=case_ref,
                case_index=index,
                predicate=lambda value: value == 0,
                message=(
                    "Case text indicates a zero-value boundary, but the authored value is not zero. "
                    "Use zero for the stated field."
                ),
                details={"field": field_name, "rule": "zero"},
            )
        )

    return diagnostics


def _numeric_case_boundary_mismatch_diagnostics(
    numeric_literals: list[tuple[str, int | float]],
    *,
    field_name: str,
    case_ref: str,
    case_index: int,
    predicate: Any,
    message: str,
    details: dict[str, Any],
) -> list[GenerationDiagnostic]:
    relevant_literals = _relevant_numeric_literals(numeric_literals, field_name)
    if not relevant_literals:
        return [
            authoring_diagnostic(
                "authoring_case_boundary_mismatch",
                "Case text indicates a numeric boundary, but no authored numeric literal was found for the stated field.",
                source_ref=case_ref,
                details={**details, "case_index": case_index, "actual_values": []},
            )
        ]
    if any(predicate(value) for _, value in relevant_literals):
        return []
    return [
        authoring_diagnostic(
            "authoring_case_boundary_mismatch",
            message,
            source_ref=case_ref,
            details={
                **details,
                "case_index": case_index,
                "actual_values": [value for _, value in relevant_literals],
            },
        )
    ]


def _collect_numeric_literals(value: Any, *, path: str = "") -> list[tuple[str, int | float]]:
    if value is None:
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [(path, value)]
    if isinstance(value, str):
        return []
    if isinstance(value, dict):
        collected: list[tuple[str, int | float]] = []
        for key, nested_value in value.items():
            nested_path = f"{path}.{key}" if path else str(key)
            collected.extend(_collect_numeric_literals(nested_value, path=nested_path))
        return collected
    if isinstance(value, (list, tuple, set)):
        collected: list[tuple[str, int | float]] = []
        for index, nested_value in enumerate(value):
            nested_path = f"{path}[{index}]" if path else f"[{index}]"
            collected.extend(_collect_numeric_literals(nested_value, path=nested_path))
        return collected
    return []


def _relevant_numeric_literals(
    numeric_literals: list[tuple[str, int | float]],
    field_name: str,
) -> list[tuple[str, int | float]]:
    normalized_field = _normalize_case_field_name(field_name)
    relevant = [
        (path, value)
        for path, value in numeric_literals
        if normalized_field in {_normalize_case_field_name(part) for part in _numeric_path_parts(path)}
    ]
    if relevant:
        return relevant
    return numeric_literals


def _numeric_path_parts(path: str) -> list[str]:
    normalized = path.replace("[", ".").replace("]", "")
    return [part for part in normalized.split(".") if part]


def _normalize_case_field_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _numeric_path_has_placeholder(path: str) -> bool:
    return bool(_extract_placeholders(path))


def _required_stage_inventory_diagnostics(file_path: Path) -> list[GenerationDiagnostic]:
    if managed_generation_artifacts_root_for_path(file_path) is None:
        return []
    inventory_specs = (
        (
            "entity_inventory",
            file_path.parent / ENTITY_INVENTORY_FILENAME,
            ("version", "source_id", "project", "surface", "entities"),
            {"entities"},
        ),
        (
            "operation_inventory",
            file_path.parent / OPERATION_INVENTORY_FILENAME,
            ("version", "source_id", "project", "surface", "entity_operations", "routes"),
            {"entity_operations", "routes", "db_verifications"},
        ),
    )
    diagnostics: list[GenerationDiagnostic] = []
    for inventory_kind, inventory_path, required_fields, list_fields in inventory_specs:
        diagnostics.extend(
            _inventory_file_diagnostics(
                inventory_kind=inventory_kind,
                inventory_path=inventory_path,
                required_fields=required_fields,
                list_fields=list_fields,
            )
        )
    return diagnostics


def _inventory_file_diagnostics(
    *,
    inventory_kind: str,
    inventory_path: Path,
    required_fields: tuple[str, ...],
    list_fields: set[str],
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not inventory_path.exists():
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_missing",
                "Managed authoring bundles require staged inventory files before authoring-plan validation or compile.",
                source_ref=str(inventory_path),
                details={"inventory_kind": inventory_kind, "path": str(inventory_path)},
            )
        )
        return diagnostics
    try:
        import yaml

        payload = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
    except Exception as exc:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_invalid",
                "Staged inventory file could not be parsed as YAML.",
                source_ref=str(inventory_path),
                details={"inventory_kind": inventory_kind, "path": str(inventory_path), "error": str(exc)},
            )
        )
        return diagnostics
    if not isinstance(payload, dict):
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_invalid",
                "Staged inventory file must contain a YAML object.",
                source_ref=str(inventory_path),
                details={"inventory_kind": inventory_kind, "path": str(inventory_path)},
            )
        )
        return diagnostics
    missing_fields = [field_name for field_name in required_fields if field_name not in payload]
    if missing_fields:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_invalid",
                "Staged inventory file is missing required top-level fields.",
                source_ref=str(inventory_path),
                details={
                    "inventory_kind": inventory_kind,
                    "path": str(inventory_path),
                    "missing_fields": missing_fields,
                },
            )
        )
    for field_name in list_fields:
        if field_name in payload and not isinstance(payload.get(field_name), list):
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_stage_inventory_invalid",
                    "Staged inventory list fields must be YAML arrays.",
                    source_ref=str(inventory_path),
                    details={
                        "inventory_kind": inventory_kind,
                        "path": str(inventory_path),
                        "field": field_name,
                    },
                )
            )
    return diagnostics


def _stage_inventory_contract_diagnostics(
    *,
    file_path: Path,
    authoring_plan: AuthoringPlan,
) -> list[GenerationDiagnostic]:
    if managed_generation_artifacts_root_for_path(file_path) is None:
        return []
    entity_inventory = _load_inventory_payload_if_valid(
        inventory_path=file_path.parent / ENTITY_INVENTORY_FILENAME,
        required_fields=("version", "source_id", "project", "surface", "entities"),
        list_fields={"entities"},
    )
    operation_inventory = _load_inventory_payload_if_valid(
        inventory_path=file_path.parent / OPERATION_INVENTORY_FILENAME,
        required_fields=("version", "source_id", "project", "surface", "entity_operations", "routes"),
        list_fields={"entity_operations", "routes", "db_verifications"},
    )
    if entity_inventory is None or operation_inventory is None:
        return []
    return _cross_check_authoring_plan_against_stage_inventories(
        authoring_plan=authoring_plan,
        file_path=file_path,
        entity_inventory=entity_inventory,
        operation_inventory=operation_inventory,
    )


def _load_inventory_payload_if_valid(
    *,
    inventory_path: Path,
    required_fields: tuple[str, ...],
    list_fields: set[str],
) -> dict[str, Any] | None:
    if not inventory_path.exists():
        return None
    try:
        import yaml

        payload = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if any(field_name not in payload for field_name in required_fields):
        return None
    if any(field_name in payload and not isinstance(payload.get(field_name), list) for field_name in list_fields):
        return None
    return payload


def _cross_check_authoring_plan_against_stage_inventories(
    *,
    authoring_plan: AuthoringPlan,
    file_path: Path,
    entity_inventory: dict[str, Any],
    operation_inventory: dict[str, Any],
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    source_ref = str(file_path)
    entity_specs = _entity_inventory_specs(entity_inventory)
    entity_operation_specs = _entity_operation_inventory_specs(operation_inventory)
    route_specs = _route_inventory_specs(operation_inventory)
    db_verification_specs = _db_verification_inventory_specs(operation_inventory)

    for entity_name, entity_spec in authoring_plan.entities.items():
        inventory_entity_spec = entity_specs.get(entity_name)
        if inventory_entity_spec is None:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_stage_inventory_entity_mismatch",
                    "Authoring-plan entity is not declared in entity-inventory.yaml.",
                    source_ref=source_ref,
                    details={"entity": entity_name},
                )
            )
            continue
        inventory_id_field = str(inventory_entity_spec.get("id_field") or "").strip()
        authored_id_field = entity_spec.id_field.strip()
        if inventory_id_field and authored_id_field and inventory_id_field != authored_id_field:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_stage_inventory_entity_mismatch",
                    "Authoring-plan entity id_field must match entity-inventory.yaml.",
                    source_ref=source_ref,
                    details={
                        "entity": entity_name,
                        "authored_id_field": authored_id_field,
                        "inventory_id_field": inventory_id_field,
                    },
                )
            )
        for operation_name, operation in entity_spec.operations.items():
            operation_key = (entity_name, operation_name)
            if operation.route is not None:
                if operation_key not in entity_operation_specs:
                    diagnostics.append(
                        authoring_diagnostic(
                            "authoring_stage_inventory_operation_mismatch",
                            "Route-backed entity operation is not declared in operation-inventory.yaml.",
                            source_ref=source_ref,
                            details={"entity": entity_name, "operation": operation_name},
                        )
                    )
            if operation.sql.strip():
                db_verification_spec = db_verification_specs.get(operation_key)
                if db_verification_spec is None:
                    diagnostics.append(
                        authoring_diagnostic(
                            "authoring_stage_inventory_operation_mismatch",
                            "DB verification operation is not declared in operation-inventory.yaml.",
                            source_ref=source_ref,
                            details={"entity": entity_name, "operation": operation_name},
                        )
                    )
                else:
                    scoped_by = str(db_verification_spec.get("scoped_by") or "").strip()
                    if scoped_by and inventory_id_field and scoped_by != inventory_id_field:
                        diagnostics.append(
                            authoring_diagnostic(
                                "authoring_stage_inventory_operation_mismatch",
                                "DB verification scope must match the entity id_field declared in staged inventories.",
                                source_ref=source_ref,
                                details={
                                    "entity": entity_name,
                                    "operation": operation_name,
                                    "scoped_by": scoped_by,
                                    "inventory_id_field": inventory_id_field,
                                },
                            )
                        )

    for case in authoring_plan.cases:
        case_ref = case.id.strip() or source_ref
        for setup_step in case.setup:
            step_key = (setup_step.use_entity.strip(), setup_step.operation.strip())
            if step_key not in entity_operation_specs:
                diagnostics.append(
                    authoring_diagnostic(
                        "authoring_stage_inventory_operation_mismatch",
                        "Workflow setup operation is not declared in operation-inventory.yaml.",
                        source_ref=case_ref,
                        details={"entity": step_key[0], "operation": step_key[1]},
                    )
                )
        if case.oracle is not None and case.oracle.persisted_state is not None:
            persisted_key = (
                case.oracle.persisted_state.entity.strip(),
                case.oracle.persisted_state.operation.strip(),
            )
            if persisted_key not in db_verification_specs:
                diagnostics.append(
                    authoring_diagnostic(
                        "authoring_stage_inventory_operation_mismatch",
                        "Persisted-state operation is not declared in operation-inventory.yaml.",
                        source_ref=case_ref,
                        details={"entity": persisted_key[0], "operation": persisted_key[1]},
                    )
                )
        if case.execute is None or case.execute.route is None:
            continue
        route_key = (
            case.execute.route.method.strip().upper(),
            case.execute.route.path.strip(),
        )
        route_spec = route_specs.get(route_key)
        if route_spec is None:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_stage_inventory_route_mismatch",
                    "Authoring case route is not declared in operation-inventory.yaml.",
                    source_ref=case_ref,
                    details={"method": route_key[0], "path": route_key[1]},
                )
            )
            continue
        expected_status = None if case.oracle is None else case.oracle.status_code
        if isinstance(expected_status, int):
            success_status = _maybe_int(route_spec.get("success_status"))
            failure_statuses = {_maybe_int(item) for item in route_spec.get("failure_statuses", [])}
            failure_statuses.discard(None)
            if 200 <= expected_status < 300:
                if success_status is not None and expected_status != success_status:
                    diagnostics.append(
                        authoring_diagnostic(
                            "authoring_stage_inventory_status_mismatch",
                            "Success HTTP status in authoring-plan.yaml does not match operation-inventory.yaml.",
                            source_ref=case_ref,
                            details={
                                "method": route_key[0],
                                "path": route_key[1],
                                "authored_status": expected_status,
                                "inventory_success_status": success_status,
                            },
                        )
                    )
            elif failure_statuses and expected_status not in failure_statuses:
                diagnostics.append(
                    authoring_diagnostic(
                        "authoring_stage_inventory_status_mismatch",
                        "Failure HTTP status in authoring-plan.yaml is not listed in operation-inventory.yaml.",
                        source_ref=case_ref,
                        details={
                            "method": route_key[0],
                            "path": route_key[1],
                            "authored_status": expected_status,
                            "inventory_failure_statuses": sorted(failure_statuses),
                        },
                    )
                )
        if case.kind.strip().lower() != "workflow" or not case.setup:
            continue
        expected_state = _normalized_inventory_state(route_spec.get("precondition_state")) or _expected_precondition_state(case)
        actual_state = _infer_setup_state_from_inventory(case.setup, entity_operation_specs)
        if expected_state is None or actual_state is None or expected_state == actual_state:
            continue
        diagnostics.append(
            authoring_diagnostic(
                "authoring_stage_inventory_state_mismatch",
                "Workflow setup state derived from operation-inventory.yaml does not satisfy the case precondition.",
                source_ref=case_ref,
                details={
                    "expected_state": expected_state,
                    "actual_state": actual_state,
                    "route_path": route_key[1],
                    "setup_operations": [step.operation for step in case.setup],
                },
            )
        )
    return diagnostics


def _entity_inventory_specs(entity_inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for item in entity_inventory.get("entities", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        specs[name] = item
    return specs


def _entity_operation_inventory_specs(operation_inventory: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    specs: dict[tuple[str, str], dict[str, Any]] = {}
    for item in operation_inventory.get("entity_operations", []):
        if not isinstance(item, dict):
            continue
        entity_name = str(item.get("entity") or "").strip()
        operation_name = str(item.get("operation") or "").strip()
        if not entity_name or not operation_name:
            continue
        specs[(entity_name, operation_name)] = item
    return specs


def _route_inventory_specs(operation_inventory: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    specs: dict[tuple[str, str], dict[str, Any]] = {}
    for item in operation_inventory.get("routes", []):
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "").strip().upper()
        path = str(item.get("path") or "").strip()
        if not method or not path:
            continue
        specs[(method, path)] = item
    return specs


def _db_verification_inventory_specs(operation_inventory: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    specs: dict[tuple[str, str], dict[str, Any]] = {}
    for item in operation_inventory.get("db_verifications", []):
        if not isinstance(item, dict):
            continue
        entity_name = str(item.get("entity") or "").strip()
        operation_name = str(item.get("operation") or "").strip()
        if not entity_name or not operation_name:
            continue
        specs[(entity_name, operation_name)] = item
    return specs


def _infer_setup_state_from_inventory(
    setup_steps: list[AuthoringSetupStep],
    operation_specs: dict[tuple[str, str], dict[str, Any]],
) -> str | None:
    state: str | None = None
    for step in setup_steps:
        operation_spec = operation_specs.get((step.use_entity.strip(), step.operation.strip()))
        if operation_spec is None:
            continue
        state = _normalized_inventory_state(operation_spec.get("effect_state")) or state
    return state


def _normalized_inventory_state(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _workflow_setup_state_mismatch_diagnostics(
    *,
    case: AuthoringCase,
    case_ref: str,
) -> list[GenerationDiagnostic]:
    if case.kind.strip().lower() != "workflow" or not case.setup or case.execute is None or case.execute.route is None:
        return []
    actual_state = _infer_setup_state(case.setup)
    if actual_state is None:
        return []
    expected_state = _expected_precondition_state(case)
    if expected_state is None or expected_state == actual_state:
        return []
    return [
        authoring_diagnostic(
            "authoring_workflow_setup_state_mismatch",
            (
                "Workflow setup appears to leave the entity in a different lifecycle state than the case objective "
                "or execute route expects. This often produces the wrong HTTP status at execution time."
            ),
            severity=DiagnosticSeverity.WARNING,
            source_ref=case_ref,
            details={
                "expected_state": expected_state,
                "actual_state": actual_state,
                "setup_operations": [step.operation for step in case.setup],
                "route_path": case.execute.route.path,
            },
        )
    ]


def _normalized_email_expectation_diagnostics(
    *,
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
    setup_steps: list[PlannedWorkflowStep],
    persisted_verification: PlannedDbVerification | None,
) -> list[GenerationDiagnostic]:
    request_email_variables = set()
    if case.execute is not None:
        request_email_variables.update(_collect_email_placeholders(case.execute.body))
    for step in setup_steps:
        if step.step_type.strip().lower() != "api":
            continue
        request_email_variables.update(_collect_email_placeholders(step.request_body))
    if not request_email_variables:
        return []

    variable_definitions = _scenario_variable_definitions(authoring_plan, case)
    risky_bindings: list[dict[str, Any]] = []
    for expectation in [] if case.oracle is None else case.oracle.business_checks:
        binding = _email_expectation_binding(expectation)
        if binding is None:
            continue
        variable_name, field_path = binding
        if variable_name not in request_email_variables:
            continue
        if _variable_guarantees_lowercase(variable_name, variable_definitions):
            continue
        risky_bindings.append(
            {
                "scope": "api",
                "field": field_path,
                "variable": variable_name,
                "rule": expectation,
            }
        )
    if persisted_verification is not None:
        for expectation in persisted_verification.expected_outcomes:
            binding = _email_expectation_binding(expectation)
            if binding is None:
                continue
            variable_name, field_path = binding
            if variable_name not in request_email_variables:
                continue
            if _variable_guarantees_lowercase(variable_name, variable_definitions):
                continue
            risky_bindings.append(
                {
                    "scope": "db",
                    "field": field_path,
                    "variable": variable_name,
                    "rule": expectation,
                }
            )
    if not risky_bindings:
        return []

    variables = sorted({str(item["variable"]) for item in risky_bindings})
    return [
        authoring_diagnostic(
            "authoring_expected_value_case_ambiguous",
            (
                "Expected email checks reuse the same placeholder as request input, but that variable is not "
                "guaranteed lowercase. If the system normalizes email casing, author separate submitted and expected "
                "variables, for example `submitted_email` plus `expected_email = derived:submitted_email|lower`."
            ),
            severity=DiagnosticSeverity.WARNING,
            source_ref=case_ref,
            details={
                "variables": variables,
                "bindings": risky_bindings,
            },
        )
    ]


def _scenario_variable_definitions(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
) -> dict[str, ScenarioVariableDefinition]:
    definitions: dict[str, ScenarioVariableDefinition] = {}
    for entry in [*authoring_plan.defaults.scenario_variables, *case.scenario_variables]:
        if "=" not in entry:
            continue
        variable_name, raw_value = entry.split("=", 1)
        variable_name = variable_name.strip()
        if not variable_name or not _VARIABLE_NAME_PATTERN.fullmatch(variable_name):
            continue
        try:
            definitions[variable_name] = build_variable_definition(variable_name, raw_value.strip())
        except Exception:
            continue
    return definitions


def _collect_email_placeholders(value: Any, *, path: str = "") -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return set(_extract_placeholders(value)) if _path_targets_email(path) else set()
    if isinstance(value, dict):
        names: set[str] = set()
        for key, nested_value in value.items():
            nested_path = f"{path}.{key}" if path else str(key)
            names.update(_collect_email_placeholders(nested_value, path=nested_path))
        return names
    if isinstance(value, (list, tuple, set)):
        names: set[str] = set()
        for index, nested_value in enumerate(value):
            nested_path = f"{path}[{index}]" if path else f"[{index}]"
            names.update(_collect_email_placeholders(nested_value, path=nested_path))
        return names
    return set()


def _path_targets_email(path: str) -> bool:
    if not path.strip():
        return False
    last_part = _numeric_path_parts(path)[-1] if _numeric_path_parts(path) else path
    normalized = _normalize_case_field_name(last_part)
    return "email" in normalized


def _email_expectation_binding(expectation: str) -> tuple[str, str] | None:
    match = _EXPECTATION_COMPARISON_RE.fullmatch(expectation.strip())
    if match is None:
        return None
    field_path = _strip_wrapping_quotes(match.group("left").strip()).strip()
    if not _path_targets_email(field_path):
        return None
    placeholder_name = _exact_placeholder_name(match.group("right"))
    if placeholder_name is None:
        return None
    return placeholder_name, field_path


def _exact_placeholder_name(value: str) -> str | None:
    normalized = _strip_wrapping_quotes(value.strip()).strip()
    match = _EXACT_PLACEHOLDER_PATTERN.fullmatch(normalized)
    return match.group(1) if match is not None else None


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        return value[1:-1]
    return value


def _variable_guarantees_lowercase(
    variable_name: str,
    definitions: dict[str, ScenarioVariableDefinition],
    *,
    _stack: set[str] | None = None,
) -> bool:
    definition = definitions.get(variable_name)
    if definition is None:
        return False
    stack = set() if _stack is None else set(_stack)
    if variable_name in stack:
        return False
    stack.add(variable_name)
    if definition.source == ScenarioVariableSource.LITERAL:
        return definition.raw_value == definition.raw_value.lower()
    if definition.source == ScenarioVariableSource.TEMPLATE:
        literal_text = _PLACEHOLDER_PATTERN.sub("", definition.raw_value)
        if literal_text != literal_text.lower():
            return False
        dependencies = _extract_placeholders(definition.raw_value)
        return all(_variable_guarantees_lowercase(dependency, definitions, _stack=stack) for dependency in dependencies)
    if definition.source == ScenarioVariableSource.DERIVED:
        guaranteed = (
            _variable_guarantees_lowercase(definition.source_name, definitions, _stack=stack)
            if definition.source_name
            else False
        )
        for transform in definition.transforms:
            normalized = transform.strip().lower()
            if normalized == "lower":
                guaranteed = True
            elif normalized == "upper":
                guaranteed = False
            elif normalized == "trim":
                continue
            else:
                return False
        return guaranteed
    if definition.source == ScenarioVariableSource.GENERATED:
        return definition.raw_value.strip().lower().endswith(":uuid")
    return False


def _infer_setup_state(setup_steps: list[AuthoringSetupStep]) -> str | None:
    state: str | None = None
    for step in setup_steps:
        hinted_state = _operation_state_hint(step.operation)
        if hinted_state is not None:
            state = hinted_state
    return state


def _operation_state_hint(operation_name: str) -> str | None:
    normalized = operation_name.strip().lower()
    if not normalized:
        return None
    if "archive" in normalized:
        return "archived"
    if "suspend" in normalized:
        return "suspended"
    if "activate" in normalized:
        return "active"
    if "create" in normalized:
        return "active"
    return None


def _expected_precondition_state(case: AuthoringCase) -> str | None:
    route_path = "" if case.execute is None or case.execute.route is None else case.execute.route.path.strip().lower()
    expected_status = case.oracle.status_code if case.oracle is not None else None
    if route_path.endswith("/activate") and isinstance(expected_status, int) and 200 <= expected_status < 300:
        return "suspended"
    if route_path.endswith("/suspend") and isinstance(expected_status, int) and 200 <= expected_status < 300:
        return "active"
    case_text = " ".join(part.strip().lower() for part in (case.title, case.objective) if part and part.strip())
    if "archived user" in case_text or "for archived user" in case_text:
        return "archived"
    if "suspended user" in case_text or "already suspended" in case_text:
        return "suspended"
    if "active user" in case_text or "already active" in case_text:
        return "active"
    return None
