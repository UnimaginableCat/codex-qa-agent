"""CLI entrypoint for batch scenario directory execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.cli_guard import bootstrap_workspace_cli


_WORKSPACE_ROOT = bootstrap_workspace_cli(__file__, payload_kind="execution_result")

from tools.common.errors import ValidationError
from tools.common.result import ExecutionResult
from tools.common.runtime import UnsupportedPythonVersionError, ensure_supported_python_version
from tools.common.statuses import StepStatus
from tools.scenario_runner.batch import ScenarioBatchRunnerService
from tools.scenario_runner.domain.manual import RunMode
from tools.scenario_runner.runtime.redaction import redact_sensitive_data


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.scenario_runner.batch_cli",
        description="Run every markdown scenario in a directory and aggregate the results.",
    )
    parser.add_argument("--scenario-dir", required=True, help="Directory containing markdown scenarios")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in RunMode],
        default=RunMode.GUIDED.value,
        help="Run mode for each scenario. Defaults to guided for operator-safe batch execution.",
    )
    return parser


def _print_error_result(message: str, details: dict[str, object] | None = None) -> int:
    result = ExecutionResult(
        status=StepStatus.ERROR,
        message=message,
        details=details or {},
    )
    print(json.dumps(redact_sensitive_data(result.to_dict()), ensure_ascii=False))
    return 1


def _print_payload(payload: dict[str, object]) -> None:
    print(json.dumps(redact_sensitive_data(payload), ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    try:
        ensure_supported_python_version()
    except UnsupportedPythonVersionError as exc:
        return _print_error_result(
            str(exc),
            details={
                "current_python": exc.current_version_text,
                "requires_python": f">={exc.minimum_version_text}",
            },
        )

    parser = _build_parser()
    args = parser.parse_args(argv)
    run_mode = RunMode(args.mode)
    service = ScenarioBatchRunnerService()

    try:
        result = service.run_scenario_dir(Path(args.scenario_dir), run_mode=run_mode)
    except ValidationError as exc:
        return _print_error_result(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _print_error_result(f"Scenario batch runner failed: {exc}")

    payload: dict[str, object] = {"batch_summary": result.batch_summary.to_dict()}
    if result.paused_summary is not None and result.operator_state is not None:
        payload["summary"] = result.paused_summary.to_dict()
        payload["operator_state"] = result.operator_state.to_dict()
    _print_payload(payload)
    return 0 if result.batch_summary.final_status == StepStatus.PASS or result.batch_summary.resumable else 1


if __name__ == "__main__":
    raise SystemExit(main())
