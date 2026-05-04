"""Deterministic compiler from compact authoring-plan into AgentTestPlanInput."""

from __future__ import annotations

from pathlib import Path
from tools.generation.authoring import validate_agent_plan_input
from tools.generation.domain.models import (
    AgentPlannedTestCaseInput,
    AgentTestPlanInput,
    GenerationDiagnostic,
    PlannedDbVerification,
    PlannedRouteIntent,
    PlannedWorkflowStep,
)

from .case_diagnostics.boundary import _boundary_case_diagnostics
from .case_diagnostics.identity import _env_backed_identity_guid_diagnostics
from .case_diagnostics.lifecycle import (
    _workflow_same_state_contract_warning,
    _workflow_setup_state_mismatch_diagnostics,
)
from .case_diagnostics.db_expectations import _db_string_placeholder_quoting_diagnostics
from .case_diagnostics.email import _normalized_email_expectation_diagnostics
from .case_diagnostics.request_constraints import _request_constraint_diagnostics
from .case_diagnostics.visibility import _visibility_claim_diagnostics
from .diagnostics import authoring_diagnostic, build_authoring_message, derive_authoring_status
from .helpers import (
    _VARIABLE_NAME_PATTERN,
    _api_expected_outcomes,
    _authoring_defaults_metadata,
    _build_route_intent,
    _capture_targets,
    _declared_variable_names,
    _extract_placeholders,
    _extract_placeholders_from_value,
    _merge_default_headers,
    _operation_uses_placeholder,
    _persistance_template_mixes_primary_key_and_entity_id,
    _requires_persistence,
)
from .inventory_diagnostics import (
    _required_stage_inventory_diagnostics,
    _stage_inventory_contract_diagnostics,
    suppress_inventory_backed_same_state_warnings,
)
from .loaders import AuthoringPlanLoader
from .models import (
    AUTHORING_STATE_CHANGE_ALLOWED_TEXT,
    AuthoringCase,
    AuthoringEntityOperation,
    AuthoringPlan,
    AuthoringPlanCompileResult,
    AuthoringPlanLoadResult,
    AuthoringStateChange,
    AuthoringSetupStep,
    normalize_state_change_value,
)

_SUPPORTED_CASE_KINDS = {"api", "workflow", "db-check"}


def _is_code_project_path(value: str) -> bool:
    normalized = value.strip().replace("\\", "/").strip("/")
    return normalized.startswith("code/") and len(normalized.split("/", 1)[1].strip()) > 0


class AuthoringPlanCompiler:
    """Compile compact authoring DSL into the current internal IR."""

    def __init__(self, loader: AuthoringPlanLoader | None = None) -> None:
        self.loader = loader or AuthoringPlanLoader()

    def load(self, file_path: Path) -> AuthoringPlanLoadResult:
        return self.loader.load(file_path)

    def validate(self, authoring_plan: AuthoringPlan, *, file_path: Path | None = None) -> AuthoringPlanCompileResult:
        return self._compile(authoring_plan, file_path=file_path, validation_only=True)

    def validate_file(self, file_path: Path) -> AuthoringPlanCompileResult:
        return self._compile_file(file_path, validation_only=True)

    def compile(self, authoring_plan: AuthoringPlan, *, file_path: Path | None = None) -> AuthoringPlanCompileResult:
        return self._compile(authoring_plan, file_path=file_path, validation_only=False)

    def compile_file(self, file_path: Path) -> AuthoringPlanCompileResult:
        return self._compile_file(file_path, validation_only=False)

    def _compile_file(
        self,
        file_path: Path,
        *,
        validation_only: bool,
    ) -> AuthoringPlanCompileResult:
        load_result = self.load(file_path)
        inventory_diagnostics = _required_stage_inventory_diagnostics(file_path)
        load_result.diagnostics = [*load_result.diagnostics, *inventory_diagnostics]
        if load_result.authoring_plan is None:
            status = derive_authoring_status(load_result.diagnostics)
            return AuthoringPlanCompileResult(
                status=status,
                message=build_authoring_message(status, load_result.diagnostics, compiled=not validation_only),
                file_path=file_path,
                diagnostics=load_result.diagnostics,
            )
        load_result.diagnostics.extend(
            _stage_inventory_contract_diagnostics(file_path=file_path, authoring_plan=load_result.authoring_plan)
        )
        result = self._compile(load_result.authoring_plan, file_path=file_path, validation_only=validation_only)
        result.diagnostics = [*load_result.diagnostics, *result.diagnostics]
        result.diagnostics = suppress_inventory_backed_same_state_warnings(
            file_path=file_path,
            diagnostics=result.diagnostics,
        )
        result.status = derive_authoring_status(result.diagnostics)
        result.message = build_authoring_message(result.status, result.diagnostics, compiled=not validation_only)
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
            compiled_plan = self._build_agent_plan(authoring_plan, compiled_cases)
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

    @staticmethod
    def _build_agent_plan(
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
        elif not _is_code_project_path(authoring_plan.project):
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_project_must_target_code_subdir",
                    "Authoring plan project must point at a workspace project under code/<project>.",
                    source_ref=source_ref,
                    details={"project": authoring_plan.project},
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
        diagnostics.extend(_env_backed_identity_guid_diagnostics(authoring_plan, source_ref))
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
            invalid_key_fields = [
                key_field
                for key_field in entity_spec.key_fields
                if not key_field.strip() or not _VARIABLE_NAME_PATTERN.fullmatch(key_field.strip())
            ]
            if invalid_key_fields:
                diagnostics.append(
                    authoring_diagnostic(
                        "authoring_invalid_entity_key_field",
                        "Entity key_fields must be machine-readable variable names such as user_id.",
                        source_ref=entity_name,
                        details={"entity": entity_name, "key_fields": invalid_key_fields},
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
        diagnostics.extend(_boundary_case_diagnostics(authoring_plan, case, case_ref, index=index))
        diagnostics.extend(_visibility_claim_diagnostics(authoring_plan, case, case_ref, index=index))

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
        diagnostics.extend(
            _request_constraint_diagnostics(
                authoring_plan=authoring_plan,
                case=case,
                case_ref=case_ref,
                setup_steps=setup_steps,
            )
        )
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
            **_authoring_defaults_metadata(authoring_plan),
            **dict(case.metadata),
            "authoring_case_id": case.id,
            "authoring_kind": case.kind,
            "state_change": case.state_change,
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
        entity_key_fields = [field_name.strip() for field_name in entity_spec.key_fields if field_name.strip()]
        has_id_scope = bool(entity_id_field and entity_id_field in placeholders)
        has_key_scope = bool(entity_key_fields and set(entity_key_fields).issubset(placeholders))
        if entity_id_field and not has_id_scope and not has_key_scope:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_persisted_state_id_field_missing",
                    "Persisted-state template must reference the entity id_field or all declared key_fields so verification is scoped to the authored entity instance.",
                    source_ref=case_ref,
                    details={
                        "entity": entity_name,
                        "operation": operation_name,
                        "id_field": entity_id_field,
                        "key_fields": entity_key_fields,
                        "placeholders": sorted(placeholders),
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
