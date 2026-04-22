"""Intermediate representation for scenario step parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeAlias

from ..contracts.result import JsonValue

StepFieldValue: TypeAlias = JsonValue | list[str]
StepFields: TypeAlias = dict[str, StepFieldValue]


class StepFieldKind(StrEnum):
    """Field names supported by the scenario step DSL."""

    TYPE = "type"
    NAME = "name"
    METHOD = "method"
    PATH = "path"
    HEADERS = "headers"
    BODY = "body"
    RETRY = "retry"
    SQL = "sql"
    PARAMS = "params"
    CAPTURE = "capture"
    EXPECTED = "expected"


def empty_step_fields() -> StepFields:
    """Create an empty typed container for parsed step fields."""

    return {}


def empty_step_warnings() -> list[str]:
    """Create an empty warning list for a parsed step draft."""

    return []


@dataclass(frozen=True, slots=True)
class StepBlock:
    """Raw markdown lines for one scenario step before field-level parsing."""

    step_number: int
    line_number: int
    lines: list[str]


@dataclass(slots=True)
class ParsedStepDraft:
    """Parsed step fields before conversion to a domain ScenarioStep."""

    step_number: int
    line_number: int
    fields: StepFields = field(default_factory=empty_step_fields)
    warnings: list[str] = field(default_factory=empty_step_warnings)
