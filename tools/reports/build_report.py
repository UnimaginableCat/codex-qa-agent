#!/usr/bin/env python3
"""CLI entrypoint for QA report building."""

from __future__ import annotations

import json
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common import ExecutionResult, JsonFileLoadError, StepStatus, ValidationError
from tools.common.runtime import UnsupportedPythonVersionError, ensure_supported_python_version


def _print_error_result(message: str, details: dict[str, object] | None = None) -> int:
    result = ExecutionResult(
        status=StepStatus.ERROR,
        message=message,
        details=details or {},
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False))
    return 1


def main() -> int:
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

    if len(sys.argv) != 5:
        return _print_error_result(
            "Usage: python tools/reports/build_report.py <project> <scenario> <summary_json> <output_md>"
        )

    project, scenario, summary_json, output_md = sys.argv[1:]

    from tools.reports import build_service

    service = build_service()

    try:
        written_path = service.build(
            project=project,
            scenario=scenario,
            summary_path=Path(summary_json),
            output_path=Path(output_md),
        )
    except JsonFileLoadError as exc:
        return _print_error_result(str(exc))
    except ValidationError as exc:
        return _print_error_result(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _print_error_result(f"Failed to build report: {exc}")

    print(written_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
