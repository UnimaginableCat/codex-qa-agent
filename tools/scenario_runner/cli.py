"""CLI entrypoint for the reusable scenario runner skeleton."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.errors import ValidationError
from tools.common.result import ExecutionResult
from tools.common.runtime import UnsupportedPythonVersionError, ensure_supported_python_version
from tools.common.statuses import StepStatus
from tools.scenario_runner.parser import MarkdownScenarioParser
from tools.scenario_runner.orchestration.services import ScenarioRunnerService
from tools.scenario_runner.runtime.redaction import redact_sensitive_data


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.scenario_runner.cli",
        description="Initialize reusable scenario runner state for a scenario file.",
    )
    parser.add_argument("--scenario", required=True, help="Path to the scenario file")
    return parser


def _print_error_result(message: str, details: dict[str, object] | None = None) -> int:
    result = ExecutionResult(
        status=StepStatus.ERROR,
        message=message,
        details=details or {},
    )
    print(json.dumps(redact_sensitive_data(result.to_dict()), ensure_ascii=False))
    return 1


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

    parser_service = MarkdownScenarioParser()
    runner_service = ScenarioRunnerService()

    try:
        scenario_definition = parser_service.parse(Path(args.scenario))
        summary = runner_service.run(scenario_definition=scenario_definition)
    except ValidationError as exc:
        return _print_error_result(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _print_error_result(f"Scenario runner failed: {exc}")

    print(json.dumps(redact_sensitive_data(summary.to_dict()), ensure_ascii=False))
    return 0 if summary.final_status == StepStatus.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
