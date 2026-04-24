"""Deterministic authoring helpers for AgentTestPlanInput."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.common.statuses import StepStatus
from tools.generation.domain.models import (
    AgentPlannedTestCaseInput,
    AgentTestPlanInput,
    DiagnosticSeverity,
    GapCategory,
    GenerationDiagnostic,
    PlannedCaseGap,
    PlannedDbVerification,
    PlannedRouteIntent,
    PlannedWorkflowStep,
)
from tools.scenario_runner.domain.models import ApiStepDefinition, DbStepDefinition, ScenarioStep, ScenarioStepType
from tools.scenario_runner.runtime.validators import ScenarioStepValidator
from tools.db.validators import ReadOnlySqlValidator, SqlNormalizer

from .models import AgentPlanLoadResult, AgentPlanValidationResult

AGENT_PLAN_TEMPLATE_VERSION = "agent-plan-template-v1"
MANAGED_AGENT_INPUT_ROOT = ("artifacts", "agent", "generation")
API_EXPECTATION_EXAMPLES = [
    "HTTP 200",
    "HTTP 200 or HTTP 201",
    "response JSON exists",
    "response JSON is an array",
    "response contains field `id`",
    "response `status` = `AUTHENTICATED`",
    "response `createdAt` is not null",
]
DB_EXPECTATION_EXAMPLES = [
    "one row exists",
    "no rows exist",
    "`status` = `ACTIVE`",
    "`revoked_at` is null",
    "`created_at` is not null",
    "`email` starts with `autotest.`",
]
CAPTURE_RULE_EXAMPLES = [
    "response.json.id -> created_id",
    "response.json.principal.sessionId -> session_id",
    "db.first_row.id -> persisted_id",
]
MUTATING_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
AGENT_PLAN_BLOCKING_CODES = {
    "agent_plan_missing",
    "agent_plan_missing_source_id",
    "agent_plan_missing_project",
    "agent_plan_missing_title",
    "agent_plan_no_cases",
    "agent_plan_case_missing_title",
    "agent_plan_case_missing_objective",
    "agent_plan_case_route_or_workflow_required",
    "agent_plan_workflow_case_steps_required",
    "agent_plan_db_case_verification_or_workflow_required",
    "agent_plan_case_mutating_api_db_verification_required",
    "agent_plan_case_missing_expected_outcomes",
    "agent_plan_case_invalid_expectation_contract",
    "agent_plan_workflow_case_level_expected_outcomes_unsupported",
    "agent_plan_case_invalid_capture_contract",
    "agent_plan_case_request_body_required",
    "agent_plan_case_auth_strategy_required",
    "agent_plan_workflow_step_invalid_expectation_contract",
    "agent_plan_workflow_step_invalid_capture_contract",
    "agent_plan_workflow_step_request_body_required",
    "agent_plan_workflow_step_auth_strategy_required",
    "agent_plan_workflow_step_route_required",
    "agent_plan_workflow_step_missing_sql",
    "agent_plan_workflow_step_invalid_sql",
    "agent_plan_workflow_db_verification_required",
}


@dataclass(slots=True)
class AgentPlanAuthoringService:
    """Create, load, and validate structured agent-authored test plans."""

    def resolve_template_output_path(self, output_path: Path) -> Path:
        if not output_path.exists():
            return output_path
        if not _is_managed_agent_input_path(output_path):
            raise FileExistsError(str(output_path))
        return _next_managed_template_output_path(output_path)

    def build_template(
        self,
        *,
        source_id: str = "",
        project: str = "",
        title: str = "",
        goal: str = "",
    ) -> AgentTestPlanInput:
        resolved_source_id = source_id.strip() or "replace-with-source-id"
        resolved_project = project.strip() or "code/replace-project"
        resolved_title = title.strip() or "Replace with test plan title"
        resolved_goal = goal.strip() or "Replace with the feature/test goal."
        return AgentTestPlanInput(
            source_id=resolved_source_id,
            project=resolved_project,
            title=resolved_title,
            goal=resolved_goal,
            assumptions=[
                "Replace with stable assumptions that affect the entire plan."
            ],
            open_questions=[
                "Replace with unresolved operator-facing questions."
            ],
            metadata={
                "template_version": AGENT_PLAN_TEMPLATE_VERSION,
                "authoring_hints": {
                    "api_expected_outcomes_examples": API_EXPECTATION_EXAMPLES,
                    "db_expected_outcomes_examples": DB_EXPECTATION_EXAMPLES,
                    "capture_rule_syntax": "<source> -> <variable_name>",
                    "capture_rule_examples": CAPTURE_RULE_EXAMPLES,
                },
            },
            planned_test_cases=[
                AgentPlannedTestCaseInput(
                    title="Replace with case title",
                    objective="Replace with case objective.",
                    kind="api",
                    preconditions=["Replace with required setup or state."],
                    actions=["Replace with the minimal operator-authored action."],
                    auth_strategy=["Use the required auth/header strategy from runtime config without inlining secrets."],
                    requires_auth_strategy=True,
                    request_headers={"Content-Type": "application/json"},
                    request_body={"field": "value"},
                    requires_request_body=True,
                    observable_outcomes=["Replace with the externally visible behavior this case proves."],
                    expected_outcomes=[
                        "HTTP 200",
                        "response JSON exists",
                        "response contains field `id`",
                    ],
                    capture=["response.json.id -> created_id"],
                    requires_db_verification=True,
                    priority="normal",
                    tags=["replace-tag"],
                    unresolved_items=["Replace with unresolved case-specific detail."],
                    gaps=[
                        PlannedCaseGap(
                            category=GapCategory.ENDPOINT_DETAIL,
                            message="Replace with typed unresolved gap when the route or executable detail is not known.",
                        )
                    ],
                    assumptions=["Replace with case-specific assumption if needed."],
                    route=PlannedRouteIntent(
                        http_method="GET",
                        endpoint_path="/replace/path",
                        path_kind="collection",
                    ),
                    db_verification=PlannedDbVerification(
                        name="Replace with DB verification step name when persisted-state checks are needed.",
                        sql="SELECT id, status FROM replace_table WHERE id = :created_id",
                        params={"created_id": "{{created_id}}"},
                        expected_outcomes=[
                            "one row exists",
                            "`status` = `ACTIVE`",
                        ],
                    ),
                    workflow_steps=[
                        PlannedWorkflowStep(
                            step_type="api",
                            title="Optional e2e step: authenticate or create prerequisite state.",
                            route=PlannedRouteIntent(
                                http_method="POST",
                                endpoint_path="/replace/workflow/start",
                            ),
                            expected_outcomes=["HTTP 200", "response JSON exists"],
                            capture=["response.json.id -> workflow_entity_id"],
                        ),
                        PlannedWorkflowStep(
                            step_type="api",
                            title="Optional e2e step: verify the next operation in the same workflow.",
                            route=PlannedRouteIntent(
                                http_method="GET",
                                endpoint_path="/replace/workflow/{{workflow_entity_id}}",
                            ),
                            expected_outcomes=["HTTP 200", "response JSON exists"],
                        ),
                    ],
                    metadata={"notes": "Optional freeform case metadata."},
                )
            ],
        )

    def write_template(
        self,
        output_path: Path,
        *,
        source_id: str = "",
        project: str = "",
        title: str = "",
        goal: str = "",
    ) -> AgentTestPlanInput:
        output_path = self.resolve_template_output_path(output_path)
        template = self.build_template(
            source_id=source_id,
            project=project,
            title=title,
            goal=goal,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(template.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return template

    def load(self, file_path: Path) -> AgentPlanLoadResult:
        diagnostics: list[GenerationDiagnostic] = []
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_file_missing",
                    message="Agent-authored plan file does not exist.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(file_path),
                )
            )
            return AgentPlanLoadResult(file_path=file_path, diagnostics=diagnostics)
        except OSError as exc:
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_file_unreadable",
                    message="Agent-authored plan file could not be read.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(file_path),
                    details={"error": str(exc)},
                )
            )
            return AgentPlanLoadResult(file_path=file_path, diagnostics=diagnostics)
        except json.JSONDecodeError as exc:
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_file_invalid_json",
                    message="Agent-authored plan file must contain valid JSON.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(file_path),
                    details={"error": str(exc)},
                )
            )
            return AgentPlanLoadResult(file_path=file_path, diagnostics=diagnostics)

        diagnostics.extend(_validate_agent_plan_payload_shape(payload, str(file_path)))
        if diagnostics:
            return AgentPlanLoadResult(file_path=file_path, diagnostics=diagnostics)

        agent_plan = AgentTestPlanInput.from_dict(payload)
        return AgentPlanLoadResult(file_path=file_path, agent_plan=agent_plan)

    def validate(
        self,
        agent_plan: AgentTestPlanInput,
        *,
        file_path: Path | None = None,
    ) -> AgentPlanValidationResult:
        source_ref = str(file_path) if file_path is not None else agent_plan.source_id
        diagnostics = validate_agent_plan_input(agent_plan, source_ref)
        status = _derive_validation_status(diagnostics)
        return AgentPlanValidationResult(
            status=status,
            message=_build_validation_message(status, diagnostics),
            file_path=file_path,
            agent_plan=agent_plan,
            diagnostics=diagnostics,
            case_count=len(agent_plan.planned_test_cases),
        )

    def validate_file(self, file_path: Path) -> AgentPlanValidationResult:
        load_result = self.load(file_path)
        if load_result.agent_plan is None:
            status = StepStatus.ERROR
            diagnostics = load_result.diagnostics
            return AgentPlanValidationResult(
                status=status,
                message=_build_validation_message(status, diagnostics),
                file_path=file_path,
                diagnostics=diagnostics,
                case_count=0,
            )
        validation_result = self.validate(load_result.agent_plan, file_path=file_path)
        validation_result.diagnostics = [*load_result.diagnostics, *validation_result.diagnostics]
        validation_result.message = _build_validation_message(
            validation_result.status,
            validation_result.diagnostics,
        )
        return validation_result


def validate_agent_plan_input(
    agent_plan: AgentTestPlanInput | None,
    source_ref: str,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if agent_plan is None:
        return [
            GenerationDiagnostic(
                code="agent_plan_missing",
                message="input_mode=agent_plan requires an AgentTestPlanInput payload.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=source_ref,
            )
        ]
    if not agent_plan.source_id.strip():
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_missing_source_id",
                message="Agent-authored plan input must include source_id.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=source_ref,
            )
        )
    if not agent_plan.project.strip():
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_missing_project",
                message="Agent-authored plan input must include project.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=agent_plan.source_id or source_ref,
            )
        )
    if not agent_plan.title.strip():
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_missing_title",
                message="Agent-authored plan input must include a plan title.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=agent_plan.source_id or source_ref,
            )
        )
    if not agent_plan.planned_test_cases:
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_no_cases",
                message="Agent-authored plan input must include at least one planned test case.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=agent_plan.source_id or source_ref,
            )
        )
    for index, case_input in enumerate(agent_plan.planned_test_cases, start=1):
        case_ref = case_input.case_id or f"{agent_plan.source_id or source_ref}#case-{index:03d}"
        if not case_input.title.strip():
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_case_missing_title",
                    message="Agent-authored planned test case must include a title.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=case_ref,
                    details={"case_index": index},
                )
            )
        if not case_input.objective.strip():
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_case_missing_objective",
                    message="Agent-authored planned test case must include an objective.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=case_ref,
                    details={"case_index": index},
                )
            )
        if case_input.route is not None:
            if not case_input.route.http_method.strip():
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_case_route_missing_http_method",
                        message="Case route must include http_method when route is provided.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=case_ref,
                        details={"case_index": index},
                    )
                )
            if not case_input.route.endpoint_path.strip():
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_case_route_missing_endpoint_path",
                        message="Case route must include endpoint_path when route is provided.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=case_ref,
                        details={"case_index": index},
                    )
                )
        diagnostics.extend(_validate_case_execution_shape(case_input, case_ref, index))
        diagnostics.extend(_validate_case_expectation_contract(case_input, case_ref, index))
        diagnostics.extend(_validate_case_capture_contract(case_input, case_ref, index))
        diagnostics.extend(_validate_case_auth_contract(case_input, case_ref, index))
        diagnostics.extend(_validate_case_request_contract(case_input, case_ref, index))
        diagnostics.extend(_validate_case_db_verification(case_input, case_ref, index))
    return diagnostics


def _validate_case_execution_shape(
    case_input: AgentPlannedTestCaseInput,
    case_ref: str,
    case_index: int,
) -> list[GenerationDiagnostic]:
    kind = case_input.kind.strip().lower()
    diagnostics: list[GenerationDiagnostic] = []
    has_route = case_input.route is not None
    has_workflow = bool(case_input.workflow_steps)
    has_case_db_verification = case_input.db_verification is not None
    has_db_workflow = _workflow_has_authored_db_step(case_input)

    if kind == "api" and not has_route and not has_workflow:
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_case_route_or_workflow_required",
                message=(
                    "API planned case must author either a concrete route or executable workflow_steps. "
                    "Do not leave runnable API coverage in a prose-only state."
                ),
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={"case_index": case_index, "kind": kind},
            )
        )
    if kind == "workflow" and not has_workflow:
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_workflow_case_steps_required",
                message="Workflow planned case must include executable workflow_steps.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={"case_index": case_index, "kind": kind},
            )
        )
    if kind == "db" and not has_case_db_verification and not has_db_workflow:
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_db_case_verification_or_workflow_required",
                message="DB planned case must author db_verification or a db workflow_step.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={"case_index": case_index, "kind": kind},
            )
        )
    if _case_requires_persisted_state_verification(case_input) and not has_case_db_verification:
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_case_mutating_api_db_verification_required",
                message=(
                    "Single-endpoint API case includes a successful mutating request but no persisted-state DB verification. "
                    "Author db_verification so the case is execution-ready."
                ),
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={"case_index": case_index, "kind": kind},
            )
        )
    return diagnostics


def _validate_case_expectation_contract(
    case_input: AgentPlannedTestCaseInput,
    case_ref: str,
    case_index: int,
) -> list[GenerationDiagnostic]:
    kind = case_input.kind.strip().lower()
    diagnostics: list[GenerationDiagnostic] = []
    if kind in {"api", "db"} and not case_input.expected_outcomes and not _workflow_steps_have_expectations(case_input):
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_case_missing_expected_outcomes",
                message="API and DB planned cases must include deterministic expected_outcomes using runner-supported syntax, either at case level or in workflow_steps.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={"case_index": case_index, "kind": kind},
            )
        )
    if kind not in {"api", "db"} and not case_input.workflow_steps:
        return diagnostics
    if kind == "workflow" and case_input.expected_outcomes:
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_workflow_case_level_expected_outcomes_unsupported",
                message=(
                    "Workflow planned case must express executable expectations inside workflow_steps. "
                    "Do not use case-level prose expected_outcomes such as 'workflow completes'."
                ),
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={
                    "case_index": case_index,
                    "kind": kind,
                    "supported_examples": API_EXPECTATION_EXAMPLES + DB_EXPECTATION_EXAMPLES,
                },
            )
        )
    if kind in {"api", "db"} and not case_input.expected_outcomes:
        diagnostics.extend(_validate_workflow_step_expectation_contract(case_input, case_ref, case_index))
        return diagnostics
    if kind not in {"api", "db"}:
        diagnostics.extend(_validate_workflow_step_expectation_contract(case_input, case_ref, case_index))
        return diagnostics

    validator = ScenarioStepValidator()
    for contract_diagnostic in validator.inspect_contract(_case_contract_probe(case_input, case_index)):
        if contract_diagnostic.supported:
            continue
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_case_invalid_expectation_contract",
                message=_expectation_contract_error_message(kind, contract_diagnostic.rule),
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={
                    "case_index": case_index,
                    "kind": kind,
                    "rule": contract_diagnostic.rule,
                    "step_type": contract_diagnostic.step_type.value,
                    "hint": _expectation_contract_hint(kind),
                    "supported_examples": API_EXPECTATION_EXAMPLES if kind == "api" else DB_EXPECTATION_EXAMPLES,
                },
            )
        )
    diagnostics.extend(_validate_workflow_step_expectation_contract(case_input, case_ref, case_index))
    return diagnostics


def _case_contract_probe(
    case_input: AgentPlannedTestCaseInput,
    case_index: int,
) -> ScenarioStep:
    kind = case_input.kind.strip().lower()
    step_id = case_input.case_id.strip() or f"case-contract-{case_index:03d}"
    title = case_input.title.strip() or step_id
    if kind == "api":
        route = case_input.route or PlannedRouteIntent(http_method="GET", endpoint_path="/__placeholder__")
        return ScenarioStep(
            step_id=step_id,
            step_number=case_index,
            title=title,
            step_type=ScenarioStepType.API,
            api=ApiStepDefinition(
                name=title,
                method=route.http_method.strip().upper() or "GET",
                path=route.endpoint_path.strip() or "/__placeholder__",
                expected=list(case_input.expected_outcomes),
            ),
        )
    return ScenarioStep(
        step_id=step_id,
        step_number=case_index,
        title=title,
        step_type=ScenarioStepType.DB,
        db=DbStepDefinition(
            name=title,
            sql="SELECT 1",
            expected=list(case_input.expected_outcomes),
        ),
    )


def _validate_case_capture_contract(
    case_input: AgentPlannedTestCaseInput,
    case_ref: str,
    case_index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    for capture_rule in case_input.capture:
        if _capture_rule_is_valid(capture_rule):
            continue
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_case_invalid_capture_contract",
                message="Capture rule must use '<source> -> <variable_name>' syntax, for example 'response.json.id -> created_id'.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={
                    "case_index": case_index,
                    "rule": capture_rule,
                    "hint": "Use '<source> -> <variable_name>' syntax.",
                    "supported_examples": CAPTURE_RULE_EXAMPLES,
                },
            )
        )
    diagnostics.extend(_validate_workflow_step_capture_contract(case_input, case_ref, case_index))
    return diagnostics


def _capture_rule_is_valid(capture_rule: str) -> bool:
    if "->" not in capture_rule:
        return False
    source_expression, variable_name = (part.strip() for part in capture_rule.split("->", 1))
    return bool(source_expression and variable_name)


def _workflow_steps_have_expectations(case_input: AgentPlannedTestCaseInput) -> bool:
    return any(step.expected_outcomes for step in case_input.workflow_steps)


def _validate_workflow_step_expectation_contract(
    case_input: AgentPlannedTestCaseInput,
    case_ref: str,
    case_index: int,
) -> list[GenerationDiagnostic]:
    validator = ScenarioStepValidator()
    diagnostics: list[GenerationDiagnostic] = []
    for step_index, workflow_step in enumerate(case_input.workflow_steps, start=1):
        step_kind = workflow_step.step_type.strip().lower()
        if step_kind not in {"api", "db"}:
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_workflow_step_invalid_type",
                    message="workflow_steps step_type must be 'api' or 'db'.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=case_ref,
                    details={"case_index": case_index, "step_index": step_index, "step_type": workflow_step.step_type},
                )
            )
            continue
        if not workflow_step.expected_outcomes:
            continue
        for contract_diagnostic in validator.inspect_contract(
            _workflow_step_contract_probe(case_input, workflow_step, case_index, step_index)
        ):
            if contract_diagnostic.supported:
                continue
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_workflow_step_invalid_expectation_contract",
                    message=_expectation_contract_error_message(step_kind, contract_diagnostic.rule),
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=case_ref,
                    details={
                        "case_index": case_index,
                        "step_index": step_index,
                        "kind": step_kind,
                        "rule": contract_diagnostic.rule,
                        "step_type": contract_diagnostic.step_type.value,
                        "hint": _expectation_contract_hint(step_kind),
                        "supported_examples": API_EXPECTATION_EXAMPLES if step_kind == "api" else DB_EXPECTATION_EXAMPLES,
                    },
                )
            )
    return diagnostics


def _workflow_step_contract_probe(
    case_input: AgentPlannedTestCaseInput,
    workflow_step: PlannedWorkflowStep,
    case_index: int,
    step_index: int,
) -> ScenarioStep:
    step_id = case_input.case_id.strip() or f"case-contract-{case_index:03d}-step-{step_index:02d}"
    title = workflow_step.title.strip() or f"Workflow step {step_index}"
    if workflow_step.step_type.strip().lower() == "api":
        route = workflow_step.route or PlannedRouteIntent(http_method="GET", endpoint_path="/__placeholder__")
        return ScenarioStep(
            step_id=step_id,
            step_number=step_index,
            title=title,
            step_type=ScenarioStepType.API,
            api=ApiStepDefinition(
                name=title,
                method=route.http_method.strip().upper() or "GET",
                path=route.endpoint_path.strip() or "/__placeholder__",
                expected=list(workflow_step.expected_outcomes),
            ),
        )
    return ScenarioStep(
        step_id=step_id,
        step_number=step_index,
        title=title,
        step_type=ScenarioStepType.DB,
        db=DbStepDefinition(
            name=title,
            sql=workflow_step.sql.strip() or "SELECT 1",
            expected=list(workflow_step.expected_outcomes),
        ),
    )


def _validate_workflow_step_capture_contract(
    case_input: AgentPlannedTestCaseInput,
    case_ref: str,
    case_index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    for step_index, workflow_step in enumerate(case_input.workflow_steps, start=1):
        for capture_rule in workflow_step.capture:
            if _capture_rule_is_valid(capture_rule):
                continue
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_workflow_step_invalid_capture_contract",
                    message="Workflow step capture rule must use '<source> -> <variable_name>' syntax.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=case_ref,
                    details={
                        "case_index": case_index,
                        "step_index": step_index,
                        "rule": capture_rule,
                        "hint": "Use '<source> -> <variable_name>' syntax.",
                        "supported_examples": CAPTURE_RULE_EXAMPLES,
                    },
                )
            )
    return diagnostics


def _has_auth_header_signal(headers: dict[str, Any]) -> bool:
    for raw_name in headers:
        name = str(raw_name).strip().lower()
        if name == "authorization":
            return True
        if "token" in name or "api-key" in name or "apikey" in name or name == "cookie":
            return True
    return False


def _validate_case_auth_contract(
    case_input: AgentPlannedTestCaseInput,
    case_ref: str,
    case_index: int,
) -> list[GenerationDiagnostic]:
    if case_input.kind.strip().lower() != "api":
        return _validate_workflow_step_auth_contract(case_input, case_ref, case_index)
    diagnostics: list[GenerationDiagnostic] = []
    if case_input.requires_auth_strategy and not (
        case_input.auth_strategy or _has_auth_header_signal(case_input.request_headers)
    ):
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_case_auth_strategy_required",
                message="Case requires auth strategy, but no auth_strategy or auth-like request header was authored.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={"case_index": case_index},
            )
        )
    diagnostics.extend(_validate_workflow_step_auth_contract(case_input, case_ref, case_index))
    return diagnostics


def _validate_case_request_contract(
    case_input: AgentPlannedTestCaseInput,
    case_ref: str,
    case_index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if case_input.kind.strip().lower() == "api" and case_input.requires_request_body and case_input.request_body is None:
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_case_request_body_required",
                message="Case requires a request body, but request_body was not authored.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={"case_index": case_index},
            )
        )
    diagnostics.extend(_validate_workflow_step_request_contract(case_input, case_ref, case_index))
    return diagnostics


def _validate_workflow_step_auth_contract(
    case_input: AgentPlannedTestCaseInput,
    case_ref: str,
    case_index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    for step_index, workflow_step in enumerate(case_input.workflow_steps, start=1):
        if workflow_step.step_type.strip().lower() != "api":
            continue
        if workflow_step.requires_auth_strategy and not (
            workflow_step.auth_strategy or _has_auth_header_signal(workflow_step.request_headers)
        ):
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_workflow_step_auth_strategy_required",
                    message="Workflow API step requires auth strategy, but no auth_strategy or auth-like request header was authored.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=case_ref,
                    details={"case_index": case_index, "step_index": step_index},
                )
            )
    return diagnostics


def _validate_workflow_step_request_contract(
    case_input: AgentPlannedTestCaseInput,
    case_ref: str,
    case_index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    for step_index, workflow_step in enumerate(case_input.workflow_steps, start=1):
        step_kind = workflow_step.step_type.strip().lower()
        if step_kind == "api" and workflow_step.requires_request_body and workflow_step.request_body is None:
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_workflow_step_request_body_required",
                    message="Workflow API step requires a request body, but request_body was not authored.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=case_ref,
                    details={"case_index": case_index, "step_index": step_index},
                )
            )
        if step_kind == "db" and not workflow_step.sql.strip():
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_workflow_step_missing_sql",
                    message="Workflow DB step must include a read-only SQL query.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=case_ref,
                    details={"case_index": case_index, "step_index": step_index},
                )
            )
        elif step_kind == "db":
            try:
                ReadOnlySqlValidator(SqlNormalizer()).validate(workflow_step.sql)
            except Exception as exc:  # noqa: BLE001
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_workflow_step_invalid_sql",
                        message=f"Workflow DB step SQL failed read-only validation: {exc}",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=case_ref,
                        details={"case_index": case_index, "step_index": step_index},
                    )
                )
        if step_kind == "api":
            route = workflow_step.route
            if route is None or not route.http_method.strip() or not route.endpoint_path.strip():
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_workflow_step_route_required",
                        message="Workflow API step must include route.http_method and route.endpoint_path.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=case_ref,
                        details={"case_index": case_index, "step_index": step_index},
                    )
                )
    return diagnostics


def _validate_case_db_verification(
    case_input: AgentPlannedTestCaseInput,
    case_ref: str,
    case_index: int,
) -> list[GenerationDiagnostic]:
    verification = case_input.db_verification
    diagnostics: list[GenerationDiagnostic] = []
    if (
        _workflow_requires_persisted_state_verification(case_input)
        and verification is None
        and not _workflow_has_authored_db_step(case_input)
    ):
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_workflow_db_verification_required",
                message=(
                    "Workflow case includes successful mutating API steps but no persisted-state DB verification. "
                    "Author either case-level db_verification or a db workflow_step."
                ),
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={"case_index": case_index},
            )
        )
    if case_input.requires_db_verification and verification is None:
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_case_db_verification_required",
                message="Case requires DB verification, but no db_verification step was authored.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={"case_index": case_index},
            )
        )
        return diagnostics
    if verification is None:
        return diagnostics

    if not verification.sql.strip():
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_case_db_verification_missing_sql",
                message="DB verification must include a read-only SQL query.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={"case_index": case_index},
            )
        )
    else:
        try:
            ReadOnlySqlValidator(SqlNormalizer()).validate(verification.sql)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_case_db_verification_invalid_sql",
                    message=f"DB verification SQL failed read-only validation: {exc}",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=case_ref,
                    details={"case_index": case_index},
                )
            )

    if not verification.expected_outcomes:
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_case_db_verification_missing_expected_outcomes",
                message="DB verification must include deterministic expected_outcomes using runner-supported DB syntax.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={"case_index": case_index},
            )
        )
    else:
        probe = ScenarioStep(
            step_id=case_input.case_id.strip() or f"case-db-contract-{case_index:03d}",
            step_number=case_index,
            title=verification.name.strip() or case_input.title.strip() or f"case-{case_index:03d}",
            step_type=ScenarioStepType.DB,
            db=DbStepDefinition(
                name=verification.name.strip() or case_input.title.strip(),
                sql=verification.sql.strip() or "SELECT 1",
                params=dict(verification.params),
                expected=list(verification.expected_outcomes),
            ),
        )
        validator = ScenarioStepValidator()
        for contract_diagnostic in validator.inspect_contract(probe):
            if contract_diagnostic.supported:
                continue
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_case_db_verification_invalid_expectation_contract",
                    message=_expectation_contract_error_message("db", contract_diagnostic.rule),
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=case_ref,
                    details={
                        "case_index": case_index,
                        "rule": contract_diagnostic.rule,
                        "hint": _expectation_contract_hint("db"),
                        "supported_examples": DB_EXPECTATION_EXAMPLES,
                    },
                )
            )

    for capture_rule in verification.capture:
        if _capture_rule_is_valid(capture_rule):
            continue
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_case_db_verification_invalid_capture_contract",
                message="DB verification capture rule must use '<source> -> <variable_name>' syntax, for example 'db.first_row.id -> persisted_id'.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=case_ref,
                details={
                    "case_index": case_index,
                    "rule": capture_rule,
                    "hint": "Use '<source> -> <variable_name>' syntax.",
                    "supported_examples": CAPTURE_RULE_EXAMPLES,
                },
            )
        )
    return diagnostics


def _workflow_requires_persisted_state_verification(case_input: AgentPlannedTestCaseInput) -> bool:
    if not case_input.workflow_steps:
        return False
    case_level_success = _expectations_indicate_success(case_input.expected_outcomes)
    for workflow_step in case_input.workflow_steps:
        if workflow_step.step_type.strip().lower() != "api" or workflow_step.route is None:
            continue
        method = workflow_step.route.http_method.strip().upper()
        if method not in MUTATING_HTTP_METHODS:
            continue
        if _expectations_indicate_success(workflow_step.expected_outcomes) or (
            not workflow_step.expected_outcomes and case_level_success
        ):
            return True
    return False


def _case_requires_persisted_state_verification(case_input: AgentPlannedTestCaseInput) -> bool:
    if case_input.kind.strip().lower() != "api" or case_input.route is None:
        return False
    method = case_input.route.http_method.strip().upper()
    if method not in MUTATING_HTTP_METHODS:
        return False
    return _expectations_indicate_success(case_input.expected_outcomes)


def _workflow_has_authored_db_step(case_input: AgentPlannedTestCaseInput) -> bool:
    return any(
        workflow_step.step_type.strip().lower() == "db" and workflow_step.sql.strip()
        for workflow_step in case_input.workflow_steps
    )


def _expectations_indicate_success(expectations: list[str]) -> bool:
    for expectation in expectations:
        normalized = expectation.strip().upper()
        if normalized.startswith("HTTP 2"):
            return True
    return False


def _validate_agent_plan_payload_shape(
    payload: Any,
    source_ref: str,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not isinstance(payload, dict):
        return [
            GenerationDiagnostic(
                code="agent_plan_payload_not_object",
                message="Agent-authored plan file must contain a JSON object.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=source_ref,
            )
        ]

    list_fields = ("planned_test_cases", "assumptions", "open_questions")
    for field_name in list_fields:
        value = payload.get(field_name)
        if value is not None and not isinstance(value, list):
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_field_not_list",
                    message=f"Field '{field_name}' must be a JSON array.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=source_ref,
                    details={"field": field_name},
                )
            )

    planned_cases = payload.get("planned_test_cases")
    if isinstance(planned_cases, list):
        for index, item in enumerate(planned_cases, start=1):
            if not isinstance(item, dict):
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_case_not_object",
                        message="Each planned_test_cases entry must be a JSON object.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=source_ref,
                        details={"case_index": index},
                    )
                )
                continue
            for field_name in (
                "preconditions",
                "actions",
                "auth_strategy",
                "observable_outcomes",
                "expected_outcomes",
                "capture",
                "workflow_steps",
                "tags",
                "unresolved_items",
                "gaps",
                "assumptions",
            ):
                value = item.get(field_name)
                if value is not None and not isinstance(value, list):
                    diagnostics.append(
                        GenerationDiagnostic(
                            code="agent_plan_case_field_not_list",
                            message=f"Case field '{field_name}' must be a JSON array.",
                            severity=DiagnosticSeverity.ERROR,
                            source_ref=source_ref,
                            details={"case_index": index, "field": field_name},
                        )
                    )
            metadata = item.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_case_metadata_not_object",
                        message="Case metadata must be a JSON object.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=source_ref,
                        details={"case_index": index},
                    )
                )
            for field_name in ("request_headers", "request_params"):
                value = item.get(field_name)
                if value is not None and not isinstance(value, dict):
                    diagnostics.append(
                        GenerationDiagnostic(
                            code="agent_plan_case_request_field_not_object",
                            message=f"Case field '{field_name}' must be a JSON object when provided.",
                            severity=DiagnosticSeverity.ERROR,
                            source_ref=source_ref,
                            details={"case_index": index, "field": field_name},
                        )
                    )
            raw_requires_request_body = item.get("requires_request_body")
            if raw_requires_request_body is not None and not isinstance(raw_requires_request_body, bool):
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_case_requires_request_body_not_bool",
                        message="Case requires_request_body must be a boolean when provided.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=source_ref,
                        details={"case_index": index},
                    )
                )
            raw_requires_auth_strategy = item.get("requires_auth_strategy")
            if raw_requires_auth_strategy is not None and not isinstance(raw_requires_auth_strategy, bool):
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_case_requires_auth_strategy_not_bool",
                        message="Case requires_auth_strategy must be a boolean when provided.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=source_ref,
                        details={"case_index": index},
                    )
                )
            route = item.get("route")
            if route is not None and not isinstance(route, dict):
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_case_route_not_object",
                        message="Case route must be a JSON object when provided.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=source_ref,
                        details={"case_index": index},
                    )
                )
            workflow_steps = item.get("workflow_steps")
            if isinstance(workflow_steps, list):
                for step_index, workflow_step in enumerate(workflow_steps, start=1):
                    if not isinstance(workflow_step, dict):
                        diagnostics.append(
                            GenerationDiagnostic(
                                code="agent_plan_workflow_step_not_object",
                                message="Each workflow_steps entry must be a JSON object.",
                                severity=DiagnosticSeverity.ERROR,
                                source_ref=source_ref,
                                details={"case_index": index, "step_index": step_index},
                            )
                        )
                        continue
                    for field_name in ("auth_strategy", "capture", "expected_outcomes"):
                        value = workflow_step.get(field_name)
                        if value is not None and not isinstance(value, list):
                            diagnostics.append(
                                GenerationDiagnostic(
                                    code="agent_plan_workflow_step_field_not_list",
                                    message=f"workflow_steps field '{field_name}' must be a JSON array.",
                                    severity=DiagnosticSeverity.ERROR,
                                    source_ref=source_ref,
                                    details={"case_index": index, "step_index": step_index, "field": field_name},
                                )
                            )
                    for field_name in ("request_headers", "request_params", "params", "metadata"):
                        value = workflow_step.get(field_name)
                        if value is not None and not isinstance(value, dict):
                            diagnostics.append(
                                GenerationDiagnostic(
                                    code="agent_plan_workflow_step_field_not_object",
                                    message=f"workflow_steps field '{field_name}' must be a JSON object when provided.",
                                    severity=DiagnosticSeverity.ERROR,
                                    source_ref=source_ref,
                                    details={"case_index": index, "step_index": step_index, "field": field_name},
                                )
                            )
                    for field_name in ("requires_request_body", "requires_auth_strategy"):
                        value = workflow_step.get(field_name)
                        if value is not None and not isinstance(value, bool):
                            diagnostics.append(
                                GenerationDiagnostic(
                                    code="agent_plan_workflow_step_field_not_bool",
                                    message=f"workflow_steps field '{field_name}' must be a boolean when provided.",
                                    severity=DiagnosticSeverity.ERROR,
                                    source_ref=source_ref,
                                    details={"case_index": index, "step_index": step_index, "field": field_name},
                                )
                            )
                    step_route = workflow_step.get("route")
                    if step_route is not None and not isinstance(step_route, dict):
                        diagnostics.append(
                            GenerationDiagnostic(
                                code="agent_plan_workflow_step_route_not_object",
                                message="workflow_steps route must be a JSON object when provided.",
                                severity=DiagnosticSeverity.ERROR,
                                source_ref=source_ref,
                                details={"case_index": index, "step_index": step_index},
                            )
                        )
            raw_requires_db_verification = item.get("requires_db_verification")
            if raw_requires_db_verification is not None and not isinstance(raw_requires_db_verification, bool):
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_case_requires_db_verification_not_bool",
                        message="Case requires_db_verification must be a boolean when provided.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=source_ref,
                        details={"case_index": index},
                    )
                )
            db_verification = item.get("db_verification")
            if db_verification is not None and not isinstance(db_verification, dict):
                diagnostics.append(
                    GenerationDiagnostic(
                        code="agent_plan_case_db_verification_not_object",
                        message="Case db_verification must be a JSON object when provided.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=source_ref,
                        details={"case_index": index},
                    )
                )
            if isinstance(db_verification, dict):
                params = db_verification.get("params")
                if params is not None and not isinstance(params, dict):
                    diagnostics.append(
                        GenerationDiagnostic(
                            code="agent_plan_case_db_verification_params_not_object",
                            message="db_verification.params must be a JSON object when provided.",
                            severity=DiagnosticSeverity.ERROR,
                            source_ref=source_ref,
                            details={"case_index": index},
                        )
                    )
                for field_name in ("expected_outcomes", "capture"):
                    value = db_verification.get(field_name)
                    if value is not None and not isinstance(value, list):
                        diagnostics.append(
                            GenerationDiagnostic(
                                code="agent_plan_case_db_verification_field_not_list",
                                message=f"db_verification field '{field_name}' must be a JSON array.",
                                severity=DiagnosticSeverity.ERROR,
                                source_ref=source_ref,
                                details={"case_index": index, "field": field_name},
                            )
                        )
            gaps = item.get("gaps")
            if isinstance(gaps, list):
                for gap_index, gap in enumerate(gaps, start=1):
                    if not isinstance(gap, dict):
                        diagnostics.append(
                            GenerationDiagnostic(
                                code="agent_plan_case_gap_not_object",
                                message="Each case gap must be a JSON object.",
                                severity=DiagnosticSeverity.ERROR,
                                source_ref=source_ref,
                                details={"case_index": index, "gap_index": gap_index},
                            )
                        )
                        continue
                    raw_category = gap.get("category")
                    if raw_category not in {item.value for item in GapCategory}:
                        diagnostics.append(
                            GenerationDiagnostic(
                                code="agent_plan_case_gap_invalid_category",
                                message="Case gap category must be one of the supported typed gap values.",
                                severity=DiagnosticSeverity.ERROR,
                                source_ref=source_ref,
                                details={"case_index": index, "gap_index": gap_index, "category": raw_category},
                            )
                        )
                    if not str(gap.get("message", "")).strip():
                        diagnostics.append(
                            GenerationDiagnostic(
                                code="agent_plan_case_gap_missing_message",
                                message="Case gap must include a non-empty message.",
                                severity=DiagnosticSeverity.ERROR,
                                source_ref=source_ref,
                                details={"case_index": index, "gap_index": gap_index},
                            )
                        )

    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_metadata_not_object",
                message="Top-level metadata must be a JSON object.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=source_ref,
            )
        )
    evidence_scope = payload.get("evidence_scope")
    if evidence_scope is not None and not isinstance(evidence_scope, dict):
        diagnostics.append(
            GenerationDiagnostic(
                code="agent_plan_evidence_scope_not_object",
                message="Top-level evidence_scope must be a JSON object when provided.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=source_ref,
            )
        )
    if isinstance(evidence_scope, dict):
        paths = evidence_scope.get("paths")
        if paths is not None and not isinstance(paths, list):
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_evidence_scope_paths_not_list",
                    message="evidence_scope.paths must be a JSON array when provided.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=source_ref,
                )
            )
        file_patterns = evidence_scope.get("file_patterns")
        if file_patterns is not None and not isinstance(file_patterns, list):
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_evidence_scope_file_patterns_not_list",
                    message="evidence_scope.file_patterns must be a JSON array when provided.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=source_ref,
                )
            )
        stack_hint = evidence_scope.get("stack_hint")
        if stack_hint not in {None, ""} and not isinstance(stack_hint, str):
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_evidence_scope_invalid_stack_hint",
                    message="evidence_scope.stack_hint must be a string when provided.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=source_ref,
                    details={"stack_hint": str(stack_hint)},
                )
            )
    return diagnostics


def _derive_validation_status(diagnostics: list[GenerationDiagnostic]) -> StepStatus:
    if any(diagnostic.code in AGENT_PLAN_BLOCKING_CODES for diagnostic in diagnostics):
        return StepStatus.BLOCKED
    if any(diagnostic.severity == DiagnosticSeverity.ERROR for diagnostic in diagnostics):
        return StepStatus.ERROR
    return StepStatus.PASS


def _build_validation_message(
    status: StepStatus,
    diagnostics: list[GenerationDiagnostic],
) -> str:
    if status == StepStatus.PASS:
        return "Agent-authored plan input is valid."
    if status == StepStatus.BLOCKED:
        if any(
            diagnostic.code in {
                "agent_plan_case_invalid_expectation_contract",
                "agent_plan_case_db_verification_invalid_expectation_contract",
                "agent_plan_case_invalid_capture_contract",
                "agent_plan_case_db_verification_invalid_capture_contract",
            }
            for diagnostic in diagnostics
        ):
            return "Agent-authored plan input is blocked by unsupported expectation or capture DSL; see diagnostics for supported examples."
        return "Agent-authored plan input is structurally present but blocked by missing required fields or contract issues."
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.severity == DiagnosticSeverity.ERROR)
    return f"Agent-authored plan input validation failed with {error_count} error(s)."


def _expectation_contract_hint(kind: str) -> str:
    if kind == "db":
        return "Use deterministic DB expectation syntax like 'one row exists', 'no rows exist', or '`status` = `ACTIVE`'."
    return (
        "Use deterministic API expectation syntax like 'HTTP 404', 'response JSON exists', "
        "or 'response `status` = `AUTHENTICATED`'."
    )


def _expectation_contract_error_message(kind: str, rule: str) -> str:
    normalized_rule = rule.rstrip()
    separator = "" if normalized_rule.endswith((".", "!", "?")) else "."
    return f"Unsupported {kind.upper()} expectation rule: {normalized_rule}{separator} {_expectation_contract_hint(kind)}"


def _is_managed_agent_input_path(output_path: Path) -> bool:
    parts = tuple(part.lower() for part in output_path.parent.parts)
    width = len(MANAGED_AGENT_INPUT_ROOT)
    return any(parts[index:index + width] == MANAGED_AGENT_INPUT_ROOT for index in range(len(parts) - width + 1))


def _next_managed_template_output_path(output_path: Path) -> Path:
    parent = output_path.parent
    filename = output_path.name
    stem = _slugify(output_path.stem)
    counter = 1
    while True:
        candidate = parent / f"{stem}-{counter:03d}" / filename
        if not candidate.exists():
            return candidate
        counter += 1


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug.lower() or "agent-plan"
