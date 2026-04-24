"""Run context creation helpers for generation pipeline runs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tools.generation.domain.models import GenerationRunContext, GenerationSourceInput
from tools.generation.persistence.artifacts import (
    load_generation_run_context_from_bundle_file,
    create_generation_artifact_directory,
    ensure_generation_workspace_directories,
)


def create_generation_run_id(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"gen-{timestamp}-{uuid4().hex[:8]}"


def initialize_generation_run_context(
    source_input: GenerationSourceInput,
    workspace_root: Path | None = None,
) -> GenerationRunContext:
    if source_input.source_path is not None:
        existing_context = load_generation_run_context_from_bundle_file(source_input.source_path.resolve())
        if existing_context is not None:
            return existing_context
    resolved_workspace_root = (workspace_root or Path.cwd()).resolve()
    run_id = create_generation_run_id()
    directories = ensure_generation_workspace_directories(resolved_workspace_root)
    artifact_dir_name = run_id
    artifact_dir = create_generation_artifact_directory(
        directories.artifacts_root_dir,
        artifact_dir_name,
    )
    started_at = datetime.now(UTC).isoformat(timespec="seconds")

    return GenerationRunContext(
        run_id=run_id,
        workspace_root=resolved_workspace_root,
        source_id=source_input.source_id,
        project=source_input.project,
        artifacts_root_dir=directories.artifacts_root_dir,
        artifact_dir=artifact_dir,
        started_at=started_at,
        variables={
            "run_id": run_id,
            "source_id": source_input.source_id,
            "project": source_input.project,
        },
    )

