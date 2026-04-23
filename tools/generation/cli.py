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
from tools.generation.evidence.models import CodeFactsScope


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.generation.cli",
        description="Generate a NormalizedTestPlan, optionally enriched by explicit scoped code facts.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prose", help="Inline prose source for test-plan generation.")
    source.add_argument("--source-file", help="Path to a prose source file.")
    parser.add_argument("--source-id", required=True, help="Stable source id for this generation run.")
    parser.add_argument("--project", required=True, help="Project identifier stored in generation contracts.")
    parser.add_argument("--name", default="", help="Optional human-readable source name.")
    parser.add_argument("--workspace-root", default=".", help="Workspace root for artifact persistence.")
    parser.add_argument("--no-persist", action="store_true", help="Do not persist generation artifacts.")

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
        help="File glob used inside scoped directories. Defaults to *.py.",
    )
    parser.add_argument(
        "--evidence-max-files",
        type=int,
        default=20,
        help="Maximum files to inspect inside explicit evidence scope.",
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
            file_patterns=args.evidence_pattern or ["*.py"],
            max_files=args.evidence_max_files,
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
        ),
    )


def run_generation(args: argparse.Namespace) -> dict[str, Any]:
    request = build_request(args)
    result = GenerateTestPlanUseCase().execute(request)
    return summarize_result(result)


def summarize_result(result: Any) -> dict[str, Any]:
    evidence_bundle = result.evidence_bundle
    enrichment_result = result.enrichment_result
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


class GenerationCliInputError(ValueError):
    def __init__(self, diagnostics: list[GenerationDiagnostic]) -> None:
        super().__init__("Invalid generation CLI input.")
        self.diagnostics = diagnostics


def _adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
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
