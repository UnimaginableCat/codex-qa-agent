"""Scenario-level variable resolution for initial runner context."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from tools.common.errors import EnvFileLoadError, ValidationError

from .interpolator import PlaceholderInterpolator, UnresolvedPlaceholderError
from .models import RunContext, ScenarioDefinition, ScenarioVariableDefinition, ScenarioVariableSource


class VariableResolutionError(ValidationError):
    """Raised when scenario variables cannot be resolved into initial context."""

    def __init__(self, message: str, unresolved_variables: list[str] | None = None) -> None:
        self.unresolved_variables = unresolved_variables or []
        super().__init__(message)


class EnvValueLoader(Protocol):
    def load(self, env_path: Path) -> dict[str, str | None]:
        """Load env values from a file."""


def build_initial_variables(
    run_context: RunContext,
    scenario_definition: ScenarioDefinition,
    dotenv_loader: EnvValueLoader | None = None,
    interpolator: PlaceholderInterpolator | None = None,
) -> dict[str, Any]:
    """Build the initial execution context before any step captures exist."""

    definitions = list(scenario_definition.variables)
    resolved: dict[str, Any] = dict(run_context.variables)
    if not definitions:
        return resolved

    loader = dotenv_loader or _default_env_loader()
    env_values: dict[str, str | None] | None = None
    placeholder_interpolator = interpolator or PlaceholderInterpolator()

    for definition in _definitions_by_source(definitions, ScenarioVariableSource.RUNTIME):
        resolved[definition.name] = _resolve_runtime_variable(definition, run_context, resolved)

    for definition in _definitions_by_source(definitions, ScenarioVariableSource.ENV):
        if env_values is None:
            env_values = _load_env_values(run_context.workspace_root, scenario_definition.environment, loader)
        resolved[definition.name] = _resolve_env_variable(definition, env_values)

    for definition in _definitions_by_source(definitions, ScenarioVariableSource.LITERAL):
        resolved[definition.name] = definition.raw_value

    for definition in _definitions_by_source(definitions, ScenarioVariableSource.TEMPLATE):
        try:
            resolved[definition.name] = placeholder_interpolator.interpolate(definition.raw_value, resolved)
        except UnresolvedPlaceholderError as exc:
            missing_names = sorted(dict.fromkeys(exc.placeholder_names))
            raise VariableResolutionError(
                f"Variable '{definition.name}' could not be resolved: missing "
                f"{', '.join(missing_names)}.",
                unresolved_variables=[definition.name, *missing_names],
            ) from exc

    return resolved


def _definitions_by_source(
    definitions: list[ScenarioVariableDefinition],
    source: ScenarioVariableSource,
) -> list[ScenarioVariableDefinition]:
    return [definition for definition in definitions if definition.source == source]


def _resolve_runtime_variable(
    definition: ScenarioVariableDefinition,
    run_context: RunContext,
    resolved: dict[str, Any],
) -> Any:
    runtime_name = _runtime_name(definition)
    if runtime_name == "run_suffix":
        return run_context.run_id.removeprefix("run-")
    if runtime_name in resolved:
        return resolved[runtime_name]
    raise VariableResolutionError(
        f"Variable '{definition.name}' could not be resolved: unsupported runtime value '{runtime_name}'.",
        unresolved_variables=[definition.name],
    )


def _runtime_name(definition: ScenarioVariableDefinition) -> str:
    raw_value = definition.raw_value.strip()
    if ":" in raw_value:
        return raw_value.split(":", 1)[1].strip()
    if definition.name == "run_suffix":
        return "run_suffix"
    return raw_value


def _load_env_values(
    workspace_root: Path,
    environment_path: str,
    loader: EnvValueLoader,
) -> dict[str, str | None]:
    env_path = _resolve_environment_path(workspace_root, environment_path)
    try:
        return loader.load(env_path)
    except EnvFileLoadError as exc:
        raise VariableResolutionError(
            f"Environment variables could not be loaded for scenario variables: {exc}"
        ) from exc


def _resolve_env_variable(
    definition: ScenarioVariableDefinition,
    env_values: dict[str, str | None],
) -> str:
    env_name = definition.env_name or definition.name.upper()
    env_value = env_values.get(env_name)
    if env_value is None:
        env_value = os.environ.get(env_name)
    if env_value is None:
        raise VariableResolutionError(
            f"Variable '{definition.name}' could not be resolved from environment key '{env_name}'.",
            unresolved_variables=[definition.name],
        )
    return env_value


def _resolve_environment_path(workspace_root: Path, environment_path: str) -> Path:
    if not environment_path.strip():
        return workspace_root / "__missing_env__"
    candidate = Path(environment_path)
    if candidate.is_absolute():
        return candidate
    return workspace_root / candidate


def _default_env_loader() -> EnvValueLoader:
    try:
        from tools.common.env import DotenvEnvLoader
    except ModuleNotFoundError:
        return _SimpleEnvLoader()
    return DotenvEnvLoader()


class _SimpleEnvLoader:
    def load(self, env_path: Path) -> dict[str, str | None]:
        if not env_path.exists():
            raise EnvFileLoadError(f"Env file does not exist: {env_path}")

        values: dict[str, str | None] = {}
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:  # noqa: BLE001
            raise EnvFileLoadError(f"Failed to load env file '{env_path}': {exc}") from exc

        for line in lines:
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith("#") or "=" not in stripped_line:
                continue
            key, value = stripped_line.split("=", 1)
            values[key.strip()] = _strip_optional_quotes(value.strip())
        return values


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
