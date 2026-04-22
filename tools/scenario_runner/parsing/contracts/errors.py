"""Error types for scenario parsing contracts."""

from __future__ import annotations

from tools.common.errors import ValidationError


class ScenarioParsingError(ValidationError):
    """Base error for scenario parser subsystem failures."""


class ScenarioParseError(ScenarioParsingError):
    """Raised when a scenario source cannot be parsed into a valid plan."""
