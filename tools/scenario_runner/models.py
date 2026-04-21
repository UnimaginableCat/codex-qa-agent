"""Typed models for the reusable scenario runner skeleton."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any

from tools.common.statuses import StepStatus


class ScenarioStepType(StrEnum):
    API = "api"
    DB = "db"


class ScenarioVariableSource(StrEnum):
    RUNTIME = "runtime"
    ENV = "env"
    LITERAL = "literal"
    TEMPLATE = "template"


@dataclass(slots=True)
class ScenarioVariableDefinition:
    name: str
    raw_value: str = ""
    source: ScenarioVariableSource = ScenarioVariableSource.LITERAL
    env_name: str | None = None


@dataclass(slots=True)
class ApiStepDefinition:
    name: str = ""
    method: str = ""
    path: str = ""
    description: str = ""
    headers: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    capture: list[str] = field(default_factory=list)
    expected: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DbStepDefinition:
    name: str = ""
    sql: str = ""
    description: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    capture: list[str] = field(default_factory=list)
    expected: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScenarioStep:
    step_id: str
    step_number: int
    title: str
    step_type: ScenarioStepType
    api: ApiStepDefinition | None = None
    db: DbStepDefinition | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScenarioDefinition:
    scenario_path: Path
    scenario_slug: str
    scenario_name: str
    project: str = ""
    environment: str = ""
    goal: str = ""
    preconditions: list[str] = field(default_factory=list)
    notes: str = ""
    final_expectations: list[str] = field(default_factory=list)
    report_output: str = ""
    variables: list[ScenarioVariableDefinition] = field(default_factory=list)
    steps: list[ScenarioStep] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(asdict(self))


@dataclass(slots=True)
class RunContext:
    run_id: str
    workspace_root: Path
    scenario_path: Path
    scenario_slug: str
    scenario_name: str
    parsed_plans_dir: Path
    compiled_plan_path: Path
    runs_root_dir: Path
    run_state_dir: Path
    artifacts_root_dir: Path
    artifact_dir: Path
    started_at: str
    variables: dict[str, Any] = field(default_factory=dict)
    step_results: list[StepExecutionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(asdict(self))


@dataclass(slots=True)
class StepExecutionResult:
    step_id: str
    step_number: int
    step_type: ScenarioStepType
    status: StepStatus
    message: str
    expectation_results: list[ExpectationCheckResult] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExpectationCheckResult:
    rule: str
    status: StepStatus
    detail: str | None = None


@dataclass(slots=True)
class ScenarioExecutionSummary:
    scenario: str
    project: str
    environment: str
    run_id: str
    scenario_path: Path
    final_status: StepStatus
    message: str
    run_state_dir: Path
    artifact_dir: Path
    started_at: str
    finished_at: str
    report_path: Path | None = None
    steps: list[StepExecutionResult] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    tooling_issues: list[str] = field(default_factory=list)
    code_analysis_used: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = _serialize_value(asdict(self))
        payload["status"] = payload["final_status"]
        payload["final_status"] = payload["final_status"]
        payload["executive_summary"] = self.message
        payload["code_analysis_summary"] = (
            None if not self.code_analysis_used else "Code analysis was used during this run."
        )
        payload["notes"] = self._build_notes()
        payload["checks"] = self._build_report_checks()
        payload["blockers"] = [
            step.message for step in self.steps if step.status in {StepStatus.BLOCKED, StepStatus.ERROR}
        ]
        payload["assumptions"] = list(self.assumptions)
        payload["artifacts"] = self._build_artifact_list()
        return payload

    def _build_notes(self) -> list[str]:
        notes = [
            f"Environment: {self.environment}",
            f"Run ID: {self.run_id}",
            f"Code analysis used: {self.code_analysis_used}",
        ]
        notes.extend(self.tooling_issues)
        return notes

    def _build_report_checks(self) -> list[dict[str, str | None]]:
        checks: list[dict[str, str | None]] = []
        for step in self.steps:
            checks.append(
                {
                    "name": f"Step {step.step_number}: {step.step_id}",
                    "status": step.status.value,
                    "detail": step.message,
                }
            )
            for expectation_result in step.expectation_results:
                checks.append(
                    {
                        "name": f"Step {step.step_number} expectation: {expectation_result.rule}",
                        "status": expectation_result.status.value,
                        "detail": expectation_result.detail,
                    }
                )
        return checks

    def _build_artifact_list(self) -> list[str]:
        artifacts = [str(self.artifact_dir), str(self.run_state_dir)]
        if self.report_path is not None:
            artifacts.append(str(self.report_path))
        return artifacts


def _serialize_value(value: Any) -> Any:
    if is_dataclass(value):
        return _serialize_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    return value
