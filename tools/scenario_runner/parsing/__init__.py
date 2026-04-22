"""Scenario parser subsystem contracts."""

from .errors import ScenarioParseError, ScenarioParsingError
from .interfaces import ScenarioParseOptions, ScenarioParser
from .loader import ScenarioSource, load_scenario_source
from .markdown_backend import (
    LineSpan,
    MarkdownBackend,
    MarkdownBlock,
    MarkdownBlockKind,
    MarkdownItBackend,
    MarkdownTokenDocument,
)
from .markdown_document import (
    MARKDOWN_STEP_RE,
    MarkdownScenarioDocument,
    MarkdownSection,
    MarkdownStepBlock,
    parse_markdown_document_from_backend,
    parse_markdown_document,
    split_step_blocks,
)
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
    "LineSpan",
    "MarkdownBackend",
    "MarkdownBlock",
    "MarkdownBlockKind",
    "MarkdownItBackend",
    "ParseDiagnostic",
    "ParseDiagnosticKind",
    "ParseDiagnosticSeverity",
    "ScenarioParseError",
    "ScenarioParseOptions",
    "ScenarioParseResult",
    "ScenarioParser",
    "ScenarioParsingError",
    "ScenarioSource",
    "SourceLocation",
    "MARKDOWN_STEP_RE",
    "MarkdownScenarioDocument",
    "MarkdownSection",
    "MarkdownStepBlock",
    "MarkdownTokenDocument",
    "empty_json_object",
    "empty_parse_diagnostics",
    "load_scenario_source",
    "parse_markdown_document",
    "parse_markdown_document_from_backend",
    "split_step_blocks",
]
