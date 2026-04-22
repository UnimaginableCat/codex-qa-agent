"""Scenario runner persistence helpers."""

from __future__ import annotations

from .artifacts import (
    ARTIFACTS_DIRNAME,
    ArtifactPolicyError,
    COMPILED_PLAN_FILENAME,
    CONTEXT_FILENAME,
    JOURNAL_FILENAME,
    MANIFEST_FILENAME,
    PARSED_PLANS_DIRNAME,
    PAUSE_STATE_FILENAME,
    RUNS_DIRNAME,
    ScenarioRunArtifactStore,
    SUMMARY_FILENAME,
    WorkspaceDirectories,
    create_artifact_directory,
    create_compiled_plan_path,
    create_report_path,
    create_run_state_directory,
    create_step_artifact_path,
    ensure_artifact_output_path,
    ensure_workspace_directories,
    write_bundle_compiled_plan_json,
    write_compiled_plan_json,
    write_context_json,
    write_journal_entry,
    write_pause_state_json,
    write_step_artifact_json,
    write_summary_json,
)

__all__ = [
    "ARTIFACTS_DIRNAME",
    "ArtifactPolicyError",
    "COMPILED_PLAN_FILENAME",
    "CONTEXT_FILENAME",
    "JOURNAL_FILENAME",
    "MANIFEST_FILENAME",
    "PARSED_PLANS_DIRNAME",
    "PAUSE_STATE_FILENAME",
    "RUNS_DIRNAME",
    "ScenarioRunArtifactStore",
    "SUMMARY_FILENAME",
    "WorkspaceDirectories",
    "create_artifact_directory",
    "create_compiled_plan_path",
    "create_report_path",
    "create_run_state_directory",
    "create_step_artifact_path",
    "ensure_artifact_output_path",
    "ensure_workspace_directories",
    "write_bundle_compiled_plan_json",
    "write_compiled_plan_json",
    "write_context_json",
    "write_journal_entry",
    "write_pause_state_json",
    "write_step_artifact_json",
    "write_summary_json",
    "load_pause_state",
    "restore_session_from_pause_state",
]


def __getattr__(name: str):
    if name in {"load_pause_state", "restore_session_from_pause_state"}:
        from .resume import load_pause_state, restore_session_from_pause_state

        exports = {
            "load_pause_state": load_pause_state,
            "restore_session_from_pause_state": restore_session_from_pause_state,
        }
        return exports[name]
    raise AttributeError(name)
