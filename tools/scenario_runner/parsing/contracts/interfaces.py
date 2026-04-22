"""Parser interfaces for scenario source formats."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from .result import JsonObject, ScenarioParseResult, empty_json_object


@dataclass(frozen=True, slots=True)
class ScenarioParseOptions:
    """Options shared by parser implementations.

    The current automatic flow keeps using the legacy parser API. These options
    give future parser implementations a stable extension point.
    """

    strict: bool = False
    mode: str = "automatic"
    details: JsonObject = field(default_factory=empty_json_object)


@runtime_checkable
class ScenarioParser(Protocol):
    source_format: str

    def parse(
        self,
        source: Path,
        options: ScenarioParseOptions | None = None,
    ) -> ScenarioParseResult:
        """Parse a scenario source into a typed result with diagnostics."""
