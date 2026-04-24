"""Deterministic rendering of normalized plans into non-executed scenario drafts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from tools.generation.domain.gaps import format_case_gap_note, project_case_gap
from tools.generation.domain.models import (
    DiagnosticSeverity,
    GenerationDiagnostic,
    GenerationRunContext,
    NormalizedTestPlan,
    PlannedTestCase,
    PlannedWorkflowStep,
    RouteSupportHint,
)
from tools.scenario_runner.parser import MarkdownScenarioParser

from .models import (
    DeferredScenarioItem,
    ScenarioDraft,
    ScenarioDraftSet,
    ScenarioDraftValidationResult,
    ScenarioRenderResult,
    UnsupportedCheck,
)

MUTATING_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
EXECUTION_BLOCKING_GAP_CODES = {
    "auth_strategy_unresolved",
    "environment_unresolved",
    "data_setup_unresolved",
    "assertion_detail_unresolved",
    "executable_detail_unresolved",
}


@dataclass(slots=True)
class ScenarioDraftPreviewService:
    """Render, persist, and parser-validate scenario draft previews."""

    renderer: "DraftScenarioRenderer" = field(default_factory=lambda: DraftScenarioRenderer())
    parser: MarkdownScenarioParser = field(default_factory=MarkdownScenarioParser)

    def render_and_persist(
        self,
        plan: NormalizedTestPlan,
        run_context: GenerationRunContext,
        artifact_store: Any,
    ) -> tuple[ScenarioRenderResult, dict[str, Path]]:
        render_result = self.renderer.render(plan)
        artifact_store.write_scenario_drafts(run_context, render_result.draft_set)
        render_result.validation_results = [
            self._validate_draft(run_context.artifact_dir / draft.relative_path, draft)
            for draft in render_result.draft_set.drafts
        ]
        result_path = artifact_store.write_scenario_render_result(run_context, render_result)
        return render_result, {
            "scenario_drafts_dir": run_context.artifact_dir / "scenario-drafts",
            "scenario_render_result": result_path,
            "scenario_parse_results": run_context.artifact_dir / "scenario-parse-results.json",
            "unsupported_checks": run_context.artifact_dir / "unsupported-checks.json",
            "deferred_items": run_context.artifact_dir / "deferred-items.json",
        }

    def _validate_draft(self, path: Path, draft: ScenarioDraft) -> ScenarioDraftValidationResult:
        parse_result = self.parser.parse_result(path)
        return ScenarioDraftValidationResult(
            draft_id=draft.draft_id,
            case_id=draft.case_id,
            path=path,
            parse_valid=not parse_result.has_errors,
            diagnostics=[diagnostic.to_dict() for diagnostic in parse_result.diagnostics],
        )


@dataclass(slots=True)
class DraftScenarioRenderer:
    """Render parser-valid markdown previews from authored routes and workflow steps."""

    environment_template: str = "env/{project_name}.env"

    def render(self, plan: NormalizedTestPlan) -> ScenarioRenderResult:
        drafts: list[ScenarioDraft] = []
        deferred_items: list[DeferredScenarioItem] = []
        unsupported_checks: list[UnsupportedCheck] = []
        diagnostics: list[GenerationDiagnostic] = []

        for test_case in plan.test_cases:
            blocking_gap_checks = _blocking_gap_checks(test_case)
            if blocking_gap_checks:
                unsupported_checks.extend(blocking_gap_checks)
                deferred_items.append(
                    DeferredScenarioItem(
                        case_id=test_case.case_id,
                        title=test_case.title,
                        reason_code="execution_blocking_case_gaps",
                        message="Planned case was deferred because execution-blocking authored gaps remain.",
                        unsupported_checks=blocking_gap_checks,
                    )
                )
                diagnostics.append(
                    GenerationDiagnostic(
                        code="scenario_draft_deferred_due_to_case_gaps",
                        message="Planned case was deferred because execution-blocking authored gaps remain.",
                        severity=DiagnosticSeverity.WARNING,
                        source_ref=test_case.case_id,
                        details={"gap_codes": [check.reason_code for check in blocking_gap_checks]},
                    )
                )
                continue
            if test_case.workflow_steps:
                workflow_support = _workflow_route_binding(test_case)
                draft_route_binding = workflow_support or _db_only_workflow_binding(test_case)
                if not _workflow_steps_renderable(test_case):
                    check = UnsupportedCheck(
                        case_id=test_case.case_id,
                        reason_code="workflow_step_incomplete",
                        message="Workflow scenario draft rendering requires complete api/db workflow_steps.",
                        details={"workflow_step_count": len(test_case.workflow_steps)},
                    )
                    unsupported_checks.append(check)
                    deferred_items.append(
                        DeferredScenarioItem(
                            case_id=test_case.case_id,
                            title=test_case.title,
                            reason_code="unsupported_for_preview",
                            message="Planned workflow case was deferred from scenario draft rendering.",
                            unsupported_checks=[check],
                        )
                    )
                    diagnostics.append(
                        GenerationDiagnostic(
                            code="scenario_draft_deferred",
                            message="Planned workflow case lacks complete structured workflow step details for draft rendering.",
                            severity=DiagnosticSeverity.WARNING,
                            source_ref=test_case.case_id,
                            details={"reason_code": check.reason_code},
                        )
                    )
                    continue
                diagnostics.append(
                    GenerationDiagnostic(
                        code="rendering_based_on_workflow_steps",
                        message="Scenario draft rendering used structured workflow_steps as the execution source.",
                        severity=DiagnosticSeverity.INFO,
                        source_ref=test_case.case_id,
                        details={"workflow_step_count": len(test_case.workflow_steps)},
                    )
                )
                draft_id = f"draft-{test_case.case_id}"
                title = f"{plan.title} - {test_case.title}".strip(" -")
                relative_path = Path("scenario-drafts") / f"{_slugify(test_case.case_id + '-' + test_case.title)}.md"
                drafts.append(
                    ScenarioDraft(
                        draft_id=draft_id,
                        case_id=test_case.case_id,
                        title=title,
                        markdown=self._render_workflow_markdown(plan, test_case, title),
                        relative_path=relative_path,
                        source_refs=list(test_case.source_refs),
                        metadata={
                            "renderer": "draft-scenario-renderer-v1",
                            "preview_only": True,
                            "route_binding": draft_route_binding,
                            "workflow_route_bindings": _workflow_route_bindings(test_case),
                            "workflow_step_count": len(test_case.workflow_steps),
                            "case_support": _draft_case_support(test_case, draft_route_binding),
                            "expected_assertions_present": _test_case_has_authored_expectations(test_case),
                            "capture_rules_present": _test_case_has_capture_rules(test_case),
                            "auth_strategy_required": any(
                                step.requires_auth_strategy for step in test_case.workflow_steps
                            ) or test_case.requires_auth_strategy,
                            "auth_strategy_present": any(
                                step.auth_strategy or _has_auth_header_signal(step.request_headers)
                                for step in test_case.workflow_steps
                            ) or bool(test_case.auth_strategy) or _has_auth_header_signal(test_case.request_headers),
                            "request_body_required": any(
                                step.requires_request_body for step in test_case.workflow_steps
                            ) or test_case.requires_request_body,
                            "request_body_present": any(
                                step.request_body is not None for step in test_case.workflow_steps
                            ) or test_case.request_body is not None,
                            "db_verification_required": _test_case_requires_db_verification(test_case),
                            "db_verification_present": _test_case_has_db_verification(test_case),
                            "case_gaps": [gap.to_dict() for gap in test_case.gaps],
                        },
                    )
                )
                continue
            support = _supported_api_hint(test_case)
            if support is None:
                reason_code = _unsupported_reason_code(test_case)
                check = UnsupportedCheck(
                    case_id=test_case.case_id,
                    reason_code=reason_code,
                    message=_unsupported_reason_message(reason_code),
                    details={
                        "has_route_hints": bool(_case_support_route_hints(test_case)),
                        "readiness": _case_support_readiness(test_case),
                    },
                )
                unsupported_checks.append(check)
                deferred_items.append(
                    DeferredScenarioItem(
                        case_id=test_case.case_id,
                        title=test_case.title,
                        reason_code="unsupported_for_preview",
                        message="Planned case was deferred from scenario draft rendering.",
                        unsupported_checks=[check],
                    )
                )
                diagnostics.append(
                    GenerationDiagnostic(
                        code="scenario_draft_deferred",
                        message="Planned case lacks complete authored route detail for draft rendering.",
                        severity=DiagnosticSeverity.WARNING,
                        source_ref=test_case.case_id,
                        details={"reason_code": check.reason_code},
                    )
                )
                continue

            diagnostics.extend(_render_diagnostics(test_case, support))

            draft_id = f"draft-{test_case.case_id}"
            title = f"{plan.title} - {test_case.title}".strip(" -")
            relative_path = Path("scenario-drafts") / f"{_slugify(test_case.case_id + '-' + test_case.title)}.md"
            drafts.append(
                ScenarioDraft(
                    draft_id=draft_id,
                    case_id=test_case.case_id,
                    title=title,
                    markdown=self._render_markdown(plan, test_case, support, title),
                    relative_path=relative_path,
                    source_refs=list(test_case.source_refs),
                    metadata={
                        "renderer": "draft-scenario-renderer-v1",
                        "preview_only": True,
                        "route_binding": support,
                        "case_support": _draft_case_support(test_case, support),
                        "expected_assertions_present": _test_case_has_authored_expectations(test_case),
                        "capture_rules_present": _test_case_has_capture_rules(test_case),
                        "auth_strategy_required": test_case.requires_auth_strategy,
                        "auth_strategy_present": bool(test_case.auth_strategy) or _has_auth_header_signal(test_case.request_headers),
                        "request_body_required": test_case.requires_request_body,
                        "request_body_present": test_case.request_body is not None,
                        "db_verification_required": _test_case_requires_db_verification(test_case),
                        "db_verification_present": _test_case_has_db_verification(test_case),
                        "case_gaps": [gap.to_dict() for gap in test_case.gaps],
                    },
                )
            )

        return ScenarioRenderResult(
            draft_set=ScenarioDraftSet(
                plan_id=plan.plan_id,
                drafts=drafts,
                deferred_items=deferred_items,
            ),
            unsupported_checks=unsupported_checks,
            diagnostics=diagnostics,
        )

    def _render_markdown(
        self,
        plan: NormalizedTestPlan,
        test_case: PlannedTestCase,
        support: dict[str, Any],
        title: str,
    ) -> str:
        project_name = Path(plan.project).name or _slugify(plan.project)
        method = str(support["http_method"]).upper()
        endpoint_path = str(support["endpoint_path"])
        route_source = str(support.get("route_source") or "planned_route")
        route_readiness = str(support.get("readiness") or "")
        auth_strategy = list(test_case.auth_strategy)
        requires_auth_strategy = test_case.requires_auth_strategy
        request_headers = dict(test_case.request_headers)
        request_params = dict(test_case.request_params)
        request_body = test_case.request_body
        requires_request_body = test_case.requires_request_body
        capture_rules = list(test_case.capture)
        db_verification = test_case.db_verification
        requires_db_verification = test_case.requires_db_verification
        expected_results = test_case.expected_results or [
            "HTTP response is received and must be reviewed before execution."
        ]
        observable_outcomes = list(test_case.observable_outcomes)
        typed_gap_notes = _typed_gap_notes(test_case)
        typed_gap_summary = _typed_gap_summary_lines(test_case)
        notes = [
            "Generated draft preview only. Do not execute without operator review.",
            "Route resolved for preview rendering.",
            f"Route source: {route_source}.",
            (
                "Request structure was authored upstream."
                if request_headers or request_params or request_body is not None
                else "Request body is required for this case but not authored yet."
                if requires_request_body
                else "Request body not inferred."
            ),
            (
                "Auth strategy was authored upstream."
                if auth_strategy or _has_auth_header_signal(request_headers)
                else "Auth strategy is required for this case but not authored yet."
                if requires_auth_strategy
                else "Auth not required for this case."
            ),
            (
                "Deterministic expected assertions were authored upstream."
                if test_case.expected_results
                else "Assertions not generated."
            ),
            (
                "DB verification step was authored upstream."
                if db_verification is not None
                else "DB verification is required for this case but not authored yet."
                if requires_db_verification
                else "Capture rules were authored upstream."
                if capture_rules
                else "No DB checks, captures, or concrete payloads were invented."
            ),
        ]
        if route_readiness:
            notes.append(f"Case readiness: {route_readiness}.")
        notes.append(f"Auth strategy required: {'yes' if requires_auth_strategy else 'no'}.")
        notes.append(f"Request body required: {'yes' if requires_request_body else 'no'}.")
        notes.append(f"DB verification required: {'yes' if requires_db_verification else 'no'}.")
        if support.get("handler_name"):
            notes.append(f"Handler: {support['handler_name']}.")
        if support.get("controller_name"):
            notes.append(f"Controller: {support['controller_name']}.")
        if support.get("path_shape"):
            notes.append(f"Route shape: {support['path_shape']}.")
        for outcome in observable_outcomes:
            notes.append(f"Observable outcome: {outcome}")
        for item in auth_strategy:
            notes.append(f"Auth strategy: {item}")
        for question in test_case.open_questions:
            notes.append(f"Open question: {question}")
        for assumption in test_case.assumptions:
            notes.append(f"Assumption: {assumption}")
        notes.extend(typed_gap_notes)

        lines = [
            f"# Scenario: {_escape_line(title)}",
            "",
            "## Project",
            plan.project,
            "",
            "## Environment",
            self.environment_template.format(project_name=project_name),
            "",
            "## Goal",
            _escape_block(test_case.objective or test_case.title),
            "",
            "## Preconditions",
        ]
        preconditions = test_case.preconditions or [
            "API base URL, auth, and required data are configured before execution."
        ]
        lines.extend(f"- {_escape_line(item)}" for item in preconditions)
        lines.extend(
            [
                "",
                "## Notes",
                *(_escape_line(item) for item in notes),
                "",
                "## Steps",
                "",
                "### Step 1",
                "Type: api",
                f"Name: {_escape_line(test_case.title)}",
                f"Method: {method}",
                f"Path: {endpoint_path}",
            ]
        )
        if request_headers:
            lines.extend(
                [
                    "Headers:",
                    "```json",
                    _json_block(request_headers),
                    "```",
                ]
            )
        if request_params:
            lines.extend(
                [
                    "Params:",
                    "```json",
                    _json_block(request_params),
                    "```",
                ]
            )
        if request_body is not None:
            lines.extend(
                [
                    "Body:",
                    "```json",
                    _json_block(request_body),
                    "```",
                ]
            )
        if capture_rules:
            lines.extend(
                [
                    "Capture:",
                    *(f"- {_escape_line(item)}" for item in capture_rules),
                ]
            )
        lines.append("Expected:")
        lines.extend(f"- {_escape_line(item)}" for item in expected_results)
        if db_verification is not None:
            db_name = db_verification.name.strip() or f"{test_case.title} persisted-state verification"
            lines.extend(
                [
                    "",
                    "### Step 2",
                    "Type: db",
                    f"Name: {_escape_line(db_name)}",
                    "SQL:",
                    "```sql",
                    db_verification.sql.strip(),
                    "```",
                    "Params:",
                    "```json",
                    _json_block(db_verification.params),
                    "```",
                ]
            )
            if db_verification.capture:
                lines.extend(
                    [
                        "Capture:",
                        *(f"- {_escape_line(item)}" for item in db_verification.capture),
                    ]
                )
            lines.append("Expected:")
            lines.extend(f"- {_escape_line(item)}" for item in db_verification.expected_outcomes)
        lines.extend(
            [
                "",
                "## Final expectations",
                "- Draft parses successfully as scenario markdown.",
                (
                    "- Operator reviews missing payloads, headers, and environment data before execution."
                    if test_case.expected_results
                    else "- Operator reviews missing payloads, headers, assertions, and environment data before execution."
                ),
                "",
                "## Report output",
                f"artifacts/agent/{project_name}-{_slugify(test_case.case_id)}-draft-report.md",
                "Summary:",
                *(_escape_line(item) for item in typed_gap_summary),
                "",
            ]
        )
        return "\n".join(lines)

    def _render_workflow_markdown(
        self,
        plan: NormalizedTestPlan,
        test_case: PlannedTestCase,
        title: str,
    ) -> str:
        project_name = Path(plan.project).name or _slugify(plan.project)
        typed_gap_notes = _typed_gap_notes(test_case)
        typed_gap_summary = _typed_gap_summary_lines(test_case)
        db_verification_required = _test_case_requires_db_verification(test_case)
        db_verification_present = _test_case_has_db_verification(test_case)
        lines = [
            f"# Scenario: {_escape_line(title)}",
            "",
            "## Project",
            plan.project,
            "",
            "## Environment",
            self.environment_template.format(project_name=project_name),
            "",
            "## Goal",
            _escape_block(test_case.objective or test_case.title),
            "",
            "## Preconditions",
        ]
        preconditions = test_case.preconditions or [
            "API base URL, auth, and required data are configured before execution."
        ]
        lines.extend(f"- {_escape_line(item)}" for item in preconditions)
        lines.extend(
            [
                "",
                "## Notes",
                "Generated workflow draft preview only. Do not execute without operator review.",
                f"Workflow step count: {len(test_case.workflow_steps)}.",
                f"DB verification required: {'yes' if db_verification_required else 'no'}.",
            ]
        )
        if db_verification_required and not db_verification_present:
            lines.append("Persisted-state verification is required for this workflow but is not authored yet.")
        for outcome in test_case.observable_outcomes:
            lines.append(f"Observable outcome: {outcome}")
        for question in test_case.open_questions:
            lines.append(f"Open question: {question}")
        for assumption in test_case.assumptions:
            lines.append(f"Assumption: {assumption}")
        lines.extend(_escape_line(item) for item in typed_gap_notes)
        lines.extend(["", "## Steps", ""])

        for step_number, workflow_step in enumerate(test_case.workflow_steps, start=1):
            lines.extend(_render_workflow_step_block(step_number, workflow_step, test_case))
            lines.append("")

        lines.extend(
            [
                "## Final expectations",
                "- Draft parses successfully as scenario markdown.",
            ]
        )
        final_expectations = test_case.expected_results or [
            "Operator reviews workflow assertions and environment data before execution."
        ]
        lines.extend(f"- {_escape_line(item)}" for item in final_expectations)
        lines.extend(
            [
                "",
                "## Report output",
                f"artifacts/agent/{project_name}-{_slugify(test_case.case_id)}-draft-report.md",
                "Summary:",
                *(_escape_line(item) for item in typed_gap_summary),
                "",
            ]
        )
        return "\n".join(lines)


def _supported_api_hint(test_case: PlannedTestCase) -> dict[str, Any] | None:
    route_hint = _route_hint_support(test_case)
    if route_hint is not None:
        return route_hint

    planned_route = _planned_route_support(test_case)
    if planned_route is not None:
        return planned_route
    return None


def _route_hint_support(test_case: PlannedTestCase) -> dict[str, Any] | None:
    readiness = _case_support_readiness(test_case)
    if readiness not in {"route_resolved", "evidence_supported"}:
        return None
    route_hints = [
        hint
        for hint in _case_support_route_hints(test_case)
        if hint.get("endpoint_path") and hint.get("http_method")
    ]
    if not route_hints:
        return None

    unique_pairs = {
        (str(hint["endpoint_path"]), str(hint["http_method"]).upper())
        for hint in route_hints
    }
    if len(unique_pairs) != 1:
        return None

    hint = dict(route_hints[0])
    confidence = str(hint.get("confidence", ""))
    if confidence == "weak_inference":
        return None
    endpoint_path = str(hint["endpoint_path"])
    return {
        **hint,
        "http_method": str(hint["http_method"]).upper(),
        "route_source": "route_hints",
        "readiness": readiness,
        "path_shape": _path_shape(endpoint_path),
    }


def _planned_route_support(test_case: PlannedTestCase) -> dict[str, Any] | None:
    planned_route = test_case.planned_route
    if planned_route is None:
        return None
    endpoint_path = planned_route.endpoint_path.strip()
    http_method = planned_route.http_method.strip().upper()
    if not endpoint_path or not http_method:
        return None
    return {
        "endpoint_path": endpoint_path,
        "http_method": http_method,
        "path_kind": planned_route.path_kind,
        "route_source": "planned_route",
        "readiness": str(test_case.metadata.get("readiness", "")) or "route_resolved",
        "path_shape": planned_route.path_kind or _path_shape(endpoint_path),
        "planned_route_source": planned_route.source,
    }


def _render_diagnostics(test_case: PlannedTestCase, support: dict[str, Any]) -> list[GenerationDiagnostic]:
    diagnostics = [
        GenerationDiagnostic(
            code="route_used_for_rendering",
            message="Scenario draft rendering used an authored route binding.",
            severity=DiagnosticSeverity.INFO,
            source_ref=test_case.case_id,
            details={
                "endpoint_path": support.get("endpoint_path"),
                "http_method": support.get("http_method"),
            },
        ),
    ]
    if support.get("route_source") == "route_hints":
        diagnostics.append(
            GenerationDiagnostic(
                code="rendering_based_on_route_hints",
                message="Scenario draft rendering used route_hints metadata as the primary route source.",
                severity=DiagnosticSeverity.INFO,
                source_ref=test_case.case_id,
            )
        )
    if support.get("route_source") == "planned_route":
        diagnostics.append(
            GenerationDiagnostic(
                code="rendering_based_on_planned_route",
                message="Scenario draft rendering used agent-authored planned_route as the primary route source.",
                severity=DiagnosticSeverity.INFO,
                source_ref=test_case.case_id,
            )
        )
    diagnostics.append(
        GenerationDiagnostic(
            code="rendered_with_partial_information",
            message=(
                "Scenario draft was rendered without inferred payloads or auth."
                if test_case.expected_results
                else "Scenario draft was rendered without inferred payloads, auth, or assertions."
            ),
            severity=DiagnosticSeverity.INFO,
            source_ref=test_case.case_id,
        )
    )
    return diagnostics


def _unsupported_reason_code(test_case: PlannedTestCase) -> str:
    readiness = _case_support_readiness(test_case)
    route_hints = [
        hint
        for hint in _case_support_route_hints(test_case)
        if hint.get("endpoint_path") and hint.get("http_method")
    ]
    if route_hints:
        unique_pairs = {
            (str(hint["endpoint_path"]), str(hint["http_method"]).upper())
            for hint in route_hints
        }
        if len(unique_pairs) > 1:
            return "ambiguous_route_mapping"
        if readiness not in {"route_resolved", "evidence_supported"}:
            return "route_not_ready_for_rendering"
        if any(str(hint.get("confidence", "")) == "weak_inference" for hint in route_hints):
            return "low_confidence_route_evidence"
    if test_case.planned_route is not None:
        planned_method = test_case.planned_route.http_method.strip()
        planned_path = test_case.planned_route.endpoint_path.strip()
        if not planned_method or not planned_path:
            return "planned_route_incomplete"
    return "missing_planned_route"


def _unsupported_reason_message(reason_code: str) -> str:
    messages = {
        "ambiguous_route_mapping": "Scenario draft rendering requires one unambiguous route binding.",
        "route_not_ready_for_rendering": "Scenario draft rendering requires route_hints to be marked ready before use.",
        "low_confidence_route_evidence": "Scenario draft rendering does not use low-confidence route metadata.",
        "planned_route_incomplete": "Scenario draft rendering requires both endpoint path and HTTP method in planned_route.",
        "missing_planned_route": "Scenario draft rendering requires an authored endpoint path and HTTP method.",
    }
    return messages.get(reason_code, messages["missing_planned_route"])


def _path_shape(path: str) -> str:
    return "item" if re.search(r"\{[^}]+\}", path) else "collection"


def _workflow_steps_renderable(test_case: PlannedTestCase) -> bool:
    if not test_case.workflow_steps:
        return False
    for workflow_step in test_case.workflow_steps:
        step_kind = workflow_step.step_type.strip().lower()
        if step_kind == "api":
            route = workflow_step.route
            if route is None or not route.http_method.strip() or not route.endpoint_path.strip():
                return False
        elif step_kind == "db":
            if not workflow_step.sql.strip():
                return False
        else:
            return False
    return True


def _workflow_route_binding(test_case: PlannedTestCase) -> dict[str, Any] | None:
    for workflow_step in test_case.workflow_steps:
        if workflow_step.step_type.strip().lower() != "api" or workflow_step.route is None:
            continue
        endpoint_path = workflow_step.route.endpoint_path.strip()
        http_method = workflow_step.route.http_method.strip().upper()
        if not endpoint_path or not http_method:
            continue
        return {
            "endpoint_path": endpoint_path,
            "http_method": http_method,
            "route_source": "workflow_steps",
            "readiness": "workflow_authored",
            "path_shape": workflow_step.route.path_kind or _path_shape(endpoint_path),
        }
    return None


def _workflow_route_bindings(test_case: PlannedTestCase) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for workflow_step in test_case.workflow_steps:
        if workflow_step.step_type.strip().lower() != "api" or workflow_step.route is None:
            continue
        endpoint_path = workflow_step.route.endpoint_path.strip()
        http_method = workflow_step.route.http_method.strip().upper()
        if not endpoint_path or not http_method:
            continue
        bindings.append(
            {
                "endpoint_path": endpoint_path,
                "http_method": http_method,
                "route_source": "workflow_steps",
                "readiness": "workflow_authored",
                "path_shape": workflow_step.route.path_kind or _path_shape(endpoint_path),
                "title": workflow_step.title,
            }
        )
    return bindings


def _db_only_workflow_binding(test_case: PlannedTestCase) -> dict[str, Any] | None:
    if not test_case.workflow_steps:
        return None
    if any(step.step_type.strip().lower() == "api" for step in test_case.workflow_steps):
        return None
    return {
        "route_source": "workflow_db_only",
        "readiness": "workflow_authored",
        "path_shape": "db_only",
    }


def _test_case_requires_db_verification(test_case: PlannedTestCase) -> bool:
    if test_case.requires_db_verification:
        return True
    return _workflow_requires_persisted_state_verification(test_case)


def _test_case_has_db_verification(test_case: PlannedTestCase) -> bool:
    return test_case.db_verification is not None or any(
        workflow_step.step_type.strip().lower() == "db" and workflow_step.sql.strip()
        for workflow_step in test_case.workflow_steps
    )


def _test_case_has_authored_expectations(test_case: PlannedTestCase) -> bool:
    if test_case.expected_results:
        return True
    if test_case.db_verification is not None and test_case.db_verification.expected_outcomes:
        return True
    return any(workflow_step.expected_outcomes for workflow_step in test_case.workflow_steps)


def _test_case_has_capture_rules(test_case: PlannedTestCase) -> bool:
    if test_case.capture:
        return True
    if test_case.db_verification is not None and test_case.db_verification.capture:
        return True
    return any(workflow_step.capture for workflow_step in test_case.workflow_steps)


def _workflow_requires_persisted_state_verification(test_case: PlannedTestCase) -> bool:
    if not test_case.workflow_steps:
        return False
    case_level_success = _expectations_indicate_success(test_case.expected_results)
    for workflow_step in test_case.workflow_steps:
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


def _expectations_indicate_success(expectations: list[str]) -> bool:
    for expectation in expectations:
        normalized = expectation.strip().upper()
        if normalized.startswith("HTTP 2"):
            return True
    return False


def _render_workflow_step_block(
    step_number: int,
    workflow_step: PlannedWorkflowStep,
    test_case: PlannedTestCase,
) -> list[str]:
    title = workflow_step.title.strip() or f"Workflow step {step_number}"
    step_kind = workflow_step.step_type.strip().lower()
    if step_kind == "api":
        route = workflow_step.route
        assert route is not None
        lines = [
            f"### Step {step_number}",
            "Type: api",
            f"Name: {_escape_line(title)}",
            f"Method: {route.http_method.strip().upper()}",
            f"Path: {route.endpoint_path.strip()}",
        ]
        if workflow_step.request_headers:
            lines.extend(["Headers:", "```json", _json_block(workflow_step.request_headers), "```"])
        if workflow_step.request_params:
            lines.extend(["Params:", "```json", _json_block(workflow_step.request_params), "```"])
        if workflow_step.request_body is not None:
            lines.extend(["Body:", "```json", _json_block(workflow_step.request_body), "```"])
        if workflow_step.capture:
            lines.extend(["Capture:", *(f"- {_escape_line(item)}" for item in workflow_step.capture)])
        if workflow_step.expected_outcomes:
            lines.append("Expected:")
            lines.extend(f"- {_escape_line(item)}" for item in workflow_step.expected_outcomes)
        elif test_case.expected_results:
            lines.append("Expected:")
            lines.extend(f"- {_escape_line(item)}" for item in test_case.expected_results)
        return lines

    lines = [
        f"### Step {step_number}",
        "Type: db",
        f"Name: {_escape_line(title)}",
        "SQL:",
        "```sql",
        workflow_step.sql.strip(),
        "```",
        "Params:",
        "```json",
        _json_block(workflow_step.params),
        "```",
    ]
    if workflow_step.capture:
        lines.extend(["Capture:", *(f"- {_escape_line(item)}" for item in workflow_step.capture)])
    if workflow_step.expected_outcomes:
        lines.append("Expected:")
        lines.extend(f"- {_escape_line(item)}" for item in workflow_step.expected_outcomes)
    return lines


def _case_support_readiness(test_case: PlannedTestCase) -> str:
    if test_case.support is not None and test_case.support.readiness:
        return test_case.support.readiness
    return str(test_case.metadata.get("readiness", ""))


def _case_support_route_hints(test_case: PlannedTestCase) -> list[dict[str, Any]]:
    if test_case.support is not None and test_case.support.route_hints:
        return [hint.to_dict() for hint in test_case.support.route_hints]
    return [
        dict(hint)
        for hint in test_case.metadata.get("route_hints", [])
        if isinstance(hint, dict)
    ]


def _draft_case_support(test_case: PlannedTestCase, support: dict[str, Any]) -> dict[str, Any]:
    if test_case.support is not None:
        return test_case.support.to_dict()
    endpoint_path = str(support.get("endpoint_path") or "")
    http_method = str(support.get("http_method") or "")
    if not endpoint_path or not http_method:
        return {}
    route_hint = RouteSupportHint(
        fact_id=str(support.get("fact_id") or ""),
        endpoint_path=endpoint_path,
        http_method=http_method,
        confidence=str(support.get("confidence") or ""),
        handler_name=str(support.get("handler_name") or ""),
        controller_name=str(support.get("controller_name") or ""),
        framework_hint=str(support.get("framework_hint") or ""),
        match_reasons=[str(item) for item in support.get("match_reasons", [])],
        route_source=str(support.get("route_source") or ""),
    )
    return {
        "readiness": str(support.get("readiness") or ""),
        "route_hints": [route_hint.to_dict()],
    }


def _json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _has_auth_header_signal(headers: dict[str, Any]) -> bool:
    for raw_name in headers:
        name = str(raw_name).strip().lower()
        if name == "authorization":
            return True
        if "token" in name or "api-key" in name or "apikey" in name or name == "cookie":
            return True
    return False


def _typed_gap_notes(test_case: PlannedTestCase) -> list[str]:
    return [format_case_gap_note(gap) for gap in test_case.gaps if gap.message or gap.category]


def _typed_gap_summary_lines(test_case: PlannedTestCase) -> list[str]:
    if not test_case.gaps:
        return ["- No typed unresolved intent was captured upstream."]
    categories: list[str] = []
    lines = [f"- Typed unresolved intent count: {len(test_case.gaps)}"]
    for gap in test_case.gaps:
        code, _ = project_case_gap(gap)
        if code:
            categories.append(gap.category.value)
    if categories:
        lines.append(f"- Typed unresolved intent categories: {', '.join(_dedupe_preserve_order(categories))}")
    lines.extend(f"- {format_case_gap_note(gap)}" for gap in test_case.gaps)
    return lines


def _blocking_gap_checks(test_case: PlannedTestCase) -> list[UnsupportedCheck]:
    checks: list[UnsupportedCheck] = []
    seen_codes: set[str] = set()
    for gap in test_case.gaps:
        code, message = project_case_gap(gap)
        if not code or code not in EXECUTION_BLOCKING_GAP_CODES or code in seen_codes:
            continue
        seen_codes.add(code)
        checks.append(
            UnsupportedCheck(
                case_id=test_case.case_id,
                reason_code=code,
                message=message or "Execution-blocking authored gap remains unresolved.",
                details={"gap_category": gap.category.value, "gap_source": gap.source},
            )
        )
    return checks


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug.lower() or "scenario-draft"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _escape_line(value: str) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _escape_block(value: str) -> str:
    return "\n".join(_escape_line(line) for line in str(value).splitlines()).strip()
