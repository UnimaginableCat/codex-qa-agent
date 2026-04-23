"""Stack-aware orchestration for deterministic code facts extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic
from tools.generation.evidence.common import build_evidence_bundle

from .api_surface import PythonApiSurfaceFactsExtractor
from .extractors import CodeFactsExtractor
from .java_spring_api_surface import JavaSpringApiSurfaceFactsExtractor
from .models import CodeFactsScope, GenerationEvidenceBundle, TargetStack


@dataclass(slots=True)
class ExtractorSelectionResult:
    selected_stack: TargetStack | None
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)


@dataclass(slots=True)
class CodeFactsExtractionService:
    """Select a stack-specific extractor and return a unified evidence bundle."""

    python_extractor: CodeFactsExtractor = field(default_factory=PythonApiSurfaceFactsExtractor)
    java_spring_extractor: CodeFactsExtractor = field(default_factory=JavaSpringApiSurfaceFactsExtractor)

    def extract(self, project_path: Path, scope: CodeFactsScope) -> GenerationEvidenceBundle:
        selection = self.select_extractor(project_path, scope)
        if selection.selected_stack is None:
            return build_evidence_bundle(
                scope=scope,
                project_root=project_path.resolve(),
                facts=[],
                diagnostics=selection.diagnostics,
            )

        extractor = self._extractor_for(selection.selected_stack)
        bundle = extractor.extract(project_path, scope)
        bundle.diagnostics = [*selection.diagnostics, *bundle.diagnostics]
        return bundle

    def select_extractor(self, project_path: Path, scope: CodeFactsScope) -> ExtractorSelectionResult:
        diagnostics: list[GenerationDiagnostic] = []
        project_root = project_path.resolve()
        scope_extensions = _scope_extensions(scope)

        if scope.stack_hint is not None:
            if scope_extensions and not _stack_matches_extensions(scope.stack_hint, scope_extensions):
                diagnostics.append(
                    GenerationDiagnostic(
                        code="extractor_not_applicable",
                        message="Explicit stack hint does not match the explicit evidence scope file types.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=scope.scope_id,
                        details={"stack_hint": scope.stack_hint.value, "extensions": sorted(scope_extensions)},
                    )
                )
                return ExtractorSelectionResult(selected_stack=None, diagnostics=diagnostics)
            return ExtractorSelectionResult(selected_stack=scope.stack_hint, diagnostics=diagnostics)

        if len(scope_extensions) > 1:
            diagnostics.append(
                GenerationDiagnostic(
                    code="ambiguous_stack",
                    message="Evidence scope mixes file types that map to different extractors.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=scope.scope_id,
                    details={"extensions": sorted(scope_extensions)},
                )
            )
            return ExtractorSelectionResult(selected_stack=None, diagnostics=diagnostics)

        if scope_extensions == {".py"}:
            return ExtractorSelectionResult(selected_stack=TargetStack.PYTHON, diagnostics=diagnostics)

        if scope_extensions == {".java"}:
            spring_detected = _spring_annotation_detected(project_root, scope)
            if spring_detected:
                return ExtractorSelectionResult(selected_stack=TargetStack.JAVA_SPRING, diagnostics=diagnostics)
            diagnostics.append(
                GenerationDiagnostic(
                    code="extractor_not_applicable",
                    message="Scoped Java files do not contain supported Spring controller annotations.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=scope.scope_id,
                )
            )
            return ExtractorSelectionResult(selected_stack=None, diagnostics=diagnostics)

        diagnostics.append(
            GenerationDiagnostic(
                code="unsupported_stack",
                message="No supported extractor could be selected for the explicit evidence scope.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=scope.scope_id,
                details={"extensions": sorted(scope_extensions)},
            )
        )
        return ExtractorSelectionResult(selected_stack=None, diagnostics=diagnostics)

    def _extractor_for(self, stack: TargetStack) -> CodeFactsExtractor:
        if stack == TargetStack.PYTHON:
            return self.python_extractor
        if stack == TargetStack.JAVA_SPRING:
            return self.java_spring_extractor
        raise ValueError(f"Unsupported stack: {stack}")


def _scope_extensions(scope: CodeFactsScope) -> set[str]:
    path_extensions = {path.suffix.lower() for path in scope.paths if path.suffix}
    if path_extensions:
        return path_extensions

    extensions: set[str] = set()
    for pattern in scope.file_patterns:
        match = re.search(r"\.(\w+)$", pattern)
        if match:
            extensions.add("." + match.group(1).lower())
    return extensions


def _stack_matches_extensions(stack: TargetStack, extensions: set[str]) -> bool:
    expected = {
        TargetStack.PYTHON: {".py"},
        TargetStack.JAVA_SPRING: {".java"},
    }[stack]
    return not extensions or extensions <= expected


def _spring_annotation_detected(project_root: Path, scope: CodeFactsScope) -> bool:
    markers = (
        "@RequestMapping",
        "@GetMapping",
        "@PostMapping",
        "@PutMapping",
        "@PatchMapping",
        "@DeleteMapping",
        "@RestController",
        "@Controller",
    )
    for raw_path in scope.paths:
        candidate = raw_path if raw_path.is_absolute() else project_root / raw_path
        resolved = candidate.resolve()
        if not resolved.exists() or not resolved.is_file() or resolved.suffix.lower() != ".java":
            continue
        try:
            text = resolved.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        if any(marker in text for marker in markers):
            return True
    return False
