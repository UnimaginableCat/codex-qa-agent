"""Support code for the generation CLI adapter."""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.generation.application import GenerationInputMode
from tools.generation.cli_core import (
    LEGACY_AGENT_PLAN_ROOT,
    MANAGED_AGENT_PLAN_ROOT,
    _path_under_root,
    _resolve_bundle_dir,
)
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic


def _project_arg_diagnostics(project: str) -> list[GenerationDiagnostic]:
    normalized = project.strip().replace("\\", "/").strip("/")
    if normalized.startswith("code/") and len(normalized.split("/", 1)[1].strip()) > 0:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_project_must_target_code_subdir",
            message="--project must point at a workspace project under code/<project>.",
            severity=DiagnosticSeverity.ERROR,
            source_ref=project,
            details={"project": project},
        )
    ]


def _adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.authoring_plan_file and not args.agent_plan_file and not args.prose and not args.source_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_source",
                message="Generation requires exactly one of --authoring-plan-file, --agent-plan-file, --prose, or --source-file.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.input_mode == GenerationInputMode.AUTHORING_PLAN.value and not args.authoring_plan_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_authoring_plan_mode_requires_file",
                message="input_mode=authoring_plan requires --authoring-plan-file.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.input_mode == GenerationInputMode.AGENT_PLAN.value and not args.agent_plan_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_agent_plan_mode_requires_file",
                message="input_mode=agent_plan requires --agent-plan-file.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.input_mode == GenerationInputMode.PROSE.value and args.agent_plan_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_prose_mode_rejects_agent_plan_file",
                message="input_mode=prose requires --prose or --source-file, not --agent-plan-file.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.input_mode == GenerationInputMode.PROSE.value and args.authoring_plan_file:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_prose_mode_rejects_authoring_plan_file",
                message="input_mode=prose requires --prose or --source-file, not --authoring-plan-file.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.authoring_plan_file and not Path(args.authoring_plan_file).exists():
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_authoring_plan_file_missing",
                message="Authoring-plan file does not exist.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.authoring_plan_file,
            )
        )
    if args.authoring_plan_file and _path_under_root(Path(args.authoring_plan_file), LEGACY_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_authoring_plan_file_legacy_root_unsupported",
                message="Legacy artifacts/agent/input is no longer supported. Use artifacts/agent/generation for generated bundles.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.authoring_plan_file,
            )
        )
    if args.agent_plan_file and not Path(args.agent_plan_file).exists():
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_agent_plan_file_missing",
                message="Agent-authored plan file does not exist.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.agent_plan_file,
            )
        )
    if args.agent_plan_file and _path_under_root(Path(args.agent_plan_file), LEGACY_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_agent_plan_file_legacy_root_unsupported",
                message="Legacy artifacts/agent/input is no longer supported. Use one generation bundle root under artifacts/agent/generation.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.agent_plan_file,
            )
        )
    if not args.agent_plan_file and not args.authoring_plan_file and not args.source_id:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_source_id",
                message="Prose generation requires --source-id.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    if not args.agent_plan_file and not args.authoring_plan_file and not args.project:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_generation_requires_project",
                message="Prose generation requires --project.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.source_id,
            )
        )
    if args.project:
        diagnostics.extend(_project_arg_diagnostics(args.project))
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



def _init_agent_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.output:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_agent_plan_requires_output",
                message="--init-agent-plan requires --output.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    elif not _path_under_root(Path(args.output), MANAGED_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_agent_plan_requires_managed_root",
                message="Agent plan scaffold must be written under artifacts/agent/generation.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.output,
            )
        )
    if args.project:
        diagnostics.extend(_project_arg_diagnostics(args.project))
    return diagnostics



def _init_authoring_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.output:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_authoring_plan_requires_output",
                message="--init-authoring-plan requires --output.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    elif not _path_under_root(Path(args.output), MANAGED_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_authoring_plan_requires_managed_root",
                message="Authoring plan scaffold must be written under artifacts/agent/generation.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.output,
            )
        )
    if args.project:
        diagnostics.extend(_project_arg_diagnostics(args.project))
    return diagnostics



def _init_entity_inventory_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.output:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_entity_inventory_requires_output",
                message="--init-entity-inventory requires --output.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    elif not _path_under_root(Path(args.output), MANAGED_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_entity_inventory_requires_managed_root",
                message="Entity inventory scaffold must target artifacts/agent/generation or one existing bundle inside it.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.output,
            )
        )
    if args.project:
        diagnostics.extend(_project_arg_diagnostics(args.project))
    return diagnostics



def _init_operation_inventory_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if not args.output:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_operation_inventory_requires_output",
                message="--init-operation-inventory requires --output.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    elif not _path_under_root(Path(args.output), MANAGED_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_init_operation_inventory_requires_managed_root",
                message="Operation inventory scaffold must target artifacts/agent/generation or one existing bundle inside it.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.output,
            )
        )
    if args.project:
        diagnostics.extend(_project_arg_diagnostics(args.project))
    return diagnostics



def _validate_agent_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.agent_plan_file:
        if _path_under_root(Path(args.agent_plan_file), LEGACY_AGENT_PLAN_ROOT):
            return [
                GenerationDiagnostic(
                    code="adapter_validate_agent_plan_legacy_root_unsupported",
                    message="Legacy artifacts/agent/input is no longer supported. Use one generation bundle root under artifacts/agent/generation.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=args.agent_plan_file,
                )
            ]
        return []
    return [
        GenerationDiagnostic(
            code="adapter_validate_agent_plan_requires_file",
            message="--validate-agent-plan requires --agent-plan-file.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]



def _validate_authoring_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.authoring_plan_file:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_validate_authoring_plan_requires_file",
            message="--validate-authoring-plan requires --authoring-plan-file.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]



def _sync_authoring_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if not args.path:
        return [
            GenerationDiagnostic(
                code="adapter_sync_authoring_plan_requires_path",
                message="--sync-authoring-plan requires --path pointing to a managed bundle dir or staged file inside it.",
                severity=DiagnosticSeverity.ERROR,
            )
        ]
    bundle_dir = _resolve_bundle_dir(Path(args.path))
    if not _path_under_root(bundle_dir, MANAGED_AGENT_PLAN_ROOT):
        return [
            GenerationDiagnostic(
                code="adapter_sync_authoring_plan_requires_managed_root",
                message="--sync-authoring-plan requires a path under artifacts/agent/generation.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.path,
            )
        ]
    return []



def _validate_entity_inventory_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.entity_inventory_file:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_validate_entity_inventory_requires_file",
            message="--validate-entity-inventory requires --entity-inventory-file.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]



def _validate_operation_inventory_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.operation_inventory_file:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_validate_operation_inventory_requires_file",
            message="--validate-operation-inventory requires --operation-inventory-file.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]



def _validate_authoring_bundle_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if not args.path:
        return [
            GenerationDiagnostic(
                code="adapter_validate_authoring_bundle_requires_path",
                message="--validate-authoring-bundle requires --path pointing to a managed bundle dir or one staged file inside it.",
                severity=DiagnosticSeverity.ERROR,
            )
        ]
    bundle_dir = _resolve_bundle_dir(Path(args.path))
    if not _path_under_root(bundle_dir, MANAGED_AGENT_PLAN_ROOT):
        return [
            GenerationDiagnostic(
                code="adapter_validate_authoring_bundle_requires_managed_root",
                message="--validate-authoring-bundle requires a path under artifacts/agent/generation.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.path,
            )
        ]
    return []



def _compile_authoring_plan_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    diagnostics = _validate_authoring_plan_adapter_diagnostics(args)
    if not args.output:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_compile_authoring_plan_requires_output",
                message="--compile-authoring-plan requires --output.",
                severity=DiagnosticSeverity.ERROR,
            )
        )
    elif not _path_under_root(Path(args.output), MANAGED_AGENT_PLAN_ROOT):
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_compile_authoring_plan_requires_managed_root",
                message="Compiled authoring-plan bundle must be written under artifacts/agent/generation.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.output,
            )
        )
    return diagnostics



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
    if args.promote_draft and not args.draft_id:
        diagnostics.append(
            GenerationDiagnostic(
                code="adapter_promotion_requires_draft_id",
                message="--promote-draft requires --draft-id.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.run_id,
            )
        )
    return diagnostics



def _patch_template_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.target_type:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_patch_template_requires_target_type",
            message="--show-patch-template requires --target-type.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]



def _revalidation_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if args.path:
        return []
    return [
        GenerationDiagnostic(
            code="adapter_revalidation_requires_path",
            message="--validate-scenario requires --path.",
            severity=DiagnosticSeverity.ERROR,
        )
    ]



def _revalidation_dir_adapter_diagnostics(args: argparse.Namespace) -> list[GenerationDiagnostic]:
    if not args.path:
        return [
            GenerationDiagnostic(
                code="adapter_revalidation_dir_requires_path",
                message="--validate-scenario-dir requires --path.",
                severity=DiagnosticSeverity.ERROR,
            )
        ]
    path = Path(args.path)
    if not path.exists():
        return [
            GenerationDiagnostic(
                code="adapter_revalidation_dir_path_missing",
                message="--validate-scenario-dir path does not exist.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.path,
            )
        ]
    if path.exists() and not path.is_dir():
        return [
            GenerationDiagnostic(
                code="adapter_revalidation_dir_requires_directory",
                message="--validate-scenario-dir requires a directory path.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=args.path,
            )
        ]
    return []

