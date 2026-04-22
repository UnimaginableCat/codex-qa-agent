"""Services for report building and writing."""

from __future__ import annotations

from pathlib import Path

from tools.common import write_text_file

from .loaders import SummaryLoader
from .models import ReportContext
from .renderers import MarkdownReportRenderer


class ReportWriter:
    """Writes report content to disk."""

    def write(self, output_path: Path, content: str) -> None:
        write_text_file(output_path, content)


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
        context = ReportContext(project=project, scenario=scenario, summary=summary)
        return self.build_from_context(context=context, output_path=output_path)

    def build_from_context(self, context: ReportContext, output_path: Path) -> Path:
        content = self._renderer.render(context)
        self._writer.write(output_path, content)
        return output_path


def build_service() -> ReportBuildService:
    return ReportBuildService(
        summary_loader=SummaryLoader(),
        renderer=MarkdownReportRenderer(),
        writer=ReportWriter(),
    )
