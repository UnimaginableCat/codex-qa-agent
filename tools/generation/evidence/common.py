"""Shared helpers for scoped evidence extraction."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic

from .models import CodeFactsScope, GenerationEvidenceBundle, GenerationEvidenceFact


def build_evidence_bundle(
    *,
    scope: CodeFactsScope,
    project_root: Path,
    facts: list[GenerationEvidenceFact],
    diagnostics: list[GenerationDiagnostic],
) -> GenerationEvidenceBundle:
    return GenerationEvidenceBundle(
        bundle_id=f"evidence-{scope.scope_id}",
        target_project=str(project_root),
        scope=scope.scope_id,
        facts=facts,
        diagnostics=diagnostics,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def resolve_scope_files(
    project_root: Path,
    scope: CodeFactsScope,
    diagnostics: list[GenerationDiagnostic],
) -> list[Path]:
    if not project_root.exists():
        diagnostics.append(
            GenerationDiagnostic(
                code="target_project_missing",
                message="Target project path for code facts extraction does not exist.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=scope.scope_id,
                details={"project_path": str(project_root)},
            )
        )
        return []

    if not scope.paths:
        diagnostics.append(
            GenerationDiagnostic(
                code="missing_evidence_scope",
                message="Code facts extraction requires explicit scoped paths; global scans are not supported.",
                severity=DiagnosticSeverity.ERROR,
                source_ref=scope.scope_id,
            )
        )
        return []

    resolved_project_root = project_root.resolve()
    files: list[Path] = []
    for raw_path in scope.paths:
        candidate = raw_path if raw_path.is_absolute() else resolved_project_root / raw_path
        resolved_candidate = candidate.resolve()
        try:
            resolved_candidate.relative_to(resolved_project_root)
        except ValueError:
            diagnostics.append(
                GenerationDiagnostic(
                    code="scope_path_outside_project",
                    message="Evidence scope path must stay inside the explicit project root.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=scope.scope_id,
                    details={"path": str(resolved_candidate)},
                )
            )
            continue

        if not resolved_candidate.exists():
            diagnostics.append(
                GenerationDiagnostic(
                    code="scope_path_missing",
                    message="Evidence scope path does not exist.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=scope.scope_id,
                    details={"path": str(resolved_candidate)},
                )
            )
            continue

        if resolved_candidate.is_file():
            files.append(resolved_candidate)
            continue

        if resolved_candidate.is_dir():
            for pattern in scope.file_patterns:
                files.extend(
                    sorted(item.resolve() for item in resolved_candidate.glob(pattern) if item.is_file())
                )

    unique_files = _dedupe_paths(files)
    if len(unique_files) > scope.max_files:
        diagnostics.append(
            GenerationDiagnostic(
                code="scope_file_limit_applied",
                message="Evidence scope matched more files than allowed; extraction was truncated.",
                severity=DiagnosticSeverity.WARNING,
                source_ref=scope.scope_id,
                details={"matched": len(unique_files), "max_files": scope.max_files},
            )
        )
    return unique_files[: scope.max_files]


def relative_to_project(path: Path, project_root: Path) -> Path:
    try:
        return path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return path


def dedupe_paths(paths: list[Path]) -> list[Path]:
    return _dedupe_paths(paths)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result
