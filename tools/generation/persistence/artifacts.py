"""Filesystem persistence for generation run artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.common.errors import ToolingError
from tools.common.io import write_text_file
from tools.generation.domain.models import (
    GenerationDiagnostic,
    GenerationRunContext,
    GenerationSourceInput,
    NormalizedProseSource,
    NormalizedTestPlan,
    TraceabilityMap,
)
from tools.generation.enrichment.models import EnrichedTestPlanResult
from tools.generation.evidence.models import GenerationEvidenceBundle

GENERATION_RUNS_DIRNAME = Path(".codex-qa/generation/runs")
GENERATION_ARTIFACTS_DIRNAME = Path("artifacts/agent/generation")
CONTEXT_FILENAME = "context.json"
SOURCE_INPUT_FILENAME = "source-input.json"
NORMALIZED_SOURCE_FILENAME = "normalized-source.json"
NORMALIZED_PLAN_FILENAME = "normalized-plan.json"
TRACEABILITY_MAP_FILENAME = "traceability-map.json"
DIAGNOSTICS_FILENAME = "diagnostics.json"
EVIDENCE_RUN_STATE_FILENAME = "evidence.json"
EVIDENCE_BUNDLE_FILENAME = "evidence-bundle.json"
ENRICHED_PLAN_FILENAME = "enriched-plan.json"
ENRICHMENT_RESULT_FILENAME = "enrichment-result.json"
APPLIED_EVIDENCE_FILENAME = "applied-evidence.json"
UNAPPLIED_EVIDENCE_FILENAME = "unapplied-evidence.json"
SUMMARY_FILENAME = "summary.json"
MANIFEST_FILENAME = "manifest.json"
FORBIDDEN_GENERATION_ARTIFACT_SUFFIXES = {
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


class GenerationArtifactPolicyError(ToolingError):
    """Raised when generation artifact persistence would leave the artifact root."""


@dataclass(slots=True)
class GenerationWorkspaceDirectories:
    runs_root_dir: Path
    artifacts_root_dir: Path


class FileGenerationArtifactStore:
    """Writes generation artifacts to a predictable filesystem bundle."""

    def write_context(self, run_context: GenerationRunContext) -> Path:
        target_path = run_context.run_state_dir / CONTEXT_FILENAME
        payload = run_context.to_dict()
        _write_json_file(target_path, payload)
        _write_json_file(_bundle_file_path(run_context, CONTEXT_FILENAME), payload)
        self.write_manifest(run_context)
        return target_path

    def write_source_input(
        self,
        run_context: GenerationRunContext,
        source_input: GenerationSourceInput,
    ) -> Path:
        target_path = _bundle_file_path(run_context, SOURCE_INPUT_FILENAME)
        _write_json_file(target_path, source_input.to_dict())
        self.write_manifest(run_context)
        return target_path

    def write_normalized_source(
        self,
        run_context: GenerationRunContext,
        normalized_source: NormalizedProseSource,
    ) -> Path:
        target_path = _bundle_file_path(run_context, NORMALIZED_SOURCE_FILENAME)
        _write_json_file(target_path, normalized_source.to_dict())
        self.write_manifest(run_context)
        return target_path

    def write_normalized_plan(
        self,
        run_context: GenerationRunContext,
        normalized_plan: NormalizedTestPlan,
    ) -> Path:
        target_path = _bundle_file_path(run_context, NORMALIZED_PLAN_FILENAME)
        _write_json_file(target_path, normalized_plan.to_dict())
        self.write_manifest(run_context)
        return target_path

    def write_traceability_map(
        self,
        run_context: GenerationRunContext,
        traceability_map: TraceabilityMap,
    ) -> Path:
        target_path = _bundle_file_path(run_context, TRACEABILITY_MAP_FILENAME)
        _write_json_file(target_path, traceability_map.to_dict())
        self.write_manifest(run_context)
        return target_path

    def write_diagnostics(
        self,
        run_context: GenerationRunContext,
        diagnostics: list[GenerationDiagnostic],
    ) -> Path:
        target_path = _bundle_file_path(run_context, DIAGNOSTICS_FILENAME)
        payload = {"diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics]}
        _write_json_file(target_path, payload)
        self.write_manifest(run_context)
        return target_path

    def write_evidence_bundle(
        self,
        run_context: GenerationRunContext,
        evidence_bundle: GenerationEvidenceBundle,
    ) -> Path:
        run_state_path = run_context.run_state_dir / EVIDENCE_RUN_STATE_FILENAME
        payload = evidence_bundle.to_dict()
        _write_json_file(run_state_path, payload)
        _write_json_file(_bundle_file_path(run_context, EVIDENCE_BUNDLE_FILENAME), payload)
        self.write_manifest(run_context)
        return run_state_path

    def write_enriched_plan(
        self,
        run_context: GenerationRunContext,
        normalized_plan: NormalizedTestPlan,
    ) -> Path:
        target_path = _bundle_file_path(run_context, ENRICHED_PLAN_FILENAME)
        _write_json_file(target_path, normalized_plan.to_dict())
        self.write_manifest(run_context)
        return target_path

    def write_enrichment_result(
        self,
        run_context: GenerationRunContext,
        enrichment_result: EnrichedTestPlanResult,
    ) -> Path:
        target_path = _bundle_file_path(run_context, ENRICHMENT_RESULT_FILENAME)
        _write_json_file(target_path, enrichment_result.to_dict())
        _write_json_file(
            _bundle_file_path(run_context, APPLIED_EVIDENCE_FILENAME),
            {"applied_evidence": [link.to_dict() for link in enrichment_result.applied_evidence]},
        )
        _write_json_file(
            _bundle_file_path(run_context, UNAPPLIED_EVIDENCE_FILENAME),
            {"unapplied_evidence": [reason.to_dict() for reason in enrichment_result.unapplied_evidence]},
        )
        self.write_manifest(run_context)
        return target_path

    def write_summary(self, run_context: GenerationRunContext, summary: dict[str, object]) -> Path:
        target_path = run_context.run_state_dir / SUMMARY_FILENAME
        _write_json_file(target_path, summary)
        _write_json_file(_bundle_file_path(run_context, SUMMARY_FILENAME), summary)
        self.write_manifest(run_context)
        return target_path

    @staticmethod
    def write_manifest(run_context: GenerationRunContext) -> Path:
        return _write_manifest_json(run_context)


def ensure_generation_workspace_directories(workspace_root: Path) -> GenerationWorkspaceDirectories:
    runs_root_dir = workspace_root / GENERATION_RUNS_DIRNAME
    artifacts_root_dir = workspace_root / GENERATION_ARTIFACTS_DIRNAME

    runs_root_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root_dir.mkdir(parents=True, exist_ok=True)

    return GenerationWorkspaceDirectories(
        runs_root_dir=runs_root_dir,
        artifacts_root_dir=artifacts_root_dir,
    )


def create_generation_run_state_directory(runs_root_dir: Path, run_id: str) -> Path:
    run_state_dir = runs_root_dir / run_id
    run_state_dir.mkdir(parents=True, exist_ok=False)
    return run_state_dir


def create_generation_artifact_directory(artifacts_root_dir: Path, artifact_dir_name: str) -> Path:
    artifact_dir = artifacts_root_dir / artifact_dir_name
    artifact_dir.mkdir(parents=True, exist_ok=False)
    return artifact_dir


def slugify_artifact_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return normalized.lower() or "generation-source"


def ensure_generation_artifact_output_path(path: Path, artifacts_root_dir: Path) -> Path:
    resolved_artifacts_root = artifacts_root_dir.resolve()
    resolved_path = path.resolve()

    if resolved_artifacts_root not in resolved_path.parents and resolved_path != resolved_artifacts_root:
        raise GenerationArtifactPolicyError(
            "Generation artifact outputs must be written under artifacts/agent/generation"
        )

    if resolved_path.suffix.lower() in FORBIDDEN_GENERATION_ARTIFACT_SUFFIXES:
        raise GenerationArtifactPolicyError(
            "Never write source code into artifacts/. Artifacts are only for immutable outputs/evidence."
        )

    return resolved_path


def _bundle_file_path(run_context: GenerationRunContext, filename: str) -> Path:
    return ensure_generation_artifact_output_path(
        run_context.artifact_dir / filename,
        run_context.artifacts_root_dir,
    )


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    write_text_file(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _write_manifest_json(run_context: GenerationRunContext) -> Path:
    target_path = _bundle_file_path(run_context, MANIFEST_FILENAME)
    payload = {
        "run_id": run_context.run_id,
        "source_id": run_context.source_id,
        "project": run_context.project,
        "workspace_root": str(run_context.workspace_root),
        "run_state_dir": str(run_context.run_state_dir),
        "artifact_dir": str(run_context.artifact_dir),
        "layout_version": 1,
        "bundle": {
            "manifest_path": str(target_path),
            "context_path": str(run_context.artifact_dir / CONTEXT_FILENAME),
            "source_input_path": str(run_context.artifact_dir / SOURCE_INPUT_FILENAME),
            "normalized_source_path": str(run_context.artifact_dir / NORMALIZED_SOURCE_FILENAME),
            "normalized_plan_path": str(run_context.artifact_dir / NORMALIZED_PLAN_FILENAME),
            "traceability_map_path": str(run_context.artifact_dir / TRACEABILITY_MAP_FILENAME),
            "diagnostics_path": str(run_context.artifact_dir / DIAGNOSTICS_FILENAME),
            "evidence_bundle_path": str(run_context.artifact_dir / EVIDENCE_BUNDLE_FILENAME),
            "enriched_plan_path": str(run_context.artifact_dir / ENRICHED_PLAN_FILENAME),
            "enrichment_result_path": str(run_context.artifact_dir / ENRICHMENT_RESULT_FILENAME),
            "applied_evidence_path": str(run_context.artifact_dir / APPLIED_EVIDENCE_FILENAME),
            "unapplied_evidence_path": str(run_context.artifact_dir / UNAPPLIED_EVIDENCE_FILENAME),
            "summary_path": str(run_context.artifact_dir / SUMMARY_FILENAME),
        },
        "run_state": {
            "context_path": str(run_context.run_state_dir / CONTEXT_FILENAME),
            "evidence_path": str(run_context.run_state_dir / EVIDENCE_RUN_STATE_FILENAME),
            "summary_path": str(run_context.run_state_dir / SUMMARY_FILENAME),
        },
    }
    _write_json_file(target_path, payload)
    return target_path
