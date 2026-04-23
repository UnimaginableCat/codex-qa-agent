"""Typed models for agent-plan authoring helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.domain.models import AgentTestPlanInput, GenerationDiagnostic


@dataclass(slots=True)
class AgentPlanLoadResult:
    """Structured outcome of loading one agent-authored plan file."""

    file_path: Path
    agent_plan: AgentTestPlanInput | None = None
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return to_json_safe(asdict(self))


@dataclass(slots=True)
class AgentPlanValidationResult:
    """Structured validation result for one agent-authored plan."""

    status: StepStatus
    message: str
    file_path: Path | None = None
    agent_plan: AgentTestPlanInput | None = None
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)
    case_count: int = 0

    def to_dict(self) -> dict[str, object]:
        payload = to_json_safe(asdict(self))
        payload["status"] = self.status.value
        return payload
