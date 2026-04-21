"""Scenario step executors built on top of existing API and DB CLIs."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import mkstemp
from typing import Any

from tools.common.statuses import StepStatus

from .artifacts import write_step_artifact_json
from .interpolator import InterpolationError, PlaceholderInterpolator
from .models import RunContext, ScenarioDefinition, ScenarioStep, ScenarioStepType, StepExecutionResult


class CaptureResolutionError(Exception):
    """Raised when a capture expression cannot be resolved from a step result."""


@dataclass(slots=True)
class StepExecutionOutcome:
    step_result: StepExecutionResult
    captured_values: dict[str, Any] = field(default_factory=dict)
    tool_payload: dict[str, Any] | None = None
    journal_details: dict[str, Any] = field(default_factory=dict)


class StepExecutorFactory:
    """Builds step executors for parsed scenario steps."""

    def __init__(self, interpolator: PlaceholderInterpolator | None = None) -> None:
        self._interpolator = interpolator or PlaceholderInterpolator()

    def create(self, step: ScenarioStep, workspace_root: Path) -> "_BaseStepExecutor":
        if step.step_type == ScenarioStepType.API:
            return ApiStepExecutor(workspace_root=workspace_root, interpolator=self._interpolator)
        return DbStepExecutor(workspace_root=workspace_root, interpolator=self._interpolator)


class _BaseStepExecutor:
    """Common subprocess execution flow for scenario steps."""

    def __init__(self, workspace_root: Path, interpolator: PlaceholderInterpolator) -> None:
        self._workspace_root = workspace_root
        self._interpolator = interpolator

    def execute(
        self,
        run_context: RunContext,
        scenario_definition: ScenarioDefinition,
        step: ScenarioStep,
    ) -> StepExecutionOutcome:
        try:
            step_payload = self._build_step_payload(run_context, step)
        except InterpolationError as exc:
            return StepExecutionOutcome(
                step_result=self._build_step_result(
                    step=step,
                    status=StepStatus.BLOCKED,
                    message=str(exc),
                ),
                journal_details={"phase": "interpolation"},
            )

        input_artifact_path = write_step_artifact_json(
            run_context=run_context,
            step_id=step.step_id,
            artifact_name="input.json",
            payload=step_payload,
        )

        env_path = self._resolve_environment_path(run_context.workspace_root, scenario_definition.environment)
        tool_result = self._run_cli(env_path=env_path, step_payload=step_payload)
        result_artifact_path = write_step_artifact_json(
            run_context=run_context,
            step_id=step.step_id,
            artifact_name="raw-result.json",
            payload=tool_result,
        )

        payload = tool_result.get("result")
        status = self._coerce_status(payload.get("status") if isinstance(payload, dict) else None)
        message = (
            str(payload.get("message"))
            if isinstance(payload, dict) and payload.get("message") is not None
            else "Tool execution failed"
        )

        captures: dict[str, Any] = {}
        if status == StepStatus.PASS:
            try:
                captures = self._apply_captures(step=step, payload=payload)
            except CaptureResolutionError as exc:
                status = StepStatus.FAIL
                message = str(exc)

        step_result = self._build_step_result(
            step=step,
            status=status,
            message=message,
            details={
                "input_artifact_path": str(input_artifact_path),
                "result_artifact_path": str(result_artifact_path),
                "tool_status": payload.get("status") if isinstance(payload, dict) else "ERROR",
                "capture_keys": sorted(captures.keys()),
                "tool_debug": tool_result.get("debug"),
                "api_request_debug": payload.get("request_debug") if isinstance(payload, dict) else None,
            },
        )

        return StepExecutionOutcome(
            step_result=step_result,
            captured_values=captures if status == StepStatus.PASS else {},
            tool_payload=payload if isinstance(payload, dict) else None,
            journal_details={
                "input_artifact_path": str(input_artifact_path),
                "result_artifact_path": str(result_artifact_path),
                "captures": sorted(captures.keys()),
                "tool_command": tool_result.get("command"),
                "tool_debug": tool_result.get("debug"),
                "api_request_debug": payload.get("request_debug") if isinstance(payload, dict) else None,
            },
        )

    def _run_cli(self, env_path: Path, step_payload: dict[str, Any]) -> dict[str, Any]:
        file_descriptor, raw_step_path = mkstemp(suffix=".json")
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as temp_step_file:
                json.dump(step_payload, temp_step_file, ensure_ascii=False)
                temp_step_file.flush()

            return self._invoke_cli(env_path=env_path, step_file=Path(raw_step_path))
        finally:
            Path(raw_step_path).unlink(missing_ok=True)

    def _invoke_cli(self, env_path: Path, step_file: Path) -> dict[str, Any]:
        command = [
            sys.executable,
            str(self._tool_script_path()),
            str(env_path),
            str(step_file),
        ]
        child_env = os.environ.copy()
        debug_metadata = self._subprocess_debug_metadata(child_env)

        try:
            completed = subprocess.run(
                command,
                cwd=self._workspace_root,
                env=child_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "command": command,
                "returncode": None,
                "stdout": "",
                "stderr": "",
                "debug": debug_metadata,
                "result": {
                    "status": StepStatus.ERROR.value,
                    "message": f"Failed to launch tool: {exc}",
                },
            }

        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "debug": debug_metadata,
            "result": self._parse_tool_payload(completed.stdout, completed.stderr, completed.returncode),
        }

    def _subprocess_debug_metadata(self, child_env: dict[str, str]) -> dict[str, Any]:
        return {
            "interpreter_path": sys.executable,
            "cwd": str(self._workspace_root),
            "VIRTUAL_ENV": child_env.get("VIRTUAL_ENV"),
            "PATH": child_env.get("PATH"),
            "HTTP_PROXY": _safe_child_env_debug_value(child_env, "HTTP_PROXY"),
            "HTTPS_PROXY": _safe_child_env_debug_value(child_env, "HTTPS_PROXY"),
            "NO_PROXY": child_env.get("NO_PROXY"),
            "REQUESTS_CA_BUNDLE": child_env.get("REQUESTS_CA_BUNDLE"),
            "SSL_CERT_FILE": child_env.get("SSL_CERT_FILE"),
        }

    def _parse_tool_payload(self, stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
        non_empty_lines = [line for line in stdout.splitlines() if line.strip()]
        if not non_empty_lines:
            stderr_lines = [line.strip() for line in stderr.splitlines() if line.strip()]
            error_suffix = f" stderr: {stderr_lines[-1]}" if stderr_lines else ""
            return {
                "status": StepStatus.ERROR.value,
                "message": f"Tool returned no structured JSON output.{error_suffix}",
                "stderr": stderr,
                "returncode": returncode,
            }

        candidate = non_empty_lines[-1]
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            return {
                "status": StepStatus.ERROR.value,
                "message": f"Tool returned invalid JSON: {exc.msg}",
                "stdout": stdout,
                "stderr": stderr,
                "returncode": returncode,
            }

        if not isinstance(payload, dict):
            return {
                "status": StepStatus.ERROR.value,
                "message": "Tool returned non-object JSON",
                "stdout": stdout,
                "stderr": stderr,
                "returncode": returncode,
            }

        return payload

    def _apply_captures(self, step: ScenarioStep, payload: dict[str, Any]) -> dict[str, Any]:
        capture_rules = self._capture_rules(step)
        if not capture_rules:
            return {}

        captures: dict[str, Any] = {}
        for capture_rule in capture_rules:
            source_expression, variable_name = self._parse_capture_rule(capture_rule)
            captures[variable_name] = self._resolve_capture_value(payload, source_expression)
        return captures

    def _resolve_capture_value(self, payload: dict[str, Any], expression: str) -> Any:
        if expression == "response.json":
            expression = "response.body"
        elif expression.startswith("response.json."):
            expression = "response.body." + expression.removeprefix("response.json.")

        current: Any = payload
        for segment in expression.split("."):
            if isinstance(current, dict):
                if segment not in current:
                    raise CaptureResolutionError(
                        f"Capture source '{expression}' could not be resolved: missing key '{segment}'."
                    )
                current = current[segment]
                continue
            if isinstance(current, list):
                if not segment.isdigit():
                    raise CaptureResolutionError(
                        f"Capture source '{expression}' could not be resolved: expected numeric list index at '{segment}'."
                    )
                index = int(segment)
                if index >= len(current):
                    raise CaptureResolutionError(
                        f"Capture source '{expression}' could not be resolved: list index {index} is out of range."
                    )
                current = current[index]
                continue
            raise CaptureResolutionError(
                f"Capture source '{expression}' could not be resolved beyond segment '{segment}'."
            )
        return current

    @staticmethod
    def _parse_capture_rule(capture_rule: str) -> tuple[str, str]:
        if "->" not in capture_rule:
            raise CaptureResolutionError(
                f"Invalid capture rule '{capture_rule}'. Expected format '<source> -> <variable_name>'."
            )
        source_expression, variable_name = (part.strip() for part in capture_rule.split("->", 1))
        if not source_expression or not variable_name:
            raise CaptureResolutionError(
                f"Invalid capture rule '{capture_rule}'. Expected format '<source> -> <variable_name>'."
            )
        return source_expression, variable_name

    @staticmethod
    def _resolve_environment_path(workspace_root: Path, environment_path: str) -> Path:
        if not environment_path.strip():
            return workspace_root / "__missing_env__"
        candidate = Path(environment_path)
        if candidate.is_absolute():
            return candidate
        return workspace_root / candidate

    @staticmethod
    def _coerce_status(raw_status: Any) -> StepStatus:
        try:
            return StepStatus(str(raw_status))
        except ValueError:
            return StepStatus.ERROR

    @staticmethod
    def _build_step_result(
        step: ScenarioStep,
        status: StepStatus,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> StepExecutionResult:
        return StepExecutionResult(
            step_id=step.step_id,
            step_number=step.step_number,
            step_type=step.step_type,
            status=status,
            message=message,
            details=details or {},
        )

    def _tool_script_path(self) -> Path:
        raise NotImplementedError

    def _build_step_payload(self, run_context: RunContext, step: ScenarioStep) -> dict[str, Any]:
        raise NotImplementedError

    def _capture_rules(self, step: ScenarioStep) -> list[str]:
        raise NotImplementedError


class ApiStepExecutor(_BaseStepExecutor):
    """Executes API steps through the existing API CLI tool."""

    def _tool_script_path(self) -> Path:
        return self._workspace_root / "tools" / "api" / "run_request.py"

    def _build_step_payload(self, run_context: RunContext, step: ScenarioStep) -> dict[str, Any]:
        if step.api is None:
            raise InterpolationError(f"Step '{step.step_id}' is missing API definition.")
        return {
            "method": self._interpolator.interpolate(step.api.method, run_context.variables),
            "path": self._interpolator.interpolate(step.api.path, run_context.variables),
            "headers": self._interpolator.interpolate(step.api.headers, run_context.variables),
            "query_params": self._interpolator.interpolate(step.api.params, run_context.variables),
            "body": self._interpolator.interpolate(step.api.body, run_context.variables),
        }

    def _capture_rules(self, step: ScenarioStep) -> list[str]:
        return [] if step.api is None else list(step.api.capture)


class DbStepExecutor(_BaseStepExecutor):
    """Executes DB steps through the existing DB CLI tool."""

    def _tool_script_path(self) -> Path:
        return self._workspace_root / "tools" / "db" / "query_check.py"

    def _build_step_payload(self, run_context: RunContext, step: ScenarioStep) -> dict[str, Any]:
        if step.db is None:
            raise InterpolationError(f"Step '{step.step_id}' is missing DB definition.")
        return {
            "sql": self._interpolator.interpolate(step.db.sql, run_context.variables),
            "params": self._interpolator.interpolate(step.db.params, run_context.variables),
        }

    def _capture_rules(self, step: ScenarioStep) -> list[str]:
        return [] if step.db is None else list(step.db.capture)


def _safe_child_env_debug_value(env: dict[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None:
        return None
    if key.upper() in {"HTTP_PROXY", "HTTPS_PROXY"}:
        return re.sub(r"(?<=://)[^/@]+@", "<redacted>@", value)
    return value
