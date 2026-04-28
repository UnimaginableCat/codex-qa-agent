"""Batch execution helpers for scenario directory runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

from tools.common.errors import ValidationError
from tools.common.io import write_text_file
from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus

from .domain.manual import RunMode
from .domain.models import ScenarioExecutionSummary
from .domain.pause import RunContinuationState
from .orchestration.services import ScenarioRunnerService
from .parser import MarkdownScenarioParser
from .projections.operator import (
    OperatorGuidanceProjection,
    build_operator_guidance_from_summary,
)
from .projections.summary import resolve_final_status
from .runtime.redaction import redact_sensitive_data

SCENARIO_BATCHES_DIRNAME = Path("artifacts/agent/scenario-batches")


@dataclass(slots=True)
class ScenarioBatchItem:
    index: int
    scenario_path: Path
    scenario_name: str
    final_status: StepStatus
    message: str
    run_id: str | None = None
    continuation_state: RunContinuationState = RunContinuationState.TERMINAL
    resumable: bool = False
    run_state_dir: Path | None = None
    artifact_dir: Path | None = None
    report_path: Path | None = None
    pause_state_path: Path | None = None

    @classmethod
    def from_summary(cls, index: int, summary: ScenarioExecutionSummary) -> "ScenarioBatchItem":
        return cls(
            index=index,
            scenario_path=summary.scenario_path,
            scenario_name=summary.scenario,
            final_status=summary.final_status,
            message=summary.message,
            run_id=summary.run_id,
            continuation_state=summary.continuation_state,
            resumable=summary.resumable,
            run_state_dir=summary.run_state_dir,
            artifact_dir=summary.artifact_dir,
            report_path=summary.report_path,
            pause_state_path=summary.pause_state_path,
        )

    @classmethod
    def from_error(
        cls,
        index: int,
        scenario_path: Path,
        message: str,
        *,
        final_status: StepStatus = StepStatus.ERROR,
    ) -> "ScenarioBatchItem":
        return cls(
            index=index,
            scenario_path=scenario_path,
            scenario_name=scenario_path.stem,
            final_status=final_status,
            message=message,
        )

    def to_dict(self) -> dict[str, object]:
        return to_json_safe(
            {
                "index": self.index,
                "scenario_path": self.scenario_path,
                "scenario_name": self.scenario_name,
                "final_status": self.final_status.value,
                "message": self.message,
                "run_id": self.run_id,
                "continuation_state": self.continuation_state.value,
                "resumable": self.resumable,
                "run_state_dir": self.run_state_dir,
                "artifact_dir": self.artifact_dir,
                "report_path": self.report_path,
                "pause_state_path": self.pause_state_path,
            }
        )


@dataclass(slots=True)
class ScenarioBatchSummary:
    batch_id: str
    scenario_dir: Path
    workspace_root: Path
    run_mode: RunMode
    final_status: StepStatus
    continuation_state: RunContinuationState
    resumable: bool
    message: str
    started_at: str
    finished_at: str
    artifact_dir: Path
    summary_path: Path
    report_path: Path
    manifest_path: Path
    scenario_count_total: int
    scenario_count_executed: int
    scenario_count_remaining: int
    status_counts: dict[str, int]
    items: list[ScenarioBatchItem] = field(default_factory=list)
    remaining_scenarios: list[Path] = field(default_factory=list)
    paused_run_id: str | None = None
    paused_pause_state_path: Path | None = None

    def to_dict(self) -> dict[str, object]:
        return to_json_safe(
            {
                "batch_id": self.batch_id,
                "scenario_dir": self.scenario_dir,
                "workspace_root": self.workspace_root,
                "run_mode": self.run_mode.value,
                "final_status": self.final_status.value,
                "status": self.final_status.value,
                "continuation_state": self.continuation_state.value,
                "resumable": self.resumable,
                "message": self.message,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "artifact_dir": self.artifact_dir,
                "summary_path": self.summary_path,
                "report_path": self.report_path,
                "manifest_path": self.manifest_path,
                "scenario_count_total": self.scenario_count_total,
                "scenario_count_executed": self.scenario_count_executed,
                "scenario_count_remaining": self.scenario_count_remaining,
                "status_counts": dict(self.status_counts),
                "items": [item.to_dict() for item in self.items],
                "remaining_scenarios": self.remaining_scenarios,
                "paused_run_id": self.paused_run_id,
                "paused_pause_state_path": self.paused_pause_state_path,
                "artifacts": [
                    str(self.artifact_dir),
                    str(self.summary_path),
                    str(self.report_path),
                    str(self.manifest_path),
                ],
            }
        )


@dataclass(slots=True)
class ScenarioBatchExecutionResult:
    batch_summary: ScenarioBatchSummary
    paused_summary: ScenarioExecutionSummary | None = None
    operator_state: OperatorGuidanceProjection | None = None


class ScenarioBatchRunnerService:
    """Runs every scenario in a directory and produces an aggregate batch result."""

    def __init__(
        self,
        *,
        parser: MarkdownScenarioParser | None = None,
        runner_service: ScenarioRunnerService | None = None,
    ) -> None:
        self._parser = parser or MarkdownScenarioParser()
        self._runner_service = runner_service or ScenarioRunnerService()

    def run_scenario_dir(
        self,
        scenario_dir: Path,
        *,
        workspace_root: Path | None = None,
        run_mode: RunMode = RunMode.GUIDED,
    ) -> ScenarioBatchExecutionResult:
        resolved_workspace_root = (workspace_root or Path.cwd()).resolve()
        resolved_scenario_dir = scenario_dir.resolve()
        scenario_paths = self._discover_scenarios(resolved_scenario_dir)

        batch_id = _create_batch_id()
        batch_artifact_dir = resolved_workspace_root / SCENARIO_BATCHES_DIRNAME / batch_id
        summary_path = batch_artifact_dir / "summary.json"
        report_path = batch_artifact_dir / "report.md"
        manifest_path = batch_artifact_dir / "manifest.json"
        started_at = _utc_now_iso()

        items: list[ScenarioBatchItem] = []
        paused_summary: ScenarioExecutionSummary | None = None
        operator_state: OperatorGuidanceProjection | None = None

        for index, scenario_path in enumerate(scenario_paths, start=1):
            try:
                scenario_definition = self._parser.parse(scenario_path)
                summary = self._runner_service.run(
                    scenario_definition,
                    workspace_root=resolved_workspace_root,
                    run_mode=run_mode,
                )
            except Exception as exc:  # noqa: BLE001
                items.append(
                    ScenarioBatchItem.from_error(
                        index=index,
                        scenario_path=scenario_path,
                        message=f"Scenario batch execution failed for '{scenario_path.name}': {exc}",
                    )
                )
                continue

            items.append(ScenarioBatchItem.from_summary(index, summary))
            if run_mode != RunMode.AUTO and summary.resumable:
                paused_summary = summary
                operator_state = build_operator_guidance_from_summary(summary, run_mode=run_mode)
                break

        remaining_scenarios = scenario_paths[len(items) :]
        final_status = resolve_final_status([item.final_status for item in items])
        continuation_state = (
            RunContinuationState.PAUSED if paused_summary is not None else RunContinuationState.TERMINAL
        )
        resumable = paused_summary is not None and paused_summary.resumable
        finished_at = _utc_now_iso()
        status_counts = _count_statuses(items)
        message = _build_batch_message(
            final_status=final_status,
            total_count=len(scenario_paths),
            executed_count=len(items),
            paused_summary=paused_summary,
        )

        batch_summary = ScenarioBatchSummary(
            batch_id=batch_id,
            scenario_dir=resolved_scenario_dir,
            workspace_root=resolved_workspace_root,
            run_mode=run_mode,
            final_status=final_status,
            continuation_state=continuation_state,
            resumable=resumable,
            message=message,
            started_at=started_at,
            finished_at=finished_at,
            artifact_dir=batch_artifact_dir,
            summary_path=summary_path,
            report_path=report_path,
            manifest_path=manifest_path,
            scenario_count_total=len(scenario_paths),
            scenario_count_executed=len(items),
            scenario_count_remaining=len(remaining_scenarios),
            status_counts=status_counts,
            items=items,
            remaining_scenarios=remaining_scenarios,
            paused_run_id=None if paused_summary is None else paused_summary.run_id,
            paused_pause_state_path=None if paused_summary is None else paused_summary.pause_state_path,
        )
        _write_batch_artifacts(batch_summary)
        return ScenarioBatchExecutionResult(
            batch_summary=batch_summary,
            paused_summary=paused_summary,
            operator_state=operator_state,
        )

    @staticmethod
    def _discover_scenarios(scenario_dir: Path) -> list[Path]:
        if not scenario_dir.exists():
            raise ValidationError(f"Scenario directory does not exist: {scenario_dir}")
        if not scenario_dir.is_dir():
            raise ValidationError(f"Scenario directory path is not a directory: {scenario_dir}")

        scenario_paths = sorted(
            (path.resolve() for path in scenario_dir.rglob("*.md") if path.is_file()),
            key=lambda path: path.as_posix(),
        )
        if not scenario_paths:
            raise ValidationError(f"Scenario directory does not contain any .md files: {scenario_dir}")
        return scenario_paths


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _create_batch_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"batch-{timestamp}-{uuid4().hex[:8]}"


def _count_statuses(items: list[ScenarioBatchItem]) -> dict[str, int]:
    counts = {status.value: 0 for status in StepStatus}
    for item in items:
        counts[item.final_status.value] += 1
    return counts


def _build_batch_message(
    *,
    final_status: StepStatus,
    total_count: int,
    executed_count: int,
    paused_summary: ScenarioExecutionSummary | None,
) -> str:
    if paused_summary is not None:
        return (
            f"Scenario batch execution paused after {executed_count} of {total_count} scenarios. "
            f"Paused run: {paused_summary.run_id}."
        )
    if final_status == StepStatus.PASS:
        return f"Scenario batch execution completed for {executed_count} scenario(s)."
    return f"Scenario batch execution completed with status {final_status.value}."


def _write_batch_artifacts(summary: ScenarioBatchSummary) -> None:
    payload = redact_sensitive_data(summary.to_dict())
    write_text_file(summary.summary_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    write_text_file(summary.report_path, _build_batch_report(summary))
    write_text_file(summary.manifest_path, json.dumps(_build_batch_manifest(summary), ensure_ascii=False, indent=2) + "\n")


def _build_batch_manifest(summary: ScenarioBatchSummary) -> dict[str, object]:
    return redact_sensitive_data(
        to_json_safe(
            {
                "batch_id": summary.batch_id,
                "scenario_dir": summary.scenario_dir,
                "workspace_root": summary.workspace_root,
                "summary_path": summary.summary_path,
                "report_path": summary.report_path,
                "scenario_count_total": summary.scenario_count_total,
                "scenario_count_executed": summary.scenario_count_executed,
                "scenario_count_remaining": summary.scenario_count_remaining,
                "paused_run_id": summary.paused_run_id,
                "paused_pause_state_path": summary.paused_pause_state_path,
            }
        )
    )


def _build_batch_report(summary: ScenarioBatchSummary) -> str:
    lines = [
        f"# Scenario Batch: {summary.scenario_dir.name}",
        "",
        f"- Final status: `{summary.final_status.value}`",
        f"- Continuation state: `{summary.continuation_state.value}`",
        f"- Run mode: `{summary.run_mode.value}`",
        f"- Scenario directory: `{summary.scenario_dir}`",
        f"- Executed: `{summary.scenario_count_executed}/{summary.scenario_count_total}`",
        f"- PASS: `{summary.status_counts[StepStatus.PASS.value]}`",
        f"- FAIL: `{summary.status_counts[StepStatus.FAIL.value]}`",
        f"- BLOCKED: `{summary.status_counts[StepStatus.BLOCKED.value]}`",
        f"- ERROR: `{summary.status_counts[StepStatus.ERROR.value]}`",
        "",
        "## Summary",
        "",
        summary.message,
        "",
        "## Scenario Outcomes",
        "",
    ]

    for item in summary.items:
        lines.append(
            f"- `{item.index:02d}` `{item.final_status.value}` `{item.continuation_state.value}` "
            f"`{item.scenario_path.name}`"
        )
        if item.run_id:
            lines.append(f"  Run: `{item.run_id}`")
        if item.pause_state_path:
            lines.append(f"  Pause state: `{item.pause_state_path}`")
        if item.message:
            lines.append(f"  Message: {item.message}")

    if summary.remaining_scenarios:
        lines.extend(["", "## Remaining Scenarios", ""])
        for path in summary.remaining_scenarios:
            lines.append(f"- `{path.name}`")

    lines.append("")
    return "\n".join(lines)
