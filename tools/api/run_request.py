#!/usr/bin/env python3
"""CLI entrypoint for API request execution."""

from __future__ import annotations

import json
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.api import build_runner
from tools.common import ExecutionResult, StepStatus


def main() -> int:
    if len(sys.argv) != 3:
        result = ExecutionResult(
            status=StepStatus.ERROR,
            message="Usage: python tools/api/run_request.py <env_file> <step_json>",
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False))
        return 1

    env_file = Path(sys.argv[1])
    step_file = Path(sys.argv[2])

    runner = build_runner()
    result = runner.run(env_file=env_file, step_file=step_file)

    print(json.dumps(result.to_dict(), ensure_ascii=False))
    return 1 if result.status == StepStatus.ERROR else 0


if __name__ == "__main__":
    raise SystemExit(main())
