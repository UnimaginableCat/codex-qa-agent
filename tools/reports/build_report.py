#!/usr/bin/env python3
"""Build a simple markdown QA report from a summary JSON file."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 5:
        print(
            "Usage: python tools/reports/build_report.py <project> <scenario> <summary_json> <output_md>",
            file=sys.stderr,
        )
        return 1

    project, scenario, summary_json, output_md = sys.argv[1:]
    summary_path = Path(summary_json)
    output_path = Path(output_md)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    notes = summary.get("notes") or []
    checks = summary.get("checks") or []
    final_status = summary.get("final_status", "UNKNOWN")

    lines = [
        f"# QA Report: {scenario}",
        "",
        f"- Project: `{project}`",
        f"- Scenario: `{scenario}`",
        f"- Final status: `{final_status}`",
        "",
        "## Notes",
    ]

    if notes:
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("- None")

    lines.extend(["", "## Checks"])
    if checks:
        for check in checks:
            name = check.get("name", "Unnamed check")
            status = check.get("status", "UNKNOWN")
            detail = check.get("detail")
            line = f"- `{status}` {name}"
            if detail:
                line += f": {detail}"
            lines.append(line)
    else:
        lines.append("- None")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
