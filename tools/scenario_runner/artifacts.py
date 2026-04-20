"""Filesystem helpers for scenario runner state and immutable artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.common.errors import ToolingError
from tools.common.io import write_text_file

from .models import RunContext, ScenarioDefinition, ScenarioExecutionSummary
from .redaction import redact_sensitive_data

PARSED_PLANS_DIRNAME = Path(".codex-qa/parsed-plans")
RUNS_DIRNAME = Path(".codex-qa/runs")
ARTIFACTS_DIRNAME = Path("artifacts/agent")
CONTEXT_FILENAME = "context.json"
SUMMARY_FILENAME = "summary.json"
JOURNAL_FILENAME = "journal.jsonl"
FORBIDDEN_ARTIFACT_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".sh",
    ".ps1",
}


class ArtifactPolicyError(ToolingError):
    """Raised when a write would violate artifact immutability rules."""


@dataclass(slots=True)
class WorkspaceDirectories:
    parsed_plans_dir: Path
    runs_root_dir: Path
    artifacts_root_dir: Path


def ensure_workspace_directories(workspace_root: Path) -> WorkspaceDirectories:
    parsed_plans_dir = workspace_root / PARSED_PLANS_DIRNAME
    runs_root_dir = workspace_root / RUNS_DIRNAME
    artifacts_root_dir = workspace_root / ARTIFACTS_DIRNAME

    parsed_plans_dir.mkdir(parents=True, exist_ok=True)
    runs_root_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root_dir.mkdir(parents=True, exist_ok=True)

    return WorkspaceDirectories(
        parsed_plans_dir=parsed_plans_dir,
        runs_root_dir=runs_root_dir,
        artifacts_root_dir=artifacts_root_dir,
    )


def create_run_state_directory(runs_root_dir: Path, run_id: str) -> Path:
    run_state_dir = runs_root_dir / run_id
    run_state_dir.mkdir(parents=True, exist_ok=False)
    return run_state_dir


def create_artifact_directory(artifacts_root_dir: Path, artifact_dir_name: str) -> Path:
    artifact_dir = artifacts_root_dir / artifact_dir_name
    artifact_dir.mkdir(parents=True, exist_ok=False)
    return artifact_dir


def create_compiled_plan_path(parsed_plans_dir: Path, scenario_slug: str) -> Path:
    return parsed_plans_dir / f"{scenario_slug}.json"


def write_compiled_plan_json(parsed_plan_path: Path, scenario_definition: ScenarioDefinition) -> Path:
    _write_json_file(parsed_plan_path, scenario_definition.to_dict())
    return parsed_plan_path


def create_step_artifact_path(
    run_context: RunContext,
    step_id: str,
    artifact_name: str,
) -> Path:
    target_path = run_context.artifact_dir / "steps" / step_id / artifact_name
    return ensure_artifact_output_path(target_path, run_context.artifacts_root_dir)


def write_step_artifact_json(
    run_context: RunContext,
    step_id: str,
    artifact_name: str,
    payload: dict[str, Any],
) -> Path:
    target_path = create_step_artifact_path(run_context, step_id, artifact_name)
    _write_json_file(target_path, payload)
    return target_path


def create_report_path(run_context: RunContext) -> Path:
    target_path = run_context.artifact_dir / "report.md"
    return ensure_artifact_output_path(target_path, run_context.artifacts_root_dir)


def write_context_json(run_context: RunContext) -> Path:
    target_path = run_context.run_state_dir / CONTEXT_FILENAME
    _write_json_file(target_path, run_context.to_dict())
    return target_path


def write_summary_json(run_context: RunContext, summary: ScenarioExecutionSummary) -> Path:
    target_path = run_context.run_state_dir / SUMMARY_FILENAME
    _write_json_file(target_path, summary.to_dict())
    return target_path


def write_journal_entry(run_context: RunContext, entry: dict[str, Any]) -> Path:
    target_path = run_context.run_state_dir / JOURNAL_FILENAME
    serialized_entry = json.dumps(redact_sensitive_data(entry), ensure_ascii=False)
    if target_path.exists():
        with target_path.open("a", encoding="utf-8") as handle:
            handle.write(serialized_entry + "\n")
    else:
        write_text_file(target_path, serialized_entry + "\n")
    return target_path


def ensure_artifact_output_path(path: Path, artifacts_root_dir: Path) -> Path:
    resolved_artifacts_root = artifacts_root_dir.resolve()
    resolved_path = path.resolve()

    if resolved_artifacts_root not in resolved_path.parents and resolved_path != resolved_artifacts_root:
        raise ArtifactPolicyError("Artifact outputs must be written under artifacts/agent")

    if resolved_path.suffix.lower() in FORBIDDEN_ARTIFACT_SUFFIXES:
        raise ArtifactPolicyError(
            "Never write source code into artifacts/. Artifacts are only for immutable outputs/evidence."
        )

    return resolved_path


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    safe_payload = redact_sensitive_data(payload)
    write_text_file(path, json.dumps(safe_payload, ensure_ascii=False, indent=2) + "\n")
