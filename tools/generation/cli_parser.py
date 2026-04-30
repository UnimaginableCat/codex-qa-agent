"""Support code for the generation CLI adapter."""

from __future__ import annotations

import argparse

from tools.generation.application import GenerationInputMode
from tools.generation.review import DraftEditTargetType


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.generation.cli",
        description="Compile authoring DSL into a NormalizedTestPlan and optionally render markdown draft scenarios.",
    )
    workflow = parser.add_mutually_exclusive_group()
    workflow.add_argument(
        "--init-authoring-plan",
        action="store_true",
        help="Write a scaffolded authoring-plan YAML file into a managed generation bundle.",
    )
    workflow.add_argument(
        "--init-entity-inventory",
        action="store_true",
        help="Write a scaffolded entity-inventory YAML file into a managed generation bundle.",
    )
    workflow.add_argument(
        "--init-operation-inventory",
        action="store_true",
        help="Write a scaffolded operation-inventory YAML file into a managed generation bundle.",
    )
    workflow.add_argument(
        "--init-agent-plan",
        action="store_true",
        help="Write a low-level AgentTestPlanInput template JSON file. Prefer authoring-plan YAML for the normal DSL flow.",
    )
    workflow.add_argument(
        "--validate-agent-plan",
        action="store_true",
        help="Validate a compiled AgentTestPlanInput file without generation.",
    )
    workflow.add_argument(
        "--validate-authoring-plan",
        action="store_true",
        help="Validate a compact authoring-plan file without compile or generation.",
    )
    workflow.add_argument(
        "--sync-authoring-plan",
        action="store_true",
        help="Synchronize authoring-plan scope/entities/operation templates from staged inventories.",
    )
    workflow.add_argument(
        "--validate-authoring-bundle",
        action="store_true",
        help="Validate entity inventory, operation inventory, and authoring plan together for one managed bundle.",
    )
    workflow.add_argument(
        "--validate-entity-inventory",
        action="store_true",
        help="Validate an entity-inventory YAML file without compile or generation.",
    )
    workflow.add_argument(
        "--validate-operation-inventory",
        action="store_true",
        help="Validate an operation-inventory YAML file without compile or generation.",
    )
    workflow.add_argument(
        "--compile-authoring-plan",
        action="store_true",
        help="Compile a compact authoring-plan file into a managed AgentTestPlanInput bundle.",
    )
    workflow.add_argument("--review-drafts", action="store_true", help="Review generated drafts for a run id.")
    workflow.add_argument("--promote-draft", action="store_true", help="Promote one selected draft into scenarios/.")
    workflow.add_argument("--promote-all-drafts", action="store_true", help="Promote all drafts from one run into scenarios/.")
    workflow.add_argument("--list-patch-templates", action="store_true", help="List deterministic draft edit templates.")
    workflow.add_argument("--show-patch-template", action="store_true", help="Show one draft edit template by target type.")
    workflow.add_argument("--validate-scenario", action="store_true", help="Validate one scenario file without execution.")
    workflow.add_argument("--validate-scenario-dir", action="store_true", help="Validate all scenario markdown files in one directory.")

    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--agent-plan-file",
        help="Path to a compiled AgentTestPlanInput JSON file. Prefer --authoring-plan-file for the normal DSL flow.",
    )
    source.add_argument(
        "--authoring-plan-file",
        help="Path to a compact authoring-plan YAML file. This is the preferred DSL input.",
    )
    source.add_argument("--prose", help="Inline prose source for fallback/bootstrap test-plan generation.")
    source.add_argument("--source-file", help="Path to a prose source file.")
    parser.add_argument("--entity-inventory-file", help="Path to an entity-inventory YAML file.")
    parser.add_argument("--operation-inventory-file", help="Path to an operation-inventory YAML file.")
    parser.add_argument(
        "--input-mode",
        choices=[mode.value for mode in GenerationInputMode],
        help="Generation input mode. Defaults to authoring_plan, agent_plan, or prose based on the selected source flag.",
    )
    parser.add_argument("--source-id", help="Stable source id for this generation run.")
    parser.add_argument("--project", help="Project identifier stored in generation contracts.")
    parser.add_argument("--surface", default="", help="Optional surface/controller name used for staged authoring inventories.")
    parser.add_argument("--name", default="", help="Optional human-readable source name.")
    parser.add_argument("--goal", default="", help="Optional goal used when scaffolding a low-level agent plan template.")
    parser.add_argument(
        "--output",
        help="Managed generation root hint for --init-authoring-plan, --init-agent-plan, or --compile-authoring-plan. The CLI writes bundles under artifacts/agent/generation.",
    )
    parser.add_argument("--workspace-root", default=".", help="Workspace root for artifact persistence.")
    parser.add_argument(
        "--output-format",
        choices=["json", "text"],
        default="json",
        help="Output format for review-oriented commands. Defaults to json.",
    )
    parser.add_argument("--no-persist", action="store_true", help="Do not persist generation artifacts.")
    parser.add_argument("--run-id", help="Generation run id for review or promotion.")
    parser.add_argument("--draft-id", help="Draft id selected for promotion.")
    parser.add_argument("--path", help="Scenario markdown file or directory path for validation commands.")
    parser.add_argument(
        "--mode",
        choices=["parser", "compile", "preflight"],
        default="parser",
        help="Validation mode for --validate-scenario. Defaults to parser.",
    )
    parser.add_argument(
        "--target-type",
        choices=[target_type.value for target_type in DraftEditTargetType],
        help="Edit target type for --show-patch-template.",
    )
    parser.add_argument("--allow-invalid", action="store_true", help="Allow promotion of parser-invalid drafts.")
    parser.add_argument(
        "--allow-known-gaps",
        action="store_true",
        help=(
            "Allow promotion when review found known non-parser gaps or high-priority edit targets. "
            "Use only after explicit operator review."
        ),
    )
    parser.add_argument(
        "--purge-target-dir",
        action="store_true",
        help="Delete the resolved promotion target directory before promotion. Use for rerender/re-promote cycles.",
    )
    parser.add_argument(
        "--target-dir",
        default="scenarios/generated",
        help="Promotion target directory under scenarios/. The default generated/ root uses a run-scoped subdirectory.",
    )

    parser.add_argument(
        "--render-drafts",
        action="store_true",
        help="Render non-executed markdown scenario drafts from the generated plan and parser-validate them.",
    )
    return parser

