"""Filesystem persistence for generation run artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.common.errors import ToolingError
from tools.common.io import read_json_file
from tools.common.io import write_text_file
from tools.generation.domain.models import (
    AgentTestPlanInput,
    GenerationDiagnostic,
    GenerationRunContext,
    GenerationSourceInput,
    NormalizedProseSource,
    NormalizedTestPlan,
    TraceabilityMap,
)
from tools.generation.enrichment.models import CoverageAssessmentResult, EnrichedTestPlanResult
from tools.generation.evidence.models import GenerationEvidenceBundle
from tools.generation.rendering.models import ScenarioDraftSet, ScenarioRenderResult
from tools.generation.review.models import ScenarioPromotionResult

GENERATION_ARTIFACTS_DIRNAME = Path("artifacts/agent/generation")
BUNDLE_LAYOUT_VERSION = 6
CONTEXT_FILENAME = "context.json"
AGENT_PLAN_FILENAME = "agent-plan.json"
SOURCE_INPUT_FILENAME = "source-input.json"
NORMALIZED_SOURCE_FILENAME = "normalized-source.json"
NORMALIZED_PLAN_FILENAME = "normalized-plan.json"
TRACEABILITY_MAP_FILENAME = "traceability-map.json"
DIAGNOSTICS_FILENAME = "diagnostics.json"
EVIDENCE_BUNDLE_FILENAME = "evidence-bundle.json"
ENRICHED_PLAN_FILENAME = "enriched-plan.json"
ENRICHMENT_RESULT_FILENAME = "enrichment-result.json"
APPLIED_EVIDENCE_FILENAME = "applied-evidence.json"
UNAPPLIED_EVIDENCE_FILENAME = "unapplied-evidence.json"
COVERAGE_ASSESSMENT_FILENAME = "coverage-assessment.json"
SCENARIO_DRAFTS_DIRNAME = "scenario-drafts"
SCENARIO_RENDER_RESULT_FILENAME = "scenario-render-result.json"
SCENARIO_PARSE_RESULTS_FILENAME = "scenario-parse-results.json"
UNSUPPORTED_CHECKS_FILENAME = "unsupported-checks.json"
DEFERRED_ITEMS_FILENAME = "deferred-items.json"
PROMOTION_RESULT_FILENAME = "promotion-result.json"
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
    artifacts_root_dir: Path


class FileGenerationArtifactStore:
    """Writes generation artifacts to a predictable filesystem bundle."""

    def write_context(self, run_context: GenerationRunContext) -> Path:
        target_path = _bundle_file_path(run_context, CONTEXT_FILENAME)
        payload = run_context.to_dict()
        _write_json_file(target_path, payload)
        self.write_manifest(run_context)
        return target_path

    def write_agent_plan(
        self,
        run_context: GenerationRunContext,
        agent_plan: AgentTestPlanInput,
    ) -> Path:
        target_path = _bundle_file_path(run_context, AGENT_PLAN_FILENAME)
        _write_json_file(target_path, agent_plan.to_dict())
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
        payload = evidence_bundle.to_dict()
        target_path = _bundle_file_path(run_context, EVIDENCE_BUNDLE_FILENAME)
        _write_json_file(target_path, payload)
        self.write_manifest(run_context)
        return target_path

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

    def write_coverage_assessment(
        self,
        run_context: GenerationRunContext,
        coverage_assessment: CoverageAssessmentResult,
    ) -> Path:
        target_path = _bundle_file_path(run_context, COVERAGE_ASSESSMENT_FILENAME)
        _write_json_file(target_path, coverage_assessment.to_dict())
        self.write_manifest(run_context)
        return target_path

    def write_scenario_drafts(
        self,
        run_context: GenerationRunContext,
        draft_set: ScenarioDraftSet,
    ) -> list[Path]:
        written_paths: list[Path] = []
        for draft in draft_set.drafts:
            target_path = _bundle_relative_path(run_context, draft.relative_path)
            write_text_file(target_path, draft.markdown)
            written_paths.append(target_path)
        self.write_manifest(run_context)
        return written_paths

    def write_scenario_render_result(
        self,
        run_context: GenerationRunContext,
        render_result: ScenarioRenderResult,
    ) -> Path:
        target_path = _bundle_file_path(run_context, SCENARIO_RENDER_RESULT_FILENAME)
        _write_json_file(target_path, render_result.to_dict())
        _write_json_file(
            _bundle_file_path(run_context, SCENARIO_PARSE_RESULTS_FILENAME),
            {
                "validation_results": [
                    validation.to_dict() for validation in render_result.validation_results
                ]
            },
        )
        _write_json_file(
            _bundle_file_path(run_context, UNSUPPORTED_CHECKS_FILENAME),
            {"unsupported_checks": [check.to_dict() for check in render_result.unsupported_checks]},
        )
        _write_json_file(
            _bundle_file_path(run_context, DEFERRED_ITEMS_FILENAME),
            {"deferred_items": [item.to_dict() for item in render_result.draft_set.deferred_items]},
        )
        self.write_manifest(run_context)
        return target_path

    def write_promotion_result(
        self,
        run_context: GenerationRunContext,
        promotion_result: ScenarioPromotionResult,
    ) -> Path:
        target_path = _bundle_file_path(run_context, PROMOTION_RESULT_FILENAME)
        _write_json_file(target_path, promotion_result.to_dict())
        self.write_manifest(run_context)
        return target_path

    def write_summary(self, run_context: GenerationRunContext, summary: dict[str, object]) -> Path:
        target_path = _bundle_file_path(run_context, SUMMARY_FILENAME)
        _write_json_file(target_path, summary)
        self.write_manifest(run_context)
        return target_path

    @staticmethod
    def write_manifest(run_context: GenerationRunContext) -> Path:
        return _write_manifest_json(run_context)


def ensure_generation_workspace_directories(workspace_root: Path) -> GenerationWorkspaceDirectories:
    artifacts_root_dir = workspace_root / GENERATION_ARTIFACTS_DIRNAME
    artifacts_root_dir.mkdir(parents=True, exist_ok=True)

    return GenerationWorkspaceDirectories(
        artifacts_root_dir=artifacts_root_dir,
    )


def create_generation_artifact_directory(artifacts_root_dir: Path, artifact_dir_name: str) -> Path:
    artifact_dir = artifacts_root_dir / artifact_dir_name
    artifact_dir.mkdir(parents=True, exist_ok=False)
    return artifact_dir


def managed_generation_artifacts_root_for_path(path: Path) -> Path | None:
    parts = path.parts
    normalized_parts = tuple(part.lower() for part in parts)
    root_parts = tuple(part.lower() for part in GENERATION_ARTIFACTS_DIRNAME.parts)
    width = len(root_parts)
    for index in range(len(normalized_parts) - width + 1):
        if normalized_parts[index:index + width] != root_parts:
            continue
        prefix = Path(*parts[:index]) if index else Path()
        return prefix / GENERATION_ARTIFACTS_DIRNAME
    return None


def load_generation_run_context_from_bundle_file(path: Path) -> GenerationRunContext | None:
    if path.name != AGENT_PLAN_FILENAME:
        return None
    artifacts_root_dir = managed_generation_artifacts_root_for_path(path)
    if artifacts_root_dir is None:
        return None
    context_path = path.parent / CONTEXT_FILENAME
    if not context_path.exists():
        return None
    payload = read_json_file(context_path, "Generation run context")
    return GenerationRunContext.from_dict(dict(payload))


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


def _bundle_relative_path(run_context: GenerationRunContext, relative_path: Path) -> Path:
    if relative_path.is_absolute():
        raise GenerationArtifactPolicyError("Generation artifact relative paths must not be absolute.")
    return ensure_generation_artifact_output_path(
        run_context.artifact_dir / relative_path,
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
        "bundle_dir": str(run_context.artifact_dir),
        "artifact_dir": str(run_context.artifact_dir),
        "layout_version": BUNDLE_LAYOUT_VERSION,
        "bundle": {
            "manifest_path": str(target_path),
            "context_path": str(run_context.artifact_dir / CONTEXT_FILENAME),
            "agent_plan_path": str(run_context.artifact_dir / AGENT_PLAN_FILENAME),
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
            "coverage_assessment_path": str(run_context.artifact_dir / COVERAGE_ASSESSMENT_FILENAME),
            "scenario_drafts_dir": str(run_context.artifact_dir / SCENARIO_DRAFTS_DIRNAME),
            "scenario_render_result_path": str(run_context.artifact_dir / SCENARIO_RENDER_RESULT_FILENAME),
            "scenario_parse_results_path": str(run_context.artifact_dir / SCENARIO_PARSE_RESULTS_FILENAME),
            "unsupported_checks_path": str(run_context.artifact_dir / UNSUPPORTED_CHECKS_FILENAME),
            "deferred_items_path": str(run_context.artifact_dir / DEFERRED_ITEMS_FILENAME),
            "promotion_result_path": str(run_context.artifact_dir / PROMOTION_RESULT_FILENAME),
            "summary_path": str(run_context.artifact_dir / SUMMARY_FILENAME),
        },
    }
    _write_json_file(target_path, payload)
    return target_path
