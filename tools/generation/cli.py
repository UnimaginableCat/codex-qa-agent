"""Agent-facing CLI adapter for test-plan generation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.generation.cli_authoring import (
    run_compile_authoring_plan,
    run_init_agent_plan,
    run_init_authoring_plan,
    run_init_entity_inventory,
    run_init_operation_inventory,
    run_sync_authoring_plan,
    run_validate_agent_plan,
    run_validate_authoring_bundle,
    run_validate_authoring_plan,
    run_validate_entity_inventory,
    run_validate_operation_inventory,
)
from tools.generation.cli_core import GenerationCliInputError
from tools.generation.cli_generation_run import build_request, run_generation, summarize_result
from tools.generation.cli_parser import build_parser
from tools.generation.cli_rendering import _error_payload, _print_payload
from tools.generation.cli_review import (
    run_list_patch_templates,
    run_promotion,
    run_review,
    run_show_patch_template,
    run_validate_scenario,
    run_validate_scenario_dir,
)
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic


AUTHORING_WORKFLOW_FLAGS = (
    "init_authoring_plan",
    "init_entity_inventory",
    "init_operation_inventory",
    "init_agent_plan",
    "validate_agent_plan",
    "validate_entity_inventory",
    "validate_operation_inventory",
    "sync_authoring_plan",
    "validate_authoring_bundle",
    "validate_authoring_plan",
    "compile_authoring_plan",
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = _run_selected_workflow(args)
    except GenerationCliInputError as exc:
        payload = _error_payload(exc.diagnostics)
        _print_payload(payload, output_format=args.output_format, workflow="error")
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
        _print_payload(payload, output_format=args.output_format, workflow="error")
        return 1

    _print_payload(payload, output_format=args.output_format, workflow=_workflow_name(args))
    return 0 if payload["status"] == StepStatus.PASS.value else 1


def _run_selected_workflow(args: argparse.Namespace) -> dict[str, Any]:
    if args.init_authoring_plan:
        return run_init_authoring_plan(args)
    if args.init_entity_inventory:
        return run_init_entity_inventory(args)
    if args.init_operation_inventory:
        return run_init_operation_inventory(args)
    if args.init_agent_plan:
        return run_init_agent_plan(args)
    if args.validate_agent_plan:
        return run_validate_agent_plan(args)
    if args.validate_entity_inventory:
        return run_validate_entity_inventory(args)
    if args.validate_operation_inventory:
        return run_validate_operation_inventory(args)
    if args.sync_authoring_plan:
        return run_sync_authoring_plan(args)
    if args.validate_authoring_bundle:
        return run_validate_authoring_bundle(args)
    if args.validate_authoring_plan:
        return run_validate_authoring_plan(args)
    if args.compile_authoring_plan:
        return run_compile_authoring_plan(args)
    if args.review_drafts:
        return run_review(args)
    if args.promote_draft or args.promote_all_drafts:
        return run_promotion(args)
    if args.list_patch_templates:
        return run_list_patch_templates(args)
    if args.show_patch_template:
        return run_show_patch_template(args)
    if args.validate_scenario:
        return run_validate_scenario(args)
    if args.validate_scenario_dir:
        return run_validate_scenario_dir(args)
    return run_generation(args)


def _workflow_name(args: argparse.Namespace) -> str:
    if any(getattr(args, flag) for flag in AUTHORING_WORKFLOW_FLAGS):
        return "authoring"
    if args.review_drafts:
        return "review"
    if args.promote_draft or args.promote_all_drafts:
        return "promotion"
    if args.list_patch_templates or args.show_patch_template:
        return "template"
    if args.validate_scenario_dir:
        return "revalidation_dir"
    if args.validate_scenario:
        return "revalidation"
    return "generation"


if __name__ == "__main__":
    raise SystemExit(main())
