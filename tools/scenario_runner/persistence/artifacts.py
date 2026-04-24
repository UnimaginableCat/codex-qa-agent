"""Filesystem helpers for scenario runner state and immutable artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from tools.common.errors import ToolingError
from tools.common.io import write_text_file

from ..domain.execution import ExecutionEvent
from ..domain.models import RunContext, ScenarioDefinition, ScenarioExecutionSummary
from ..domain.pause import PauseState
from ..runtime.redaction import redact_sensitive_data

PARSED_PLANS_DIRNAME = Path(".codex-qa/parsed-plans")
RUNS_DIRNAME = Path(".codex-qa/runs")
ARTIFACTS_DIRNAME = Path("artifacts/agent/scenario-runs")
CONTEXT_FILENAME = "context.json"
SUMMARY_FILENAME = "summary.json"
JOURNAL_FILENAME = "journal.jsonl"
PAUSE_STATE_FILENAME = "pause-state.json"
COMPILED_PLAN_FILENAME = "compiled-plan.json"
MANIFEST_FILENAME = "manifest.json"
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
RUN_STATE_NETWORK_DEBUG_KEYS = {
    "api_request_debug",
    "request_debug",
    "dns_precheck",
    "resolver_debug",
    "process_debug",
    "resolv_conf",
    "getent_hosts",
    "nslookup",
    "ping",
    "hosts_file",
    "resolver_comparison",
    "getaddrinfo",
    "gethostbyname",
    "getfqdn",
    "hostname_value",
    "hostname_repr",
    "final_url_value",
    "final_url_repr",
    "base_url_value",
    "base_url_repr",
    "normalized_base_url_value",
    "normalized_base_url_repr",
    "env_base_url_raw_value",
    "env_base_url_raw_repr",
    "env_base_url_normalized_value",
    "env_base_url_normalized_repr",
    "parsed_hostname",
    "parsed_netloc",
    "parsed_port",
    "parsed_scheme",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
}


class ArtifactPolicyError(ToolingError):
    """Raised when a write would violate artifact immutability rules."""


@dataclass(slots=True)
class WorkspaceDirectories:
    parsed_plans_dir: Path
    runs_root_dir: Path
    artifacts_root_dir: Path


class ScenarioRunArtifactStore:
    """Persists raw execution artifacts and projection outputs to disk."""

    def write_initial_state(self, session, scenario_definition: ScenarioDefinition) -> None:
        write_compiled_plan_json(session.run_context.compiled_plan_path, scenario_definition)
        write_bundle_compiled_plan_json(session.run_context, scenario_definition)
        write_context_json(session.run_context)
        if session.execution_events:
            self.write_journal(session.run_context, [session.execution_events[0]])

    @staticmethod
    def create_report_path(run_context: RunContext) -> Path:
        return create_report_path(run_context)

    @staticmethod
    def create_pause_state_path(run_context: RunContext) -> Path:
        return create_pause_state_path(run_context)

    @staticmethod
    def write_context(run_context: RunContext) -> Path:
        return write_context_json(run_context)

    @staticmethod
    def write_summary(run_context: RunContext, summary: ScenarioExecutionSummary) -> Path:
        return write_summary_json(run_context, summary)

    @staticmethod
    def write_pause_state(run_context: RunContext, pause_state: PauseState) -> Path:
        return write_pause_state_json(run_context, pause_state)

    @staticmethod
    def write_journal(
        run_context: RunContext,
        entries: Iterable[dict[str, Any] | ExecutionEvent],
    ) -> Path | None:
        last_path: Path | None = None
        for entry in entries:
            last_path = write_journal_entry(run_context, entry)
        return last_path


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


def write_bundle_compiled_plan_json(run_context: RunContext, scenario_definition: ScenarioDefinition) -> Path:
    target_path = ensure_artifact_output_path(
        run_context.artifact_dir / COMPILED_PLAN_FILENAME,
        run_context.artifacts_root_dir,
    )
    _write_json_file(target_path, scenario_definition.to_dict())
    _write_manifest_json(run_context)
    return target_path


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


def create_pause_state_path(run_context: RunContext) -> Path:
    target_path = run_context.artifact_dir / PAUSE_STATE_FILENAME
    return ensure_artifact_output_path(target_path, run_context.artifacts_root_dir)


def write_context_json(run_context: RunContext) -> Path:
    target_path = run_context.run_state_dir / CONTEXT_FILENAME
    payload = _strip_run_state_network_debug(run_context.to_dict())
    _write_json_file(target_path, payload)
    _write_json_file(_bundle_file_path(run_context, CONTEXT_FILENAME), payload)
    _write_manifest_json(run_context)
    return target_path


def write_summary_json(run_context: RunContext, summary: ScenarioExecutionSummary) -> Path:
    target_path = run_context.run_state_dir / SUMMARY_FILENAME
    payload = _strip_run_state_network_debug(summary.to_dict())
    _write_json_file(target_path, payload)
    _write_json_file(_bundle_file_path(run_context, SUMMARY_FILENAME), payload)
    _write_manifest_json(run_context)
    return target_path


def write_pause_state_json(run_context: RunContext, pause_state: PauseState) -> Path:
    target_path = run_context.run_state_dir / PAUSE_STATE_FILENAME
    pause_state.set_path(target_path)
    payload = pause_state.to_dict()
    _write_json_file(target_path, payload)
    _write_json_file(_bundle_file_path(run_context, PAUSE_STATE_FILENAME), payload)
    _write_manifest_json(run_context)
    return target_path


def write_journal_entry(run_context: RunContext, entry: dict[str, Any] | ExecutionEvent) -> Path:
    target_path = run_context.run_state_dir / JOURNAL_FILENAME
    payload = entry.to_dict() if isinstance(entry, ExecutionEvent) else entry
    serialized_entry = json.dumps(redact_sensitive_data(payload), ensure_ascii=False)
    _append_jsonl(target_path, serialized_entry)
    _append_jsonl(_bundle_file_path(run_context, JOURNAL_FILENAME), serialized_entry)
    _write_manifest_json(run_context)
    return target_path


def ensure_artifact_output_path(path: Path, artifacts_root_dir: Path) -> Path:
    resolved_artifacts_root = artifacts_root_dir.resolve()
    resolved_path = path.resolve()

    if resolved_artifacts_root not in resolved_path.parents and resolved_path != resolved_artifacts_root:
        raise ArtifactPolicyError("Artifact outputs must be written under artifacts/agent/scenario-runs")

    if resolved_path.suffix.lower() in FORBIDDEN_ARTIFACT_SUFFIXES:
        raise ArtifactPolicyError(
            "Never write source code into artifacts/. Artifacts are only for immutable outputs/evidence."
        )

    return resolved_path


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    safe_payload = redact_sensitive_data(payload)
    write_text_file(path, json.dumps(safe_payload, ensure_ascii=False, indent=2) + "\n")


def _append_jsonl(path: Path, serialized_entry: str) -> None:
    if path.exists():
        with path.open("a", encoding="utf-8") as handle:
            handle.write(serialized_entry + "\n")
    else:
        write_text_file(path, serialized_entry + "\n")


def _bundle_file_path(run_context: RunContext, filename: str) -> Path:
    return ensure_artifact_output_path(run_context.artifact_dir / filename, run_context.artifacts_root_dir)


def _write_manifest_json(run_context: RunContext) -> Path:
    target_path = _bundle_file_path(run_context, MANIFEST_FILENAME)
    payload = {
        "run_id": run_context.run_id,
        "scenario": run_context.scenario_name,
        "scenario_slug": run_context.scenario_slug,
        "scenario_path": str(run_context.scenario_path),
        "workspace_root": str(run_context.workspace_root),
        "run_state_dir": str(run_context.run_state_dir),
        "artifact_dir": str(run_context.artifact_dir),
        "legacy_compiled_plan_path": str(run_context.compiled_plan_path),
        "bundle": {
            "manifest_path": str(target_path),
            "context_path": str(run_context.artifact_dir / CONTEXT_FILENAME),
            "summary_path": str(run_context.artifact_dir / SUMMARY_FILENAME),
            "journal_path": str(run_context.artifact_dir / JOURNAL_FILENAME),
            "pause_state_path": str(run_context.artifact_dir / PAUSE_STATE_FILENAME),
            "compiled_plan_path": str(run_context.artifact_dir / COMPILED_PLAN_FILENAME),
            "report_path": str(run_context.artifact_dir / "report.md"),
            "steps_dir": str(run_context.artifact_dir / "steps"),
        },
        "legacy_run_state": {
            "context_path": str(run_context.run_state_dir / CONTEXT_FILENAME),
            "summary_path": str(run_context.run_state_dir / SUMMARY_FILENAME),
            "journal_path": str(run_context.run_state_dir / JOURNAL_FILENAME),
            "pause_state_path": str(run_context.run_state_dir / PAUSE_STATE_FILENAME),
        },
    }
    _write_json_file(target_path, payload)
    return target_path


def _strip_run_state_network_debug(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_run_state_network_debug(item)
            for key, item in value.items()
            if str(key) not in RUN_STATE_NETWORK_DEBUG_KEYS
        }
    if isinstance(value, list):
        return [_strip_run_state_network_debug(item) for item in value]
    return value
