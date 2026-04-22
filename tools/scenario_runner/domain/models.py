"""Typed models for the reusable scenario runner skeleton."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus

from .pause import RunContinuationState

if TYPE_CHECKING:
    from .guided import GuidedDiagnostic
    from .manual import AvailableOperatorAction, DecisionResolution
    from .pause import ResumeToken


class ScenarioStepType(StrEnum):
    API = "api"
    DB = "db"


class ScenarioVariableSource(StrEnum):
    RUNTIME = "runtime"
    ENV = "env"
    GENERATED = "generated"
    LITERAL = "literal"
    TEMPLATE = "template"
    DERIVED = "derived"


@dataclass(slots=True)
class ScenarioVariableDefinition:
    name: str
    raw_value: str = ""
    source: ScenarioVariableSource = ScenarioVariableSource.LITERAL
    env_name: str | None = None
    source_name: str | None = None
    transforms: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ApiStepDefinition:
    name: str = ""
    method: str = ""
    path: str = ""
    description: str = ""
    headers: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    retry: dict[str, Any] | None = None
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
        return to_json_safe(asdict(self))


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
        return to_json_safe(asdict(self))


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
    guided_diagnostics: list[GuidedDiagnostic] = field(default_factory=list)
    guided_stop_reason: GuidedDiagnostic | None = None
    continuation_state: "RunContinuationState" = field(default_factory=lambda: RunContinuationState.TERMINAL)
    resumable: bool = False
    resume_token: "ResumeToken | None" = None
    pause_state_path: Path | None = None
    available_operator_actions: list["AvailableOperatorAction"] = field(default_factory=list)
    decision_resolution: "DecisionResolution | None" = None
    resumed_from_pause: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = to_json_safe(asdict(self))
        payload["status"] = payload["final_status"]
        payload["final_status"] = payload["final_status"]
        payload["executive_summary"] = self.message
        payload["code_analysis_summary"] = (
            None if not self.code_analysis_used else "Code analysis was used during this run."
        )
        payload["notes"] = self.build_notes()
        payload["checks"] = self.build_report_checks()
        payload["blockers"] = self.build_blockers()
        payload["assumptions"] = list(self.assumptions)
        payload["artifacts"] = self.build_artifact_list()
        payload["guided_diagnostics"] = [diagnostic.to_dict() for diagnostic in self.guided_diagnostics]
        payload["guided_stop_reason"] = (
            None if self.guided_stop_reason is None else self.guided_stop_reason.to_dict()
        )
        payload["guided_decision_points"] = [
            diagnostic.decision_point.to_dict()
            for diagnostic in self.guided_diagnostics
            if diagnostic.decision_point is not None
        ]
        payload["continuation_state"] = self.continuation_state.value
        payload["resumable"] = self.resumable
        payload["resume_token"] = None if self.resume_token is None else self.resume_token.to_dict()
        payload["pause_state_path"] = None if self.pause_state_path is None else str(self.pause_state_path)
        payload["available_operator_actions"] = [
            action.to_dict() for action in self.available_operator_actions
        ]
        payload["decision_resolution"] = (
            None if self.decision_resolution is None else self.decision_resolution.to_dict()
        )
        payload["resumed_from_pause"] = self.resumed_from_pause
        return payload

    def build_notes(self) -> list[str]:
        notes = [
            f"Environment: {self.environment}",
            f"Run ID: {self.run_id}",
            f"Code analysis used: {self.code_analysis_used}",
        ]
        run_mode = self.details.get("run_mode")
        if isinstance(run_mode, str) and run_mode:
            notes.append(f"Run mode: {run_mode}")
        run_termination = self.details.get("run_termination")
        if isinstance(run_termination, dict):
            reason = run_termination.get("reason") or {}
            notes.append(
                "Run termination: "
                f"{run_termination.get('kind', 'unknown')} "
                f"({run_termination.get('completion_disposition', 'unknown')})"
            )
            if isinstance(reason, dict) and reason.get("message"):
                notes.append(f"Termination reason: {reason['message']}")
            notes.append(f"Termination source: {reason.get('source', 'unknown')}")
            if run_termination.get("partial"):
                notes.append(
                    "Partial completion: "
                    f"{run_termination.get('completed_step_count', 0)}/"
                    f"{run_termination.get('total_step_count', 0)} steps completed before stop"
                )
        notes.extend(self.tooling_issues)
        return notes

    def build_report_checks(self) -> list[dict[str, str | None]]:
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

    def build_blockers(self) -> list[str]:
        return [step.message for step in self.steps if step.status in {StepStatus.BLOCKED, StepStatus.ERROR}]

    def build_artifact_list(self) -> list[str]:
        artifacts = [str(self.artifact_dir), str(self.run_state_dir)]
        if self.report_path is not None:
            artifacts.append(str(self.report_path))
        if self.pause_state_path is not None:
            artifacts.append(str(self.pause_state_path))
        return artifacts
