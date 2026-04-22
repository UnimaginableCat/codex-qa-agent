"""Scenario variable DSL parsing before domain conversion."""

from .ir import ParsedVariable, VariableParseResult
from .parser import parse_variables_section

__all__ = [
    "ParsedVariable",
    "VariableParseResult",
    "parse_variables_section",
]
