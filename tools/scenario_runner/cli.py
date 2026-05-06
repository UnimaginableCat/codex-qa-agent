"""CLI entrypoint for the reusable scenario runner skeleton."""

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
from tools.scenario_runner.domain.manual import RunMode
from tools.scenario_runner.parser import MarkdownScenarioParser
from tools.scenario_runner.orchestration.services import ScenarioRunnerService
from tools.scenario_runner.projections.operator import build_operator_guidance_from_summary
from tools.scenario_runner.runtime.redaction import redact_sensitive_data


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.scenario_runner.cli",
        description="Run scenarios and operate guided/manual pause-resume workflows.",
    )
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--scenario", help="Path to the scenario file")
    command.add_argument("--inspect-pause", help="Path to an active pause-state.json file")
    command.add_argument("--resume", help="Path to an active pause-state.json file to resume")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in RunMode],
        default=None,
        help="Run mode for scenario execution. Defaults to auto for --scenario and guided for manual commands.",
    )
    parser.add_argument(
        "--action",
        "--selected-action-id",
        dest="selected_action_id",
        help="Operator action_id to use with --resume.",
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


def _resolve_run_mode(raw_mode: str | None, *, default: RunMode) -> RunMode:
    return default if raw_mode is None else RunMode(raw_mode)


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

    runner_service = ScenarioRunnerService()

    try:
        if args.inspect_pause is not None:
            run_mode = _resolve_run_mode(args.mode, default=RunMode.GUIDED)
            operator_state = runner_service.inspect_pause_state(
                Path(args.inspect_pause),
                run_mode=run_mode,
            )
            _print_payload({"operator_state": operator_state.to_dict()})
            return 0 if operator_state.resumable else 1

        if args.resume is not None:
            if not args.selected_action_id:
                raise ValidationError("--resume requires --action <action_id>.")
            run_mode = _resolve_run_mode(args.mode, default=RunMode.GUIDED)
            summary = runner_service.resume(
                Path(args.resume),
                selected_action_id=args.selected_action_id,
                run_mode=run_mode,
            )
            operator_state = build_operator_guidance_from_summary(summary, run_mode=run_mode)
            _print_payload(
                {
                    "summary": summary.to_dict(),
                    "operator_state": operator_state.to_dict(),
                }
            )
            return 0 if summary.final_status == StepStatus.PASS or summary.resumable else 1

        parser_service = MarkdownScenarioParser()
        run_mode = _resolve_run_mode(args.mode, default=RunMode.AUTO)
        scenario_definition = parser_service.parse(Path(args.scenario))
        summary = runner_service.run(scenario_definition=scenario_definition, run_mode=run_mode)
    except ValidationError as exc:
        return _print_error_result(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _print_error_result(f"Scenario runner failed: {exc}")

    if run_mode == RunMode.AUTO:
        _print_payload(summary.to_dict())
    else:
        operator_state = build_operator_guidance_from_summary(summary, run_mode=run_mode)
        _print_payload(
            {
                "summary": summary.to_dict(),
                "operator_state": operator_state.to_dict(),
            }
        )
    return 0 if summary.final_status == StepStatus.PASS or (run_mode != RunMode.AUTO and summary.resumable) else 1


if __name__ == "__main__":
    raise SystemExit(main())
