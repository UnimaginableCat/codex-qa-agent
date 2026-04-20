"""Run context creation helpers for the scenario runner."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .artifacts import (
    create_artifact_directory,
    create_compiled_plan_path,
    create_run_state_directory,
    ensure_workspace_directories,
)
from .models import RunContext, ScenarioDefinition


def create_run_id(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}-{uuid4().hex[:8]}"


def initialize_run_context(
    scenario_definition: ScenarioDefinition,
    workspace_root: Path | None = None,
) -> RunContext:
    resolved_workspace_root = (workspace_root or Path.cwd()).resolve()
    run_id = create_run_id()
    directories = ensure_workspace_directories(resolved_workspace_root)
    compiled_plan_path = create_compiled_plan_path(
        directories.parsed_plans_dir,
        scenario_definition.scenario_slug,
    )
    artifact_dir_name = f"{scenario_definition.scenario_slug}-{run_id}"
    run_state_dir = create_run_state_directory(directories.runs_root_dir, run_id)
    artifact_dir = create_artifact_directory(directories.artifacts_root_dir, artifact_dir_name)
    started_at = datetime.now(UTC).isoformat(timespec="seconds")

    return RunContext(
        run_id=run_id,
        workspace_root=resolved_workspace_root,
        scenario_path=scenario_definition.scenario_path.resolve(),
        scenario_slug=scenario_definition.scenario_slug,
        scenario_name=scenario_definition.scenario_name,
        parsed_plans_dir=directories.parsed_plans_dir,
        compiled_plan_path=compiled_plan_path,
        runs_root_dir=directories.runs_root_dir,
        run_state_dir=run_state_dir,
        artifacts_root_dir=directories.artifacts_root_dir,
        artifact_dir=artifact_dir,
        started_at=started_at,
        variables={
            "run_id": run_id,
            "scenario_name": scenario_definition.scenario_name,
            "scenario_slug": scenario_definition.scenario_slug,
            "project": scenario_definition.project,
        },
    )
