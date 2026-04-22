"""Raw scenario source loading helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..contracts.errors import ScenarioParseError


@dataclass(frozen=True, slots=True)
class ScenarioSource:
    """Raw scenario file content with resolved source identity."""

    path: Path
    text: str
    lines: list[str]


def load_scenario_source(
    source_path: Path,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> ScenarioSource:
    """Load a scenario file as UTF-8 text without interpreting its format."""

    if not source_path.exists():
        raise error_type(f"Scenario file does not exist: {source_path}")

    resolved_source_path = source_path.resolve()
    text = resolved_source_path.read_text(encoding="utf-8")
    return ScenarioSource(
        path=resolved_source_path,
        text=text,
        lines=text.splitlines(),
    )
