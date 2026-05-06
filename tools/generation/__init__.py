"""Test-plan and scenario generation foundation package.

Keep this initializer lightweight so ``python -m tools.generation.cli`` can
reach the CLI bootstrap guard before importing optional workspace dependencies.
"""

from __future__ import annotations


_EXPORTS: dict[str, tuple[str, str]] = {
    "AgentPlanAuthoringService": (".authoring", "AgentPlanAuthoringService"),
    "AuthoringPlanCompiler": (".authoring_contract", "AuthoringPlanCompiler"),
    "GenerateTestPlanOptions": (".application", "GenerateTestPlanOptions"),
    "GenerateTestPlanRequest": (".application", "GenerateTestPlanRequest"),
    "GenerateTestPlanUseCase": (".application", "GenerateTestPlanUseCase"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = _EXPORTS[name]
    from importlib import import_module

    module = import_module(module_name, package=__name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
