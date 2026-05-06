"""Agent-facing CLI adapter for test-plan generation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.cli_guard import bootstrap_workspace_cli


_WORKSPACE_ROOT = bootstrap_workspace_cli(__file__, payload_kind="generation")

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


WorkflowRunner = Callable[[argparse.Namespace], dict[str, Any]]
WorkflowRoute = tuple[tuple[str, ...], str, WorkflowRunner]

WORKFLOW_ROUTES: tuple[WorkflowRoute, ...] = (
    (("init_authoring_plan",), "authoring", run_init_authoring_plan),
    (("init_entity_inventory",), "authoring", run_init_entity_inventory),
    (("init_operation_inventory",), "authoring", run_init_operation_inventory),
    (("init_agent_plan",), "authoring", run_init_agent_plan),
    (("validate_agent_plan",), "authoring", run_validate_agent_plan),
    (("validate_entity_inventory",), "authoring", run_validate_entity_inventory),
    (("validate_operation_inventory",), "authoring", run_validate_operation_inventory),
    (("sync_authoring_plan",), "authoring", run_sync_authoring_plan),
    (("validate_authoring_bundle",), "authoring", run_validate_authoring_bundle),
    (("validate_authoring_plan",), "authoring", run_validate_authoring_plan),
    (("compile_authoring_plan",), "authoring", run_compile_authoring_plan),
    (("review_drafts",), "review", run_review),
    (("promote_draft", "promote_all_drafts"), "promotion", run_promotion),
    (("list_patch_templates",), "template", run_list_patch_templates),
    (("show_patch_template",), "template", run_show_patch_template),
    (("validate_scenario",), "revalidation", run_validate_scenario),
    (("validate_scenario_dir",), "revalidation_dir", run_validate_scenario_dir),
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
    selected_route = _selected_route(args)
    if selected_route is not None:
        return selected_route[2](args)
    return run_generation(args)


def _workflow_name(args: argparse.Namespace) -> str:
    selected_route = _selected_route(args)
    return "generation" if selected_route is None else selected_route[1]


def _selected_route(args: argparse.Namespace) -> WorkflowRoute | None:
    for route in WORKFLOW_ROUTES:
        flags, _, _ = route
        if any(getattr(args, flag) for flag in flags):
            return route
    return None


if __name__ == "__main__":
    raise SystemExit(main())
