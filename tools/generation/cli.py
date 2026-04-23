"""Agent-facing CLI adapter for test-plan generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.application import GenerateTestPlanOptions, GenerateTestPlanRequest
from tools.generation.application.use_cases import GenerateTestPlanUseCase
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic, GenerationSourceInput
from tools.generation.evidence.models import CodeFactsScope, TargetStack
from tools.generation.review import (
    ScenarioDraftPromotionService,
    ScenarioDraftReviewService,
    ScenarioPromotionRequest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.generation.cli",
        description="Generate a NormalizedTestPlan, optionally enriched by explicit scoped code facts.",
    )
    workflow = parser.add_mutually_exclusive_group()
    workflow.add_argument("--review-drafts", action="store_true", help="Review generated drafts for a run id.")
    workflow.add_argument("--promote-draft", action="store_true", help="Promote one selected draft into scenarios/.")

    source = parser.add_mutually_exclusive_group()
    source.add_argument("--prose", help="Inline prose source for test-plan generation.")
    source.add_argument("--source-file", help="Path to a prose source file.")
    parser.add_argument("--source-id", help="Stable source id for this generation run.")
    parser.add_argument("--project", help="Project identifier stored in generation contracts.")
    parser.add_argument("--name", default="", help="Optional human-readable source name.")
    parser.add_argument("--workspace-root", default=".", help="Workspace root for artifact persistence.")
    parser.add_argument("--no-persist", action="store_true", help="Do not persist generation artifacts.")
    parser.add_argument("--run-id", help="Generation run id for review or promotion.")
    parser.add_argument("--draft-id", help="Draft id selected for promotion.")
    parser.add_argument("--allow-invalid", action="store_true", help="Allow promotion of parser-invalid drafts.")
    parser.add_argument(
        "--target-dir",
        default="scenarios/generated",
        help="Promotion target directory under scenarios/.",
    )

    parser.add_argument("--project-path", help="Explicit target project path for code facts extraction.")
    parser.add_argument(
        "--evidence-scope-id",
        default="api",
        help="Explicit scope id for code facts extraction.",
    )
    parser.add_argument(
        "--evidence-scope-path",
        action="append",
        default=[],
        help="Explicit scoped file or directory path for code facts extraction. Repeat for multiple paths.",
    )
    parser.add_argument(
        "--evidence-pattern",
        action="append",
        default=[],
        help="File glob used inside scoped directories. Defaults to *.py and *.java.",
    )
    parser.add_argument(
        "--evidence-max-files",
        type=int,
        default=20,
        help="Maximum files to inspect inside explicit evidence scope.",
    )
    parser.add_argument(
        "--stack-hint",
        choices=[stack.value for stack in TargetStack],
        help="Optional explicit stack hint for code facts extraction.",
    )
    parser.add_argument(
        "--collect-code-facts",
        action="store_true",
        help="Collect typed code facts from the explicit evidence scope.",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Apply collected evidence to the NormalizedTestPlan.",
    )
    parser.add_argument(
        "--render-drafts",
        action="store_true",
        help="Render non-executed markdown scenario drafts and parser-validate them.",
    )
    return parser


def build_request(args: argparse.Namespace) -> GenerateTestPlanRequest:
    diagnostics = _adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)

    source_input = GenerationSourceInput(
        source_id=args.source_id,
        project=args.project,
        name=args.name,
        content=args.prose or "",
        source_path=Path(args.source_file) if args.source_file else None,
    )
    evidence_scope = None
    if args.collect_code_facts:
        evidence_scope = CodeFactsScope(
            scope_id=args.evidence_scope_id,
            paths=[Path(item) for item in args.evidence_scope_path],
            file_patterns=args.evidence_pattern or ["*.py", "*.java"],
            max_files=args.evidence_max_files,
            stack_hint=None if not args.stack_hint else TargetStack(args.stack_hint),
        )

    return GenerateTestPlanRequest(
        source_input=source_input,
        workspace_root=Path(args.workspace_root),
        project_path=Path(args.project_path) if args.project_path else None,
        evidence_scope=evidence_scope,
        options=GenerateTestPlanOptions(
            persist_artifacts=not args.no_persist,
            collect_code_facts=args.collect_code_facts,
            enrichment_enabled=args.enrich,
            render_scenario_drafts=args.render_drafts,
        ),
    )


def run_generation(args: argparse.Namespace) -> dict[str, Any]:
    request = build_request(args)
    result = GenerateTestPlanUseCase().execute(request)
    return summarize_result(result)


def summarize_result(result: Any) -> dict[str, Any]:
    evidence_bundle = result.evidence_bundle
    enrichment_result = result.enrichment_result
    scenario_render_result = result.scenario_render_result
    return to_json_safe(
        {
            "status": result.final_status.value,
            "message": result.message,
            "run_id": result.run_context.run_id,
            "source_id": result.run_context.source_id,
            "project": result.run_context.project,
            "test_case_count": len(result.normalized_plan.test_cases),
            "code_facts": result.details.get("code_facts", "not_requested"),
            "evidence_fact_count": len(evidence_bundle.facts) if evidence_bundle else 0,
            "enrichment": result.details.get("enrichment", "not_requested"),
            "applied_evidence_count": (
                len(enrichment_result.applied_evidence) if enrichment_result else 0
            ),
            "unapplied_evidence_count": (
                len(enrichment_result.unapplied_evidence) if enrichment_result else 0
            ),
            "scenario_rendering": result.details.get("scenario_rendering", "not_requested"),
            "scenario_draft_count": (
                len(scenario_render_result.draft_set.drafts) if scenario_render_result else 0
            ),
            "scenario_deferred_count": (
                len(scenario_render_result.draft_set.deferred_items) if scenario_render_result else 0
            ),
            "scenario_parse_valid_count": (
                sum(1 for item in scenario_render_result.validation_results if item.parse_valid)
                if scenario_render_result
                else 0
            ),
            "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
            "evidence_diagnostics": (
                [diagnostic.to_dict() for diagnostic in evidence_bundle.diagnostics]
                if evidence_bundle
                else []
            ),
            "unapplied_evidence": (
                [reason.to_dict() for reason in enrichment_result.unapplied_evidence]
                if enrichment_result
                else []
            ),
            "artifact_paths": result.artifact_paths,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.review_drafts:
            payload = run_review(args)
        elif args.promote_draft:
            payload = run_promotion(args)
        else:
            payload = run_generation(args)
    except GenerationCliInputError as exc:
        payload = _error_payload(exc.diagnostics)
        _print_payload(payload)
        return 1
    except Exception as exc:  # noqa: BLE001
        payload = _error_payload(
            [
                GenerationDiagnostic(
                    code="generation_adapter_error",
                    message=f"Generation adapter failed: {exc}",
                    severity=DiagnosticSeverity.ERROR,
                )
            ]
        )
        _print_payload(payload)
        return 1

    _print_payload(payload)
    return 0 if payload["status"] == StepStatus.PASS.value else 1


def run_review(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _review_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    review_set = ScenarioDraftReviewService().review(
        str(args.run_id),
        workspace_root=Path(args.workspace_root),
    )
    return to_json_safe(
        {
            "status": StepStatus.PASS.value,
            "run_id": review_set.run_id,
            "source_id": review_set.source_id,
            "artifact_dir": review_set.artifact_dir,
            "draft_count": len(review_set.items),
            "valid_draft_count": sum(1 for item in review_set.items if item.parse_status.value == "valid"),
            "invalid_draft_count": sum(1 for item in review_set.items if item.parse_status.value == "invalid"),
            "review_set": review_set.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in review_set.diagnostics],
        }
    )


def run_promotion(args: argparse.Namespace) -> dict[str, Any]:
    diagnostics = _promotion_adapter_diagnostics(args)
    if diagnostics:
        raise GenerationCliInputError(diagnostics)
    result = ScenarioDraftPromotionService().promote(
        ScenarioPromotionRequest(
            run_id=str(args.run_id),
            draft_id=str(args.draft_id),
            workspace_root=Path(args.workspace_root),
            target_dir=Path(args.target_dir),
            allow_invalid=args.allow_invalid,
        )
    )
    return to_json_safe(
        {
            "status": result.status.value,
            "run_id": result.run_id,
            "draft_id": result.draft_id,
            "source_path": result.source_path,
            "target_path": result.target_path,
            "promotion_result_path": result.promotion_result_path,
            "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
        }
    )


class GenerationCliInputError(ValueError):
    def __init__(self, diagnostics: list[GenerationDiagnostic]) -> None:
        super().__init__("Invalid generation CLI input.")
        self.diagnostics = diagnostics


def _adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.prose and not args.source_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_source",
                message="Generation requires exactly one of --prose or --source-file.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if not args.source_id:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_source_id",
                message="Generation requires --source-id.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    if not args.project:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_project",
                message="Generation requires --project.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.enrich and not args.collect_code_facts:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_enrichment_requires_code_facts",
                message="--enrich requires --collect-code-facts and an explicit evidence scope.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.collect_code_facts and not args.project_path:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_code_facts_require_project_path",
                message="Code facts collection requires explicit --project-path.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.collect_code_facts and not args.evidence_scope_path:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_code_facts_require_explicit_scope",
                message="Code facts collection requires at least one --evidence-scope-path.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.evidence_max_files < 1:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_invalid_evidence_max_files",
                message="--evidence-max-files must be at least 1.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.render_drafts and args.no_persist:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_render_drafts_requires_persistence",
                message="--render-drafts requires artifact persistence; remove --no-persist.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    return diagnostics


def _review_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.run_id:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_review_requires_run_id",
            message="--review-drafts requires --run-id.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]


def _promotion_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.run_id:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_promotion_requires_run_id",
                message="--promote-draft requires --run-id.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    if not args.draft_id:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_promotion_requires_draft_id",
                message="--promote-draft requires --draft-id.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.run_id,
            )
        )
    return diagnostics


def _error_payload(diagnostics: list[GenerationDiagnostic]) -> dict[str, Any]:
    return to_json_safe(
        {
            "status": StepStatus.ERROR.value,
            "message": "Generation adapter input was invalid.",
            "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
            "artifact_paths": {},
        }
    )


def _print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
