"""Batch revalidation helpers."""

from __future__ import annotations

from pathlib import Path

from tools.generation.review.models import (
    ExecutionEnvironmentReadinessCategory,
    ExecutionReadinessCategory,
    ScenarioDraftParseStatus,
    ScenarioRevalidationResult,
)
from tools.scenario_runner.domain.models import ScenarioDefinition


def _revalidation_title(scenario: ScenarioDefinition | None, file_path: Path) -> str:
    if scenario is not None and scenario.scenario_name:
        return scenario.scenario_name
    return file_path.stem

def _batch_revalidation_readiness_key(result: ScenarioRevalidationResult) -> str:
    if result.environment_readiness_category is not None:
        return result.environment_readiness_category.value
    return result.execution_readiness_category.value

def _batch_revalidation_is_failure(result: ScenarioRevalidationResult, validation_mode: str) -> bool:
    if result.parse_status != ScenarioDraftParseStatus.VALID:
        return True
    if validation_mode == "compile":
        return result.execution_readiness_category not in {
            ExecutionReadinessCategory.COMPILE_VALID_RUNNER_READY,
            ExecutionReadinessCategory.COMPILE_VALID_BUT_INCOMPLETE,
        }
    if validation_mode == "preflight":
        return (
            result.environment_readiness_category
            != ExecutionEnvironmentReadinessCategory.PREFLIGHT_READY
        )
    return False

def _promotion_metadata(markdown: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if not markdown.lstrip().startswith("<!--"):
        return metadata
    end_index = markdown.find("-->")
    if end_index < 0:
        return metadata
    comment = markdown[:end_index]
    for line in comment.splitlines():
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key in {"generated_by", "generation_run_id", "draft_id", "source"}:
            metadata[key] = value
    if metadata.get("generated_by") != "codex-qa-agent":
        return {}
    return metadata
