"""Deterministic rendering of normalized plans into non-executed scenario drafts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.generation.domain.models import (
    DiagnosticSeverity,
    GenerationDiagnostic,
    GenerationRunContext,
    NormalizedTestPlan,
    PlannedTestCase,
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
    """Render parser-valid markdown previews from evidence-supported cases."""

    environment_template: str = "env/{project_name}.env"

    def render(self, plan: NormalizedTestPlan) -> ScenarioRenderResult:
        drafts: list[ScenarioDraft] = []
        deferred_items: list[DeferredScenarioItem] = []
        unsupported_checks: list[UnsupportedCheck] = []
        diagnostics: list[GenerationDiagnostic] = []

        for test_case in plan.test_cases:
            support = _supported_api_hint(test_case)
            if support is None:
                reason_code = _unsupported_reason_code(test_case)
                check = UnsupportedCheck(
                    case_id=test_case.case_id,
                    reason_code=reason_code,
                    message=_unsupported_reason_message(reason_code),
                    details={
                        "has_route_hints": bool(test_case.metadata.get("route_hints")),
                        "has_evidence_hints": bool(test_case.metadata.get("evidence_hints")),
                        "readiness": str(test_case.metadata.get("readiness", "")),
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
                        message="Planned case lacks safe executable endpoint evidence for draft rendering.",
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
        route_source = str(support.get("route_source") or "evidence_hints")
        route_readiness = str(support.get("readiness") or "")
        expected_results = test_case.expected_results or [
            "HTTP response is received and must be reviewed before execution."
        ]
        notes = [
            "Generated draft preview only. Do not execute without operator review.",
            "Route resolved from code facts.",
            f"Route source: {route_source}.",
            "Request body not inferred.",
            "Auth headers not inferred.",
            "Assertions not generated.",
            "No DB checks, captures, or concrete payloads were invented.",
        ]
        if route_readiness:
            notes.append(f"Case readiness: {route_readiness}.")
        if support.get("handler_name"):
            notes.append(f"Handler: {support['handler_name']}.")
        if support.get("controller_name"):
            notes.append(f"Controller: {support['controller_name']}.")
        if support.get("path_shape"):
            notes.append(f"Route shape: {support['path_shape']}.")
        for question in test_case.open_questions:
            notes.append(f"Open question: {question}")
        for assumption in test_case.assumptions:
            notes.append(f"Assumption: {assumption}")

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
                "Expected:",
            ]
        )
        lines.extend(f"- {_escape_line(item)}" for item in expected_results)
        lines.extend(
            [
                "",
                "## Final expectations",
                "- Draft parses successfully as scenario markdown.",
                "- Operator reviews missing payloads, headers, assertions, and environment data before execution.",
                "",
                "## Report output",
                f"artifacts/agent/{project_name}-{_slugify(test_case.case_id)}-draft-report.md",
                "",
            ]
        )
        return "\n".join(lines)


def _supported_api_hint(test_case: PlannedTestCase) -> dict[str, Any] | None:
    readiness = str(test_case.metadata.get("readiness", ""))
    if readiness not in {"route_resolved", "evidence_supported"}:
        return None

    route_hint = _route_hint_support(test_case)
    if route_hint is not None:
        return route_hint

    for raw_hint in test_case.metadata.get("evidence_hints", []):
        if not isinstance(raw_hint, dict):
            continue
        fields = raw_hint.get("applied_fields")
        if not isinstance(fields, dict):
            continue
        endpoint_path = fields.get("endpoint_path")
        http_method = fields.get("http_method")
        if endpoint_path and http_method:
            return {
                **dict(fields),
                "route_source": "evidence_hints",
                "readiness": readiness,
                "path_shape": _path_shape(str(endpoint_path)),
            }
    return None


def _route_hint_support(test_case: PlannedTestCase) -> dict[str, Any] | None:
    route_hints = [
        hint
        for hint in test_case.metadata.get("route_hints", [])
        if isinstance(hint, dict) and hint.get("endpoint_path") and hint.get("http_method")
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
        "readiness": str(test_case.metadata.get("readiness", "")),
        "path_shape": _path_shape(endpoint_path),
    }


def _render_diagnostics(test_case: PlannedTestCase, support: dict[str, Any]) -> list[GenerationDiagnostic]:
    diagnostics = [
        GenerationDiagnostic(
            code="route_used_for_rendering",
            message="Scenario draft rendering used resolved route evidence.",
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
                message="Scenario draft rendering used route_hints as the primary route source.",
                severity=DiagnosticSeverity.INFO,
                source_ref=test_case.case_id,
            )
        )
    diagnostics.append(
        GenerationDiagnostic(
            code="rendered_with_partial_information",
            message="Scenario draft was rendered without inferred payloads, auth, or assertions.",
            severity=DiagnosticSeverity.INFO,
            source_ref=test_case.case_id,
        )
    )
    return diagnostics


def _unsupported_reason_code(test_case: PlannedTestCase) -> str:
    readiness = str(test_case.metadata.get("readiness", ""))
    route_hints = [
        hint
        for hint in test_case.metadata.get("route_hints", [])
        if isinstance(hint, dict) and hint.get("endpoint_path") and hint.get("http_method")
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
    return "missing_endpoint_evidence"


def _unsupported_reason_message(reason_code: str) -> str:
    messages = {
        "ambiguous_route_mapping": "Scenario draft rendering requires one unambiguous route binding.",
        "route_not_ready_for_rendering": "Scenario draft rendering requires route_resolved or evidence_supported readiness.",
        "low_confidence_route_evidence": "Scenario draft rendering does not use low-confidence route evidence.",
        "missing_endpoint_evidence": "Scenario draft rendering requires endpoint path and HTTP method evidence.",
    }
    return messages.get(reason_code, messages["missing_endpoint_evidence"])


def _path_shape(path: str) -> str:
    return "item" if re.search(r"\{[^}]+\}", path) else "collection"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug.lower() or "scenario-draft"


def _escape_line(value: str) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _escape_block(value: str) -> str:
    return "\n".join(_escape_line(line) for line in str(value).splitlines()).strip()
