"""Adapter layer for the legacy parser facade to emit ScenarioParseResult."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tools.scenario_runner.domain.models import ScenarioDefinition

from .contracts.errors import ScenarioParseError
from .contracts.result import ScenarioParseResult
from .diagnostics_bridge import build_legacy_parse_diagnostics, build_parse_failure_diagnostic


def adapt_legacy_parse_result(
    parse_scenario: Callable[[Path], ScenarioDefinition],
    scenario_path: Path,
    *,
    source_format: str,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> ScenarioParseResult:
    """Execute legacy parse() and wrap the result in the structured parse-result contract."""

    source_path = Path(scenario_path)
    try:
        scenario_definition = parse_scenario(source_path)
    except error_type as exc:
        return ScenarioParseResult(
            scenario=None,
            diagnostics=[build_parse_failure_diagnostic(source_path, str(exc))],
            source_format=source_format,
            source_path=source_path,
        )

    return ScenarioParseResult(
        scenario=scenario_definition,
        diagnostics=build_legacy_parse_diagnostics(scenario_definition),
        source_format=str(scenario_definition.metadata.get("source_format") or source_format),
        source_path=scenario_definition.scenario_path,
    )
