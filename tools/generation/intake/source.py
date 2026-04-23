"""Source input resolution for generation workflows."""

from __future__ import annotations

from dataclasses import dataclass, field

from tools.generation.domain.models import (
    DiagnosticSeverity,
    GenerationDiagnostic,
    GenerationSourceInput,
)


@dataclass(slots=True)
class SourceIntakeResult:
    resolved_source_input: GenerationSourceInput
    content: str
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)


class SourceIntakeService:
    """Resolve inline or file-backed generation source input into text content."""

    def resolve(self, source_input: GenerationSourceInput) -> SourceIntakeResult:
        diagnostics = [
            GenerationDiagnostic(
                code="source_input_captured",
                message="Source input accepted as a typed generation model.",
                severity=DiagnosticSeverity.INFO,
                source_ref=source_input.source_id,
            )
        ]
        if source_input.content.strip():
            return SourceIntakeResult(source_input, source_input.content, diagnostics)
        if source_input.source_path is None:
            diagnostics.append(
                GenerationDiagnostic(
                    code="source_content_empty",
                    message="Source input has no inline content or source path.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=source_input.source_id,
                )
            )
            return SourceIntakeResult(source_input, "", diagnostics)

        if not source_input.source_path.exists():
            diagnostics.append(
                GenerationDiagnostic(
                    code="source_path_missing",
                    message="Source input file does not exist.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=source_input.source_id,
                    details={"source_path": str(source_input.source_path)},
                )
            )
            return SourceIntakeResult(source_input, "", diagnostics)

        try:
            content = source_input.source_path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                GenerationDiagnostic(
                    code="source_path_unreadable",
                    message="Source input file could not be read.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=source_input.source_id,
                    details={"source_path": str(source_input.source_path), "error": str(exc)},
                )
            )
            return SourceIntakeResult(source_input, "", diagnostics)

        resolved_source_input = GenerationSourceInput(
            source_id=source_input.source_id,
            project=source_input.project,
            input_format=source_input.input_format,
            name=source_input.name,
            content=content,
            source_path=source_input.source_path,
            metadata=dict(source_input.metadata),
        )
        return SourceIntakeResult(resolved_source_input, content, diagnostics)

