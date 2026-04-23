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
    PlannedRouteIntent,
)
from tools.generation.evidence.models import TargetStack

from .models import AgentPlanLoadResult, AgentPlanValidationResult

AGENT_PLAN_TEMPLATE_VERSION = "agent-plan-template-v1"
MANAGED_AGENT_INPUT_ROOT = ("artifacts", "agent", "input")
AGENT_PLAN_BLOCKING_CODES = {
    "agent_plan_missing",
    "agent_plan_missing_source_id",
    "agent_plan_missing_project",
    "agent_plan_missing_title",
    "agent_plan_no_cases",
    "agent_plan_case_missing_title",
    "agent_plan_case_missing_objective",
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
            metadata={"template_version": AGENT_PLAN_TEMPLATE_VERSION},
            planned_test_cases=[
                AgentPlannedTestCaseInput(
                    title="Replace with case title",
                    objective="Replace with case objective.",
                    kind="functional",
                    preconditions=["Replace with required setup or state."],
                    actions=["Replace with the minimal operator-authored action."],
                    expected_outcomes=["Replace with the deterministic expected outcome."],
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
    return diagnostics


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
                "expected_outcomes",
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
        if stack_hint not in {None, ""} and str(stack_hint) not in {item.value for item in TargetStack}:
            diagnostics.append(
                GenerationDiagnostic(
                    code="agent_plan_evidence_scope_invalid_stack_hint",
                    message="evidence_scope.stack_hint must be one of the supported target stacks.",
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
        return "Agent-authored plan input is structurally present but blocked by missing required fields."
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.severity == DiagnosticSeverity.ERROR)
    return f"Agent-authored plan input validation failed with {error_count} error(s)."


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
