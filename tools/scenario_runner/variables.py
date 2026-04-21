"""Scenario-level variable resolution for initial runner context."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Protocol

from tools.common.errors import EnvFileLoadError, ValidationError

from .interpolator import PLACEHOLDER_PATTERN, PlaceholderInterpolator, UnresolvedPlaceholderError
from .models import RunContext, ScenarioDefinition, ScenarioVariableDefinition, ScenarioVariableSource


_GENERATED_TEMPLATE_FALLBACKS = {
    "generated_price_list_name": "AUTOTEST Attributes Flow {{run_suffix}}",
}


class VariableResolutionError(ValidationError):
    """Raised when required scenario placeholders cannot be resolved."""

    def __init__(
        self,
        message: str,
        unresolved_variables: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.unresolved_variables = unresolved_variables or []
        self.warnings = warnings or []
        super().__init__(message)


@dataclass(slots=True)
class InitialVariableResolution:
    variables: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


class EnvValueLoader(Protocol):
    def load(self, env_path: Path) -> dict[str, str | None]:
        """Load env values from a file."""


def build_initial_variables(
    run_context: RunContext,
    scenario_definition: ScenarioDefinition,
    dotenv_loader: EnvValueLoader | None = None,
    interpolator: PlaceholderInterpolator | None = None,
) -> InitialVariableResolution:
    """Build initial context using only variables needed before the first step."""

    first_step = scenario_definition.steps[0] if scenario_definition.steps else None
    required_placeholders = _collect_step_placeholder_names(first_step) if first_step is not None else set()
    return _resolve_variables(
        run_context=run_context,
        scenario_definition=scenario_definition,
        required_placeholders=required_placeholders,
        enforce_required=False,
        dotenv_loader=dotenv_loader,
        interpolator=interpolator,
    )


def resolve_step_variables(
    run_context: RunContext,
    scenario_definition: ScenarioDefinition,
    step,
    dotenv_loader: EnvValueLoader | None = None,
    interpolator: PlaceholderInterpolator | None = None,
) -> InitialVariableResolution:
    """Resolve placeholders required by the current step from current context."""

    return _resolve_variables(
        run_context=run_context,
        scenario_definition=scenario_definition,
        required_placeholders=_collect_step_placeholder_names(step),
        enforce_required=True,
        dotenv_loader=dotenv_loader,
        interpolator=interpolator,
    )


def _resolve_variables(
    run_context: RunContext,
    scenario_definition: ScenarioDefinition,
    required_placeholders: set[str],
    enforce_required: bool,
    dotenv_loader: EnvValueLoader | None,
    interpolator: PlaceholderInterpolator | None,
) -> InitialVariableResolution:
    """Resolve required placeholders without sweeping the full scenario."""

    definitions = list(scenario_definition.variables)
    resolved: dict[str, Any] = dict(run_context.variables)
    warnings: list[str] = []
    env_values: dict[str, str | None] | None = None
    env_loaded = False
    placeholder_interpolator = interpolator or PlaceholderInterpolator()
    template_dependencies = _collect_template_dependency_placeholders(definitions)
    for fallback_name, template_value in _GENERATED_TEMPLATE_FALLBACKS.items():
        if fallback_name in required_placeholders:
            template_dependencies.update(_collect_placeholder_names(template_value))

    def load_env_values() -> dict[str, str | None]:
        nonlocal env_loaded, env_values
        if env_loaded:
            return env_values or {}
        env_loaded = True
        loader = dotenv_loader or _default_env_loader()
        try:
            env_values = _load_env_values(run_context.workspace_root, scenario_definition.environment, loader)
        except VariableResolutionError as exc:
            warnings.append(str(exc))
            env_values = {}
        return env_values

    for definition in _definitions_by_source(definitions, ScenarioVariableSource.LITERAL):
        _set_if_absent(resolved, definition.name, definition.raw_value)

    for definition in _definitions_by_source(definitions, ScenarioVariableSource.ENV):
        if definition.name in resolved:
            continue
        value = _lookup_env_variable(definition.name, definition.env_name, load_env_values())
        if value is None:
            warnings.append(
                f"Variable '{definition.name}' was declared as env-backed but could not be resolved."
            )
            continue
        resolved[definition.name] = value

    for definition in _definitions_by_source(definitions, ScenarioVariableSource.RUNTIME):
        if definition.name in resolved:
            continue
        runtime_value = _resolve_runtime_variable(definition, run_context, resolved)
        if runtime_value is None:
            warnings.append(
                f"Variable '{definition.name}' declared unsupported runtime value "
                f"'{_runtime_name(definition)}'."
            )
            continue
        resolved[definition.name] = runtime_value

    for name in sorted(required_placeholders | template_dependencies):
        if name in resolved:
            continue
        value = _lookup_env_variable(name, None, load_env_values())
        if value is not None:
            resolved[name] = value

    runtime_names = (
        required_placeholders
        | template_dependencies
        | {definition.name for definition in _definitions_by_source(definitions, ScenarioVariableSource.RUNTIME)}
    )
    for name in sorted(runtime_names):
        if name in resolved:
            continue
        runtime_value = _resolve_known_runtime_name(name, run_context, resolved)
        if runtime_value is not None:
            resolved[name] = runtime_value

    for definition in _definitions_by_source(definitions, ScenarioVariableSource.TEMPLATE):
        if definition.name in resolved:
            continue
        template_value = _resolve_template_variable(
            definition.name,
            definition.raw_value,
            resolved,
            placeholder_interpolator,
            required_placeholders,
            enforce_required,
            warnings,
        )
        if template_value is not None:
            resolved[definition.name] = template_value

    for name, template_value in _GENERATED_TEMPLATE_FALLBACKS.items():
        if name in resolved or name not in required_placeholders:
            continue
        fallback_value = _resolve_template_variable(
            name,
            template_value,
            resolved,
            placeholder_interpolator,
            required_placeholders,
            enforce_required,
            warnings,
        )
        if fallback_value is not None:
            resolved[name] = fallback_value

    unresolved_required = sorted(name for name in required_placeholders if name not in resolved)
    if unresolved_required and enforce_required:
        raise VariableResolutionError(
            "Required placeholders could not be resolved after Variables, env, generated, and template "
            f"fallbacks: {', '.join(unresolved_required)}.",
            unresolved_variables=unresolved_required,
            warnings=warnings,
        )
    if unresolved_required:
        warnings.append(
            "Initial context deferred unresolved placeholder(s) until step execution: "
            f"{', '.join(unresolved_required)}."
        )

    return InitialVariableResolution(variables=resolved, warnings=warnings)


def _resolve_template_variable(
    name: str,
    template_value: str,
    resolved: dict[str, Any],
    interpolator: PlaceholderInterpolator,
    required_placeholders: set[str],
    enforce_required: bool,
    warnings: list[str],
) -> Any | None:
    try:
        return interpolator.interpolate(template_value, resolved)
    except UnresolvedPlaceholderError as exc:
        missing_names = sorted(dict.fromkeys(exc.placeholder_names))
        message = f"Variable '{name}' could not be derived because {', '.join(missing_names)} is unresolved."
        warnings.append(message)
        if name in required_placeholders and enforce_required:
            raise VariableResolutionError(
                message,
                unresolved_variables=[name, *missing_names],
                warnings=warnings,
            ) from exc
    return None


def _collect_step_placeholder_names(step) -> set[str]:
    names: set[str] = set()
    if step.api is not None:
        names.update(_collect_placeholder_names(step.api.method))
        names.update(_collect_placeholder_names(step.api.path))
        names.update(_collect_placeholder_names(step.api.headers))
        names.update(_collect_placeholder_names(step.api.params))
        names.update(_collect_placeholder_names(step.api.body))
        names.update(_collect_placeholder_names(step.api.retry))
    if step.db is not None:
        names.update(_collect_placeholder_names(step.db.sql))
        names.update(_collect_placeholder_names(step.db.params))
    return names


def _collect_template_dependency_placeholders(definitions: list[ScenarioVariableDefinition]) -> set[str]:
    names: set[str] = set()
    for definition in _definitions_by_source(definitions, ScenarioVariableSource.TEMPLATE):
        names.update(_collect_placeholder_names(definition.raw_value))
    return names


def _collect_placeholder_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(PLACEHOLDER_PATTERN.findall(value))
    if isinstance(value, dict):
        names: set[str] = set()
        for key, item in value.items():
            names.update(_collect_placeholder_names(key))
            names.update(_collect_placeholder_names(item))
        return names
    if isinstance(value, list | tuple):
        names: set[str] = set()
        for item in value:
            names.update(_collect_placeholder_names(item))
        return names
    return set()


def _definitions_by_source(
    definitions: list[ScenarioVariableDefinition],
    source: ScenarioVariableSource,
) -> list[ScenarioVariableDefinition]:
    return [definition for definition in definitions if definition.source == source]


def _set_if_absent(target: dict[str, Any], key: str, value: Any) -> None:
    if key not in target:
        target[key] = value


def _resolve_runtime_variable(
    definition: ScenarioVariableDefinition,
    run_context: RunContext,
    resolved: dict[str, Any],
) -> Any | None:
    return _resolve_known_runtime_name(_runtime_name(definition), run_context, resolved)


def _resolve_known_runtime_name(name: str, run_context: RunContext, resolved: dict[str, Any]) -> Any | None:
    if name == "run_suffix":
        return run_context.run_id.removeprefix("run-")
    return resolved.get(name)


def _runtime_name(definition: ScenarioVariableDefinition) -> str:
    raw_value = definition.raw_value.strip()
    if ":" in raw_value:
        return raw_value.split(":", 1)[1].strip()
    if definition.name == "run_suffix":
        return "run_suffix"
    return raw_value or definition.name


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


def _lookup_env_variable(
    variable_name: str,
    declared_env_name: str | None,
    env_values: dict[str, str | None],
) -> str | None:
    candidate_names = _env_candidate_names(variable_name, declared_env_name)
    for candidate_name in candidate_names:
        env_value = env_values.get(candidate_name)
        if env_value is not None:
            return env_value
        process_value = os.environ.get(candidate_name)
        if process_value is not None:
            return process_value
    return None


def _env_candidate_names(variable_name: str, declared_env_name: str | None) -> list[str]:
    names = [
        candidate
        for candidate in (
            declared_env_name,
            variable_name,
            variable_name.upper(),
        )
        if candidate
    ]
    return list(dict.fromkeys(names))


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
