"""Placeholder interpolation helpers for scenario execution."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from tools.common.errors import ValidationError

PLACEHOLDER_PATTERN = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
EXACT_PLACEHOLDER_PATTERN = re.compile(r"^\s*{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}\s*$")


class InterpolationError(ValidationError):
    """Raised when runtime placeholder interpolation cannot be completed."""


class UnresolvedPlaceholderError(InterpolationError):
    """Raised when one or more placeholders cannot be resolved from run variables."""

    def __init__(self, placeholder_names: list[str]) -> None:
        self.placeholder_names = placeholder_names
        super().__init__(
            "Unresolved placeholders: " + ", ".join(sorted(dict.fromkeys(placeholder_names)))
        )


class PlaceholderInterpolator:
    """Resolves {{variable_name}} placeholders across nested scenario inputs."""

    def interpolate(self, value: Any, variables: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self._interpolate_string(value, variables)
        if isinstance(value, dict):
            return self._interpolate_mapping(value, variables)
        if isinstance(value, list):
            return [self.interpolate(item, variables) for item in value]
        return value

    def _interpolate_mapping(self, value: dict[Any, Any], variables: dict[str, Any]) -> dict[Any, Any]:
        interpolated: dict[Any, Any] = {}
        for key, item in value.items():
            interpolated_key = self._interpolate_mapping_key(key, variables)
            if interpolated_key in interpolated:
                raise InterpolationError(
                    f"Interpolated mapping key collision for '{interpolated_key}'."
                )
            interpolated[interpolated_key] = self.interpolate(item, variables)
        return interpolated

    def _interpolate_mapping_key(self, key: Any, variables: dict[str, Any]) -> Any:
        if not isinstance(key, str):
            return key
        interpolated_key = self._interpolate_string(key, variables)
        if isinstance(interpolated_key, (dict, list, tuple, set)):
            raise InterpolationError(
                "Mapping key placeholder resolves to a non-scalar value and cannot be used as a key."
            )
        if interpolated_key is None:
            return ""
        if not isinstance(interpolated_key, str):
            return str(interpolated_key)
        return interpolated_key

    def _interpolate_string(self, value: str, variables: dict[str, Any]) -> Any:
        exact_match = EXACT_PLACEHOLDER_PATTERN.fullmatch(value)
        if exact_match:
            variable_name = exact_match.group(1)
            if variable_name not in variables:
                raise UnresolvedPlaceholderError([variable_name])
            return deepcopy(variables[variable_name])

        referenced_names = PLACEHOLDER_PATTERN.findall(value)
        missing_names = [name for name in referenced_names if name not in variables]
        if missing_names:
            raise UnresolvedPlaceholderError(missing_names)

        def replace(match: re.Match[str]) -> str:
            variable_name = match.group(1)
            variable_value = variables[variable_name]
            if isinstance(variable_value, (dict, list, tuple)):
                raise InterpolationError(
                    f"Placeholder '{variable_name}' resolves to a non-scalar value and cannot be embedded in a string."
                )
            return "" if variable_value is None else str(variable_value)

        return PLACEHOLDER_PATTERN.sub(replace, value)
