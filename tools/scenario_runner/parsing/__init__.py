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
    MarkdownScenarioDocument,
    MarkdownSection,
    parse_markdown_document_from_backend,
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
from .step_blocks import MARKDOWN_STEP_RE, split_step_blocks
from .step_fields import parse_step_block
from .step_ir import ParsedStepDraft, StepBlock, StepFieldKind, StepFields, StepFieldValue

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
    "MarkdownTokenDocument",
    "ParsedStepDraft",
    "StepBlock",
    "StepFieldKind",
    "StepFieldValue",
    "StepFields",
    "empty_json_object",
    "empty_parse_diagnostics",
    "load_scenario_source",
    "parse_markdown_document_from_backend",
    "parse_step_block",
    "split_step_blocks",
]
