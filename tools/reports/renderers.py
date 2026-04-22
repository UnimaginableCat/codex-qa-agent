"""Markdown rendering for QA reports."""

from __future__ import annotations

from .models import CheckResult, GuidedDiagnosticData, ReportContext


class MarkdownReportRenderer:
    """Renders a QA report as markdown."""

    def render(self, context: ReportContext) -> str:
        lines: list[str] = [
            f"# QA Report: {context.scenario}",
            "",
            f"- Project: `{context.project}`",
            f"- Scenario: `{context.scenario}`",
            f"- Final status: `{context.summary.final_status}`",
            f"- Continuation state: `{context.summary.continuation_state}`",
        ]

        if context.summary.resumable:
            lines.append("- Resumable: `true`")
        if context.summary.pause_state_path:
            lines.append(f"- Pause state: `{context.summary.pause_state_path}`")

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

        lines.extend(["", "## Guided diagnostics"])
        lines.extend(self._render_guided_diagnostics(context.summary.guided_diagnostics))

        if context.summary.guided_stop_reason is not None:
            lines.extend(["", "## Guided stop reason"])
            lines.extend(self._render_guided_diagnostics([context.summary.guided_stop_reason]))

        if context.summary.resume_token is not None:
            lines.extend(["", "## Resume"])
            lines.append(f"- Run ID: `{context.summary.resume_token.get('run_id', '')}`")
            lines.append(f"- Pause ID: `{context.summary.resume_token.get('pause_id', '')}`")

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

    @staticmethod
    def _render_guided_diagnostics(diagnostics: list[GuidedDiagnosticData]) -> list[str]:
        if not diagnostics:
            return ["- None"]

        lines: list[str] = []
        for diagnostic in diagnostics:
            prefix = f"- `{diagnostic.continuation_policy}` {diagnostic.title}"
            if diagnostic.tags:
                prefix += f" [{', '.join(diagnostic.tags)}]"
            prefix += f": {diagnostic.summary}"
            lines.append(prefix)
            for action in diagnostic.actions:
                marker = "Recommended" if action.recommended else "Action"
                lines.append(
                    f"  - {marker}: `{action.action_type}` {action.title} - {action.description}"
                )
            if diagnostic.decision_point is not None:
                lines.append(
                    f"  - Decision: {diagnostic.decision_point.title} - {diagnostic.decision_point.prompt}"
                )
        return lines
