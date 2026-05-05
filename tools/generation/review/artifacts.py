"""Generation artifact loading and consistency checks."""

from __future__ import annotations

from pathlib import Path

from tools.common.io import read_json_file
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic, GenerationRunContext
from tools.generation.persistence.artifacts import GENERATION_ARTIFACTS_DIRNAME
from tools.generation.rendering.models import ScenarioRenderResult


def _load_run_context(workspace_root: Path, run_id: str) -> GenerationRunContext:
    artifacts_root = workspace_root / GENERATION_ARTIFACTS_DIRNAME
    exact_match = artifacts_root / run_id
    if exact_match.is_dir():
        matches = [exact_match]
    else:
        matches = sorted(path for path in artifacts_root.glob(f"*-{run_id}") if path.is_dir())
    if not matches:
        raise FileNotFoundError(f"Generation artifact bundle for run_id '{run_id}' was not found.")
    if len(matches) > 1:
        raise ValueError(f"Multiple generation artifact bundles matched run_id '{run_id}'.")
    context_path = matches[0] / "context.json"
    payload = read_json_file(context_path, "Generation run context")
    return GenerationRunContext.from_dict(dict(payload))

def _load_render_result(run_context: GenerationRunContext) -> ScenarioRenderResult:
    payload = read_json_file(run_context.artifact_dir / "scenario-render-result.json", "Scenario render result")
    return ScenarioRenderResult.from_dict(dict(payload))

def _run_context_consistency_diagnostics(run_context: GenerationRunContext) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if _is_placeholder_generation_value(run_context.source_id) or _is_placeholder_generation_value(run_context.project):
        diagnostics.append(
            GenerationDiagnostic(
                code="scenario_promotion_run_context_placeholder_metadata",
                message=(
                    "Generation run context still contains scaffold placeholder source_id/project metadata. "
                    "Regenerate or repair the managed generation step instead of editing context.json/manifest.json by hand."
                ),
                severity=DiagnosticSeverity.ERROR,
                source_ref=str(run_context.artifact_dir / "context.json"),
                details={"source_id": run_context.source_id, "project": run_context.project},
            )
        )

    agent_plan_path = run_context.artifact_dir / "agent-plan.json"
    if agent_plan_path.exists():
        try:
            agent_plan = read_json_file(agent_plan_path, "Agent plan")
            agent_source_id = str(agent_plan.get("source_id") or "")
            agent_project = str(agent_plan.get("project") or "")
            mismatches = {}
            if agent_source_id and agent_source_id != run_context.source_id:
                mismatches["source_id"] = {
                    "context": run_context.source_id,
                    "agent_plan": agent_source_id,
                }
            if agent_project and agent_project != run_context.project:
                mismatches["project"] = {
                    "context": run_context.project,
                    "agent_plan": agent_project,
                }
            if mismatches:
                diagnostics.append(
                    GenerationDiagnostic(
                        code="scenario_promotion_run_context_agent_plan_mismatch",
                        message=(
                            "Generation run context metadata does not match agent-plan.json. "
                            "Promotion target naming would be based on stale metadata."
                        ),
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=str(run_context.artifact_dir),
                        details=mismatches,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_agent_plan_metadata_unreadable",
                    message=f"Could not verify agent-plan.json metadata before promotion: {exc}",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(agent_plan_path),
                )
            )
    return diagnostics

def _is_placeholder_generation_value(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or normalized.startswith("replace-") or "replace_" in normalized
