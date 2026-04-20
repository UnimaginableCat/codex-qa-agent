#!/usr/bin/env python3
"""Build a markdown QA report from a summary JSON file."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ReportBuildError(Exception):
    """Base exception for report builder errors."""


class SummaryLoadError(ReportBuildError):
    """Raised when summary JSON cannot be loaded."""


class SummaryValidationError(ReportBuildError):
    """Raised when summary JSON has invalid structure."""


@dataclass(slots=True)
class CheckResult:
    name: str
    status: str
    detail: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "CheckResult":
        name = str(payload.get("name", "")).strip() or "Unnamed check"
        status = str(payload.get("status", "")).strip() or "UNKNOWN"

        detail_raw = payload.get("detail")
        detail = str(detail_raw).strip() if detail_raw is not None else None
        if detail == "":
            detail = None

        return cls(
            name=name,
            status=status,
            detail=detail,
        )


@dataclass(slots=True)
class SummaryData:
    final_status: str
    notes: list[str] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    executive_summary: str | None = None
    code_analysis_summary: str | None = None
    blockers: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "SummaryData":
        if not isinstance(payload, dict):
            raise SummaryValidationError("Summary JSON must be an object")

        final_status = str(payload.get("final_status", "")).strip() or "UNKNOWN"

        notes = cls._read_string_list(payload, "notes")
        blockers = cls._read_string_list(payload, "blockers")
        assumptions = cls._read_string_list(payload, "assumptions")
        artifacts = cls._read_string_list(payload, "artifacts")

        checks_raw = payload.get("checks") or []
        if not isinstance(checks_raw, list):
            raise SummaryValidationError("Field 'checks' must be an array")

        checks: list[CheckResult] = []
        for item in checks_raw:
            if not isinstance(item, dict):
                raise SummaryValidationError("Each item in 'checks' must be an object")
            checks.append(CheckResult.from_mapping(item))

        executive_summary = cls._read_optional_string(payload, "executive_summary")
        code_analysis_summary = cls._read_optional_string(payload, "code_analysis_summary")

        return cls(
            final_status=final_status,
            notes=notes,
            checks=checks,
            executive_summary=executive_summary,
            code_analysis_summary=code_analysis_summary,
            blockers=blockers,
            assumptions=assumptions,
            artifacts=artifacts,
        )

    @staticmethod
    def _read_string_list(payload: dict[str, Any], field_name: str) -> list[str]:
        raw_value = payload.get(field_name) or []
        if not isinstance(raw_value, list):
            raise SummaryValidationError(f"Field '{field_name}' must be an array")

        values: list[str] = []
        for item in raw_value:
            values.append(str(item).strip())
        return [item for item in values if item]

    @staticmethod
    def _read_optional_string(payload: dict[str, Any], field_name: str) -> str | None:
        raw_value = payload.get(field_name)
        if raw_value is None:
            return None

        value = str(raw_value).strip()
        return value or None


@dataclass(slots=True)
class ReportContext:
    project: str
    scenario: str
    summary: SummaryData


class SummaryLoader:
    """Loads and validates summary JSON."""

    def load(self, summary_path: Path) -> SummaryData:
        if not summary_path.exists():
            raise SummaryLoadError(f"Summary file does not exist: {summary_path}")

        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise SummaryLoadError(f"Failed to parse summary JSON '{summary_path}': {exc}") from exc

        return SummaryData.from_mapping(payload)


class MarkdownReportRenderer:
    """Renders a QA report as markdown."""

    def render(self, context: ReportContext) -> str:
        lines: list[str] = [
            f"# QA Report: {context.scenario}",
            "",
            f"- Project: `{context.project}`",
            f"- Scenario: `{context.scenario}`",
            f"- Final status: `{context.summary.final_status}`",
        ]

        if context.summary.executive_summary:
            lines.extend(
                [
                    "",
                    "## Executive summary",
                    context.summary.executive_summary,
                ]
            )

        if context.summary.code_analysis_summary:
            lines.extend(
                [
                    "",
                    "## Code analysis summary",
                    context.summary.code_analysis_summary,
                ]
            )

        lines.extend(["", "## Notes"])
        lines.extend(self._render_string_list(context.summary.notes))

        lines.extend(["", "## Checks"])
        lines.extend(self._render_checks(context.summary.checks))

        lines.extend(["", "## Blockers"])
        lines.extend(self._render_string_list(context.summary.blockers))

        lines.extend(["", "## Assumptions"])
        lines.extend(self._render_string_list(context.summary.assumptions))

        lines.extend(["", "## Artifacts"])
        lines.extend(self._render_string_list(context.summary.artifacts))

        return "\n".join(lines) + "\n"

    @staticmethod
    def _render_string_list(items: list[str]) -> list[str]:
        if not items:
            return ["- None"]
        return [f"- {item}" for item in items]

    @staticmethod
    def _render_checks(checks: list[CheckResult]) -> list[str]:
        if not checks:
            return ["- None"]

        lines: list[str] = []
        for check in checks:
            line = f"- `{check.status}` {check.name}"
            if check.detail:
                line += f": {check.detail}"
            lines.append(line)
        return lines


class ReportWriter:
    """Writes report content to disk."""

    def write(self, output_path: Path, content: str) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")


class ReportBuildService:
    """Coordinates summary loading, markdown rendering, and file output."""

    def __init__(
        self,
        summary_loader: SummaryLoader,
        renderer: MarkdownReportRenderer,
        writer: ReportWriter,
    ) -> None:
        self._summary_loader = summary_loader
        self._renderer = renderer
        self._writer = writer

    def build(self, project: str, scenario: str, summary_path: Path, output_path: Path) -> Path:
        summary = self._summary_loader.load(summary_path)

        context = ReportContext(
            project=project,
            scenario=scenario,
            summary=summary,
        )

        content = self._renderer.render(context)
        self._writer.write(output_path, content)

        return output_path


def build_service() -> ReportBuildService:
    return ReportBuildService(
        summary_loader=SummaryLoader(),
        renderer=MarkdownReportRenderer(),
        writer=ReportWriter(),
    )


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

    service = build_service()

    try:
        written_path = service.build(
            project=project,
            scenario=scenario,
            summary_path=summary_path,
            output_path=output_path,
        )
    except SummaryLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except SummaryValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Failed to build report: {exc}", file=sys.stderr)
        return 1

    print(written_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())