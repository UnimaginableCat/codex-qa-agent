#!/usr/bin/env python3
"""CLI entrypoint for read-only DB query execution."""

from __future__ import annotations

import json
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common import ExecutionResult, StepStatus
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

    if len(sys.argv) != 3:
        return _print_error_result(
            "Usage: python tools/db/query_check.py <env_file> <step_json>"
        )

    from tools.db import build_runner

    env_file = Path(sys.argv[1])
    step_file = Path(sys.argv[2])

    runner = build_runner()
    result = runner.run(env_file=env_file, step_file=step_file)

    print(json.dumps(result.to_dict(), ensure_ascii=False))
    return 1 if result.status == StepStatus.ERROR else 0


if __name__ == "__main__":
    raise SystemExit(main())
