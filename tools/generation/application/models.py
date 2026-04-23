"""Application request contracts for test-plan generation use cases."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.generation.domain.models import GenerationSourceInput
from tools.generation.evidence.models import CodeFactsScope


class GenerationOutputMode(StrEnum):
    TEST_PLAN = "test_plan"


@dataclass(slots=True)
class GenerateTestPlanOptions:
    """Conservative Phase 1 options for test-plan generation."""

    persist_artifacts: bool = True
    allow_empty_plan: bool = False
    enrichment_enabled: bool = False
    collect_code_facts: bool = False
    render_scenario_drafts: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))


@dataclass(slots=True)
class GenerateTestPlanRequest:
    """Stable application input for Phase 1 test-plan generation."""

    source_input: GenerationSourceInput
    workspace_root: Path | None = None
    project_path: Path | None = None
    evidence_scope: CodeFactsScope | None = None
    output_mode: GenerationOutputMode = GenerationOutputMode.TEST_PLAN
    options: GenerateTestPlanOptions = field(default_factory=GenerateTestPlanOptions)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))
