"""Typed parse result and diagnostic contracts for scenario parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TypeAlias

from tools.scenario_runner.domain.models import ScenarioDefinition

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


def empty_json_object() -> JsonObject:
    """Create a typed empty object for parser result metadata."""

    return {}


class ParseDiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class ParseDiagnosticKind(StrEnum):
    FILE_LOAD = "file_load"
    SYNTAX = "syntax"
    NORMALIZATION = "normalization"
    STRUCTURE = "structure"
    VALIDATION = "validation"
    COMPATIBILITY = "compatibility"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Identifies where a parser diagnostic points within a scenario source."""

    path: Path | None = None
    line: int | None = None
    column: int | None = None
    section: str | None = None
    step_number: int | None = None
    field_name: str | None = None

    def to_dict(self) -> JsonObject:
        return {
            "path": None if self.path is None else str(self.path),
            "line": self.line,
            "column": self.column,
            "section": self.section,
            "step_number": self.step_number,
            "field_name": self.field_name,
        }


@dataclass(frozen=True, slots=True)
class ParseDiagnostic:
    """Structured parse-time message that can be surfaced without running a scenario."""

    severity: ParseDiagnosticSeverity
    code: str
    message: str
    kind: ParseDiagnosticKind = ParseDiagnosticKind.UNKNOWN
    location: SourceLocation | None = None
    details: JsonObject = field(default_factory=empty_json_object)

    @property
    def is_error(self) -> bool:
        return self.severity in {ParseDiagnosticSeverity.ERROR, ParseDiagnosticSeverity.FATAL}

    @property
    def is_fatal(self) -> bool:
        return self.severity == ParseDiagnosticSeverity.FATAL

    def to_dict(self) -> JsonObject:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "kind": self.kind.value,
            "location": None if self.location is None else self.location.to_dict(),
            "details": self.details,
        }


def empty_parse_diagnostics() -> list[ParseDiagnostic]:
    """Create a typed empty diagnostics list for parse results."""

    return []


@dataclass(frozen=True, slots=True)
class ScenarioParseResult:
    """Parser output that carries a domain scenario together with parse diagnostics."""

    scenario: ScenarioDefinition | None
    diagnostics: list[ParseDiagnostic] = field(default_factory=empty_parse_diagnostics)
    source_format: str = "unknown"
    source_path: Path | None = None

    @property
    def has_errors(self) -> bool:
        return any(diagnostic.is_error for diagnostic in self.diagnostics)

    @property
    def has_fatal_errors(self) -> bool:
        return any(diagnostic.is_fatal for diagnostic in self.diagnostics)

    @property
    def warnings(self) -> list[ParseDiagnostic]:
        return [
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.severity == ParseDiagnosticSeverity.WARNING
        ]

    @property
    def errors(self) -> list[ParseDiagnostic]:
        return [diagnostic for diagnostic in self.diagnostics if diagnostic.is_error]

    @property
    def fatal_errors(self) -> list[ParseDiagnostic]:
        return [diagnostic for diagnostic in self.diagnostics if diagnostic.is_fatal]

    def to_dict(self) -> JsonObject:
        return {
            "scenario": None if self.scenario is None else self.scenario.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "source_format": self.source_format,
            "source_path": None if self.source_path is None else str(self.source_path),
            "has_errors": self.has_errors,
            "has_fatal_errors": self.has_fatal_errors,
        }
