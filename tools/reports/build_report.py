#!/usr/bin/env python3
"""CLI entrypoint for QA report building."""

from __future__ import annotations

import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common import JsonFileLoadError, ValidationError
from tools.reports import build_service


def main() -> int:
    if len(sys.argv) != 5:
        print(
            "Usage: python tools/reports/build_report.py <project> <scenario> <summary_json> <output_md>",
            file=sys.stderr,
        )
        return 1

    project, scenario, summary_json, output_md = sys.argv[1:]

    service = build_service()

    try:
        written_path = service.build(
            project=project,
            scenario=scenario,
            summary_path=Path(summary_json),
            output_path=Path(output_md),
        )
    except JsonFileLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Failed to build report: {exc}", file=sys.stderr)
        return 1

    print(written_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
