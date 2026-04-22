"""Public parser contracts and diagnostics."""

from .errors import ScenarioParseError, ScenarioParsingError
from .interfaces import ScenarioParseOptions, ScenarioParser
from .result import (
    JsonObject,
    JsonScalar,
    JsonValue,
    ParseDiagnostic,
    ParseDiagnosticKind,
    ParseDiagnosticSeverity,
    ScenarioParseResult,
    SourceLocation,
    empty_json_object,
    empty_parse_diagnostics,
)

__all__ = [
    "JsonObject",
    "JsonScalar",
    "JsonValue",
    "ParseDiagnostic",
    "ParseDiagnosticKind",
    "ParseDiagnosticSeverity",
    "ScenarioParseError",
    "ScenarioParseOptions",
    "ScenarioParseResult",
    "ScenarioParser",
    "ScenarioParsingError",
    "SourceLocation",
    "empty_json_object",
    "empty_parse_diagnostics",
]
