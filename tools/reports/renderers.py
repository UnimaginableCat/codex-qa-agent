"""Markdown rendering for QA reports."""

from __future__ import annotations

from .models import CheckResult, ReportContext


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
            lines.extend(["", "## Executive summary", context.summary.executive_summary])

        if context.summary.code_analysis_summary:
            lines.extend(["", "## Code analysis summary", context.summary.code_analysis_summary])

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
