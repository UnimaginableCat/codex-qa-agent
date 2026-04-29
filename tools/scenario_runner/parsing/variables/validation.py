"""Validation and domain conversion for the scenario Variables DSL."""

from __future__ import annotations

import re

from tools.scenario_runner.domain.models import (
    ScenarioVariableDefinition,
    ScenarioVariableSource,
)

from ..contracts.errors import ScenarioParseError
from .normalization import is_wrapped_literal, normalize_variable_raw_value

ENV_VALUE_RE = re.compile(r"^env(?:\s*:\s*|\s+)(?P<name>[A-Za-z_][A-Za-z0-9_]*)$", re.IGNORECASE)
RUNTIME_VALUE_RE = re.compile(
    r"^(?P<source>generated|runtime)(?:\s*:\s*|\s+)(?P<name>[A-Za-z_][A-Za-z0-9_]*)$",
    re.IGNORECASE,
)
VARIABLE_SOURCE_PREFIX_RE = re.compile(
    r"^(?P<source>env|environment|generated|runtime|template|literal|derived|transform)"
    r"(?:\s*:\s*(?P<value>.*)|\s*)$",
    re.IGNORECASE,
)
DERIVED_EXPRESSION_RE = re.compile(
    r"^(?P<source>\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}|[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*\|\s*(?P<transforms>[A-Za-z_][A-Za-z0-9_]*(?:\s*\|\s*[A-Za-z_][A-Za-z0-9_]*)*)$"
)
TRANSFORM_EXPRESSION_RE = re.compile(
    r"^(?P<transform>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*"
    r"(?P<source>\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}|[A-Za-z_][A-Za-z0-9_]*)$"
)
SUPPORTED_TRANSFORMS = {"lower", "upper", "trim"}
SUPPORTED_GENERATED_VALUES = {
    "numeric_suffix",
    "numeric_timestamp_suffix",
    "run_id",
    "run_suffix",
    "timestamp",
    "timestamp_suffix",
    "generated_timestamp",
    "current_timestamp",
    "uuid",
}


def build_variable_definition(
    variable_name: str,
    raw_value: str,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> ScenarioVariableDefinition:
    """Convert one parsed raw variable value into the legacy domain model."""

    raw_value = str(raw_value).strip()
    quoted_literal = is_wrapped_literal(raw_value)
    normalized_raw_value = normalize_variable_raw_value(raw_value)
    source_match = VARIABLE_SOURCE_PREFIX_RE.fullmatch(raw_value)
    source = source_match.group("source").lower() if source_match else ""
    source_value = (source_match.group("value") or "").strip() if source_match else ""

    env_match = ENV_VALUE_RE.fullmatch(raw_value)
    if source in {"env", "environment"} or env_match:
        env_name = source_value or (env_match.group("name") if env_match else "")
        return ScenarioVariableDefinition(
            name=variable_name,
            raw_value=raw_value,
            source=ScenarioVariableSource.ENV,
            env_name=env_name or variable_name.upper(),
        )

    runtime_match = RUNTIME_VALUE_RE.fullmatch(raw_value)
    if source in {"generated", "runtime"} or runtime_match:
        generated_value = source_value or (
            runtime_match.group("name") if runtime_match else variable_name
        )
        generated_value = generated_value or variable_name
        validate_generated_variable(variable_name, generated_value, error_type=error_type)
        return ScenarioVariableDefinition(
            name=variable_name,
            raw_value=f"generated:{generated_value}",
            source=ScenarioVariableSource.GENERATED,
        )

    if is_generated_runtime_variable(variable_name, raw_value):
        validate_generated_variable(variable_name, variable_name, error_type=error_type)
        return ScenarioVariableDefinition(
            name=variable_name,
            raw_value=f"generated:{variable_name}",
            source=ScenarioVariableSource.GENERATED,
        )

    if source == "template":
        return ScenarioVariableDefinition(
            name=variable_name,
            raw_value=normalize_variable_raw_value(source_value),
            source=ScenarioVariableSource.TEMPLATE,
        )

    if source == "literal":
        return ScenarioVariableDefinition(
            name=variable_name,
            raw_value=normalize_variable_raw_value(source_value),
            source=ScenarioVariableSource.LITERAL,
        )

    if source in {"derived", "transform"}:
        source_name, transforms = parse_derived_variable(source, source_value, error_type=error_type)
        return ScenarioVariableDefinition(
            name=variable_name,
            raw_value=raw_value,
            source=ScenarioVariableSource.DERIVED,
            source_name=source_name,
            transforms=transforms,
        )

    if "{{" in raw_value and "}}" in raw_value:
        return ScenarioVariableDefinition(
            name=variable_name,
            raw_value=normalized_raw_value,
            source=ScenarioVariableSource.TEMPLATE,
        )

    if quoted_literal:
        return ScenarioVariableDefinition(
            name=variable_name,
            raw_value=normalized_raw_value,
            source=ScenarioVariableSource.LITERAL,
        )

    if not raw_value:
        raise error_type(
            "empty variable definitions are not supported; use env:NAME, generated:kind, "
            "template:..., derived:source|transform, or literal:..."
        )

    raise error_type(
        f"ambiguous untyped value {raw_value!r}; prose or bare literals are not allowed in "
        "Variables. Use an explicit type prefix."
    )


def parse_derived_variable(
    source: str,
    raw_expression: str,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> tuple[str, list[str]]:
    """Parse a derived/transform variable expression into source name and transforms."""

    expression = raw_expression.strip()
    if not expression:
        raise error_type("derived variables require an expression such as derived:run_suffix|lower")

    if source == "transform":
        match = TRANSFORM_EXPRESSION_RE.fullmatch(expression)
        if match is None:
            raise error_type(
                "transform variables require transform:<transform>:<source>, for example "
                "transform:lower:run_suffix"
            )
        source_name = normalize_derived_source_name(match.group("source"))
        transforms = [match.group("transform").strip().lower()]
    else:
        match = DERIVED_EXPRESSION_RE.fullmatch(expression)
        if match is None:
            raise error_type(
                "derived variables require derived:<source>|<transform>, for example "
                "derived:run_suffix|lower"
            )
        source_name = normalize_derived_source_name(match.group("source"))
        transforms = [item.strip().lower() for item in match.group("transforms").split("|")]

    unsupported = [transform for transform in transforms if transform not in SUPPORTED_TRANSFORMS]
    if unsupported:
        raise error_type(
            "unsupported transform(s): "
            f"{', '.join(unsupported)}. Supported transforms: {', '.join(sorted(SUPPORTED_TRANSFORMS))}."
        )
    return source_name, transforms


def normalize_derived_source_name(raw_source: str) -> str:
    """Normalize placeholder-wrapped derived source names to plain variable names."""

    source = raw_source.strip()
    placeholder_match = re.fullmatch(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", source)
    return placeholder_match.group(1) if placeholder_match else source


def validate_generated_variable(
    variable_name: str,
    generated_value: str,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> None:
    """Validate that a generated variable uses one of the supported generated kinds."""

    normalized_value = generated_value.strip().lower()
    normalized_name = variable_name.strip().lower()
    if normalized_value in SUPPORTED_GENERATED_VALUES:
        return
    if normalized_value == normalized_name and (
        normalized_name.endswith("_suffix")
        or normalized_name.endswith("_numeric_suffix")
        or normalized_name.endswith("_run_id")
        or normalized_name in {"run_id", "timestamp", "generated_timestamp", "numeric_suffix", "numeric_timestamp_suffix"}
        or (normalized_name.startswith("missing_") and normalized_name.endswith("_id"))
    ):
        return
    raise error_type(
        f"unsupported generated value '{generated_value}'. Supported generated values: "
        f"{', '.join(sorted(SUPPORTED_GENERATED_VALUES))}."
    )


def is_generated_runtime_variable(variable_name: str, raw_value: str) -> bool:
    """Return whether legacy shorthand should be treated as a generated variable."""

    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"", "generated", "runtime"}:
        return False
    normalized_name = variable_name.lower()
    return (
        normalized_name == "run_suffix"
        or normalized_name.endswith("_suffix")
        or normalized_name.endswith("_run_id")
        or normalized_name in {"run_id", "timestamp", "generated_timestamp"}
    )
