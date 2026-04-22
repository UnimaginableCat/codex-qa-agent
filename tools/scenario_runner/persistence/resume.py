"""Pause-state loading and session restoration helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.common import ValidationError, read_json_file
from tools.common.statuses import StepStatus

from ..domain.execution import (
    AbortDisposition,
    CompletionDisposition,
    ExecutionEvent,
    ExecutionIssue,
    ExecutionIssueKind,
    ExecutionOutcome,
    ExecutionPhase,
    RunTermination,
    RunTerminationKind,
    ScenarioRunLifecycleState,
    ScenarioRunState,
    SkipDisposition,
    StepExecutionLifecycleState,
    StepExecutionState,
    StepReference,
    StepTermination,
    StepTerminationKind,
    TerminationReason,
    TerminationReasonSource,
)
from ..domain.models import (
    ApiStepDefinition,
    DbStepDefinition,
    ExpectationCheckResult,
    RunContext,
    ScenarioDefinition,
    ScenarioStep,
    ScenarioStepType,
    ScenarioVariableDefinition,
    ScenarioVariableSource,
    StepExecutionResult,
)
from ..domain.pause import PauseState
from ..orchestration.compiler import CompileCheckResult
from ..orchestration.engine import ScenarioExecutionSession
from ..orchestration.preflight import PreflightCheckResult


def load_pause_state(path: Path) -> PauseState:
    payload = read_json_file(path, "Pause state")
    if not isinstance(payload, dict):
        raise ValidationError("Pause state JSON must be an object")
    pause_state = PauseState.from_mapping(payload)
    pause_state.set_path(path)
    return pause_state


def restore_session_from_pause_state(
    pause_state: PauseState,
    *,
    scenario_definition: ScenarioDefinition | None = None,
) -> tuple[ScenarioDefinition, ScenarioExecutionSession]:
    snapshot = dict(pause_state.snapshot)
    restored_scenario = scenario_definition or _scenario_definition_from_mapping(snapshot.get("scenario_definition") or {})
    run_context = _run_context_from_mapping(snapshot.get("run_context") or {})
    run_state = _run_state_from_mapping(snapshot.get("run_state") or {})
    session = ScenarioExecutionSession(
        run_context=run_context,
        run_state=run_state,
        tooling_issues=[
            _execution_issue_from_mapping(item)
            for item in snapshot.get("tooling_issues") or []
            if isinstance(item, dict)
        ],
        compile_outcomes=[
            _execution_outcome_from_mapping(item)
            for item in snapshot.get("compile_outcomes") or []
            if isinstance(item, dict)
        ],
        compile_checks=[
            CompileCheckResult(
                name=str(item.get("name", "")).strip(),
                status=StepStatus(str(item.get("status", StepStatus.PASS.value))),
                message=str(item.get("message", "")).strip(),
                details=dict(item.get("details") or {}),
            )
            for item in snapshot.get("compile_checks") or []
            if isinstance(item, dict)
        ],
        preflight_outcomes=[
            _execution_outcome_from_mapping(item)
            for item in snapshot.get("preflight_outcomes") or []
            if isinstance(item, dict)
        ],
        preflight_checks=[
            PreflightCheckResult(
                name=str(item.get("name", "")).strip(),
                status=StepStatus(str(item.get("status", StepStatus.PASS.value))),
                message=str(item.get("message", "")).strip(),
                details=dict(item.get("details") or {}),
            )
            for item in snapshot.get("preflight_checks") or []
            if isinstance(item, dict)
        ],
        execution_events=[],
    )
    session.pause_state = pause_state
    session.decision_resolution = pause_state.decision_resolution
    return restored_scenario, session


def _scenario_definition_from_mapping(payload: dict[str, Any]) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_path=Path(str(payload.get("scenario_path", ""))),
        scenario_slug=str(payload.get("scenario_slug", "")).strip(),
        scenario_name=str(payload.get("scenario_name", "")).strip(),
        project=str(payload.get("project", "")).strip(),
        environment=str(payload.get("environment", "")).strip(),
        goal=str(payload.get("goal", "")).strip(),
        preconditions=[str(item) for item in payload.get("preconditions") or []],
        notes=str(payload.get("notes", "")),
        final_expectations=[str(item) for item in payload.get("final_expectations") or []],
        report_output=str(payload.get("report_output", "")),
        variables=[
            ScenarioVariableDefinition(
                name=str(item.get("name", "")).strip(),
                raw_value=str(item.get("raw_value", "")).strip(),
                source=ScenarioVariableSource(str(item.get("source", ScenarioVariableSource.LITERAL.value))),
                env_name=str(item.get("env_name", "")).strip() or None,
                source_name=str(item.get("source_name", "")).strip() or None,
                transforms=[str(transform) for transform in item.get("transforms") or []],
            )
            for item in payload.get("variables") or []
            if isinstance(item, dict)
        ],
        steps=[
            _scenario_step_from_mapping(item)
            for item in payload.get("steps") or []
            if isinstance(item, dict)
        ],
        metadata=dict(payload.get("metadata") or {}),
    )


def _scenario_step_from_mapping(payload: dict[str, Any]) -> ScenarioStep:
    api_payload = payload.get("api")
    db_payload = payload.get("db")
    return ScenarioStep(
        step_id=str(payload.get("step_id", "")).strip(),
        step_number=int(payload.get("step_number", 0)),
        title=str(payload.get("title", "")).strip(),
        step_type=ScenarioStepType(str(payload.get("step_type", ScenarioStepType.API.value))),
        api=(
            None
            if not isinstance(api_payload, dict)
            else ApiStepDefinition(
                name=str(api_payload.get("name", "")),
                method=str(api_payload.get("method", "")),
                path=str(api_payload.get("path", "")),
                description=str(api_payload.get("description", "")),
                headers=dict(api_payload.get("headers") or {}),
                params=dict(api_payload.get("params") or {}),
                body=api_payload.get("body"),
                retry=api_payload.get("retry"),
                capture=[str(item) for item in api_payload.get("capture") or []],
                expected=[str(item) for item in api_payload.get("expected") or []],
            )
        ),
        db=(
            None
            if not isinstance(db_payload, dict)
            else DbStepDefinition(
                name=str(db_payload.get("name", "")),
                sql=str(db_payload.get("sql", "")),
                description=str(db_payload.get("description", "")),
                params=dict(db_payload.get("params") or {}),
                capture=[str(item) for item in db_payload.get("capture") or []],
                expected=[str(item) for item in db_payload.get("expected") or []],
            )
        ),
        metadata=dict(payload.get("metadata") or {}),
    )


def _run_context_from_mapping(payload: dict[str, Any]) -> RunContext:
    return RunContext(
        run_id=str(payload.get("run_id", "")).strip(),
        workspace_root=Path(str(payload.get("workspace_root", ""))),
        scenario_path=Path(str(payload.get("scenario_path", ""))),
        scenario_slug=str(payload.get("scenario_slug", "")).strip(),
        scenario_name=str(payload.get("scenario_name", "")).strip(),
        parsed_plans_dir=Path(str(payload.get("parsed_plans_dir", ""))),
        compiled_plan_path=Path(str(payload.get("compiled_plan_path", ""))),
        runs_root_dir=Path(str(payload.get("runs_root_dir", ""))),
        run_state_dir=Path(str(payload.get("run_state_dir", ""))),
        artifacts_root_dir=Path(str(payload.get("artifacts_root_dir", ""))),
        artifact_dir=Path(str(payload.get("artifact_dir", ""))),
        started_at=str(payload.get("started_at", "")).strip(),
        variables=dict(payload.get("variables") or {}),
        step_results=[
            _step_result_from_mapping(item)
            for item in payload.get("step_results") or []
            if isinstance(item, dict)
        ],
    )


def _step_result_from_mapping(payload: dict[str, Any]) -> StepExecutionResult:
    return StepExecutionResult(
        step_id=str(payload.get("step_id", "")).strip(),
        step_number=int(payload.get("step_number", 0)),
        step_type=ScenarioStepType(str(payload.get("step_type", ScenarioStepType.API.value))),
        status=StepStatus(str(payload.get("status", StepStatus.ERROR.value))),
        message=str(payload.get("message", "")).strip(),
        expectation_results=[
            ExpectationCheckResult(
                rule=str(item.get("rule", "")).strip(),
                status=StepStatus(str(item.get("status", StepStatus.ERROR.value))),
                detail=str(item.get("detail", "")).strip() or None,
            )
            for item in payload.get("expectation_results") or []
            if isinstance(item, dict)
        ],
        details=dict(payload.get("details") or {}),
    )


def _run_state_from_mapping(payload: dict[str, Any]) -> ScenarioRunState:
    return ScenarioRunState(
        run_id=str(payload.get("run_id", "")).strip(),
        scenario_name=str(payload.get("scenario_name", "")).strip(),
        scenario_path=Path(str(payload.get("scenario_path", ""))),
        lifecycle_state=ScenarioRunLifecycleState(
            str(payload.get("lifecycle_state", ScenarioRunLifecycleState.READY.value))
        ),
        final_outcome=(
            None
            if not isinstance(payload.get("final_outcome"), dict)
            else _execution_outcome_from_mapping(payload["final_outcome"])
        ),
        termination=(
            None
            if not isinstance(payload.get("termination"), dict)
            else _run_termination_from_mapping(payload["termination"])
        ),
        current_step=(
            None if not isinstance(payload.get("current_step"), dict) else _step_reference_from_mapping(payload["current_step"])
        ),
        issues=[
            _execution_issue_from_mapping(item)
            for item in payload.get("issues") or []
            if isinstance(item, dict)
        ],
        step_states=[
            _step_execution_state_from_mapping(item)
            for item in payload.get("step_states") or []
            if isinstance(item, dict)
        ],
    )


def _step_reference_from_mapping(payload: dict[str, Any]) -> StepReference:
    return StepReference(
        step_id=str(payload.get("step_id", "")).strip(),
        step_number=int(payload.get("step_number", 0)),
        step_type=ScenarioStepType(str(payload.get("step_type", ScenarioStepType.API.value))),
    )


def _execution_outcome_from_mapping(payload: dict[str, Any]) -> ExecutionOutcome:
    raw_phase = payload.get("phase")
    return ExecutionOutcome(
        status=StepStatus(str(payload.get("status", StepStatus.ERROR.value))),
        message=str(payload.get("message", "")).strip(),
        phase=None if raw_phase in {None, ""} else ExecutionPhase(str(raw_phase)),
        details=dict(payload.get("details") or {}),
    )


def _execution_issue_from_mapping(payload: dict[str, Any]) -> ExecutionIssue:
    raw_outcome = payload.get("outcome")
    raw_step = payload.get("step")
    return ExecutionIssue(
        code=str(payload.get("code", "")).strip(),
        message=str(payload.get("message", "")).strip(),
        phase=ExecutionPhase(str(payload.get("phase", ExecutionPhase.STEP_EXECUTION.value))),
        issue_type=ExecutionIssueKind(str(payload.get("issue_type", ExecutionIssueKind.EXECUTION.value))),
        outcome=None if raw_outcome in {None, ""} else StepStatus(str(raw_outcome)),
        step=None if not isinstance(raw_step, dict) else _step_reference_from_mapping(raw_step),
        details=dict(payload.get("details") or {}),
    )


def _step_execution_state_from_mapping(payload: dict[str, Any]) -> StepExecutionState:
    raw_outcome = payload.get("outcome")
    raw_termination = payload.get("termination")
    return StepExecutionState(
        step=_step_reference_from_mapping(payload.get("step") or {}),
        lifecycle_state=StepExecutionLifecycleState(
            str(payload.get("lifecycle_state", StepExecutionLifecycleState.FINISHED.value))
        ),
        outcome=None if not isinstance(raw_outcome, dict) else _execution_outcome_from_mapping(raw_outcome),
        termination=(
            None
            if not isinstance(raw_termination, dict)
            else _step_termination_from_mapping(raw_termination)
        ),
        issues=[
            _execution_issue_from_mapping(item)
            for item in payload.get("issues") or []
            if isinstance(item, dict)
        ],
    )


def _termination_reason_from_mapping(payload: dict[str, Any]) -> TerminationReason:
    raw_phase = payload.get("phase")
    return TerminationReason(
        code=str(payload.get("code", "")).strip(),
        message=str(payload.get("message", "")).strip(),
        source=TerminationReasonSource(str(payload.get("source", TerminationReasonSource.EXECUTION.value))),
        phase=None if raw_phase in {None, ""} else ExecutionPhase(str(raw_phase)),
        details=dict(payload.get("details") or {}),
    )


def _step_termination_from_mapping(payload: dict[str, Any]) -> StepTermination:
    raw_outcome_status = payload.get("outcome_status")
    raw_skip_disposition = payload.get("skip_disposition")
    return StepTermination(
        kind=StepTerminationKind(str(payload.get("kind", StepTerminationKind.COMPLETED.value))),
        reason=_termination_reason_from_mapping(payload.get("reason") or {}),
        outcome_status=None if raw_outcome_status in {None, ""} else StepStatus(str(raw_outcome_status)),
        skip_disposition=None if raw_skip_disposition in {None, ""} else SkipDisposition(str(raw_skip_disposition)),
        operator_resolution=(
            None if not isinstance(payload.get("operator_resolution"), dict) else dict(payload["operator_resolution"])
        ),
        terminated_at=str(payload.get("terminated_at", "")).strip(),
    )


def _run_termination_from_mapping(payload: dict[str, Any]) -> RunTermination:
    raw_outcome_status = payload.get("outcome_status")
    raw_abort_disposition = payload.get("abort_disposition")
    return RunTermination(
        kind=RunTerminationKind(str(payload.get("kind", RunTerminationKind.COMPLETED.value))),
        reason=_termination_reason_from_mapping(payload.get("reason") or {}),
        completion_disposition=CompletionDisposition(
            str(payload.get("completion_disposition", CompletionDisposition.NONE.value))
        ),
        outcome_status=None if raw_outcome_status in {None, ""} else StepStatus(str(raw_outcome_status)),
        abort_disposition=None if raw_abort_disposition in {None, ""} else AbortDisposition(str(raw_abort_disposition)),
        operator_resolution=(
            None if not isinstance(payload.get("operator_resolution"), dict) else dict(payload["operator_resolution"])
        ),
        completed_step_count=int(payload.get("completed_step_count", 0)),
        total_step_count=int(payload.get("total_step_count", 0)),
        terminated_at=str(payload.get("terminated_at", "")).strip(),
    )
