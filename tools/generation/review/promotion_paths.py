"""Promotion path and filename helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

from tools.common.slugging import stable_slug
from tools.generation.domain.models import GenerationRunContext

from .common import _slugify

PROMOTED_SCENARIO_FILENAME_MAX_LENGTH = 120
PROMOTED_SCENARIO_DIRNAME_MAX_LENGTH = 120


def _resolve_target_dir(workspace_root: Path, target_dir: Path) -> Path:
    target = target_dir if target_dir.is_absolute() else workspace_root / target_dir
    scenarios_root = (workspace_root / "scenarios").resolve()
    resolved = target.resolve()
    if resolved != scenarios_root and scenarios_root not in resolved.parents:
        raise ValueError("Promotion target directory must be under scenarios/.")
    return target

def _promotion_target_dir(base_target_dir: Path, run_context: GenerationRunContext) -> Path:
    normalized_parts = tuple(_slugify(part) for part in base_target_dir.parts)
    if normalized_parts[-2:] != ("scenarios", "generated"):
        return base_target_dir
    dirname = stable_slug(
        f"{run_context.source_id}-{run_context.run_id}",
        fallback="generated-scenarios",
        max_length=PROMOTED_SCENARIO_DIRNAME_MAX_LENGTH,
        hash_input=f"{run_context.source_id}|{run_context.run_id}",
    )
    return base_target_dir / dirname

def _purge_target_dir(target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)

def _promotion_header(run_id: str, draft_id: str) -> str:
    return (
        "<!--\n"
        "generated_by: codex-qa-agent\n"
        f"generation_run_id: {run_id}\n"
        f"draft_id: {draft_id}\n"
        "source: draft-rendering-preview\n"
        "-->\n\n"
    )

def _promoted_scenario_filename(source_id: str, draft_id: str) -> str:
    stem = stable_slug(
        f"{source_id}-{draft_id}",
        fallback="scenario",
        max_length=PROMOTED_SCENARIO_FILENAME_MAX_LENGTH,
        hash_input=f"{source_id}|{draft_id}",
    )
    return f"{stem}.md"
