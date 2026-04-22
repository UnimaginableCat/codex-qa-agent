"""Compatibility mapping from legacy parser metadata to structured diagnostics."""

from __future__ import annotations

from pathlib import Path

from tools.scenario_runner.models import ScenarioDefinition

from .contracts.result import (
    ParseDiagnostic,
    ParseDiagnosticKind,
    ParseDiagnosticSeverity,
    SourceLocation,
)


def build_legacy_parse_diagnostics(scenario_definition: ScenarioDefinition) -> list[ParseDiagnostic]:
    """Map legacy scenario metadata into stable structured parse diagnostics."""

    diagnostics: list[ParseDiagnostic] = []
    source_path = scenario_definition.scenario_path
    diagnostics.extend(_warning_diagnostics(source_path, scenario_definition.metadata.get("parse_warnings", [])))
    diagnostics.extend(
        _validation_diagnostics(
            source_path,
            scenario_definition.metadata.get("variables_validation_errors", []),
        )
    )
    return diagnostics


def build_parse_failure_diagnostic(source_path: Path, message: str) -> ParseDiagnostic:
    """Create the stable fatal diagnostic for legacy parse exceptions."""

    return ParseDiagnostic(
        severity=ParseDiagnosticSeverity.FATAL,
        code="scenario.parse_failed",
        message=message,
        kind=ParseDiagnosticKind.SYNTAX,
        location=SourceLocation(path=source_path),
    )


def _warning_diagnostics(source_path: Path, warnings: list[object]) -> list[ParseDiagnostic]:
    return [
        ParseDiagnostic(
            severity=ParseDiagnosticSeverity.WARNING,
            code="scenario.parse_warning",
            message=str(warning),
            kind=ParseDiagnosticKind.COMPATIBILITY,
            location=SourceLocation(path=source_path),
        )
        for warning in warnings
    ]


def _validation_diagnostics(source_path: Path, errors: list[object]) -> list[ParseDiagnostic]:
    return [
        ParseDiagnostic(
            severity=ParseDiagnosticSeverity.ERROR,
            code="scenario.variables_validation_error",
            message=str(error),
            kind=ParseDiagnosticKind.VALIDATION,
            location=SourceLocation(path=source_path, section="Variables"),
        )
        for error in errors
    ]
