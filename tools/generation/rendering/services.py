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
                check = UnsupportedCheck(
                    case_id=test_case.case_id,
                    reason_code="missing_endpoint_evidence",
                    message="Scenario draft rendering requires endpoint path and HTTP method evidence.",
                    details={
                        "has_evidence_hints": bool(test_case.metadata.get("evidence_hints")),
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
                        "evidence_hint": support,
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
        expected_results = test_case.expected_results or [
            "HTTP response is received and must be reviewed before execution."
        ]
        notes = [
            "Generated draft preview only. Do not execute without operator review.",
            "No request body, auth headers, DB checks, or concrete assertions were invented.",
        ]
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
    for raw_hint in test_case.metadata.get("evidence_hints", []):
        if not isinstance(raw_hint, dict):
            continue
        fields = raw_hint.get("applied_fields")
        if not isinstance(fields, dict):
            continue
        endpoint_path = fields.get("endpoint_path")
        http_method = fields.get("http_method")
        if endpoint_path and http_method:
            return dict(fields)
    return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug.lower() or "scenario-draft"


def _escape_line(value: str) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _escape_block(value: str) -> str:
    return "\n".join(_escape_line(line) for line in str(value).splitlines()).strip()
