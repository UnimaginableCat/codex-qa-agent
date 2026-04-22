"""Common models and helpers shared across tooling packages."""

from .errors import EnvFileLoadError, JsonFileLoadError, ToolingError, ValidationError
from .json_safe import to_json_safe
from .result import ExecutionResult
from .runtime_signals import (
    ContinuationHint,
    NormalizedRuntimeSignal,
    RetryHint,
    RuntimeFailureCategory,
    RuntimeSignalSource,
    RuntimeSignalTag,
    ToolFailureCode,
)
from .statuses import StepStatus

__all__ = [
    "DotenvEnvLoader",
    "EnvFileLoadError",
    "ExecutionResult",
    "JsonFileLoadError",
    "ContinuationHint",
    "NormalizedRuntimeSignal",
    "RetryHint",
    "RuntimeFailureCategory",
    "RuntimeSignalSource",
    "RuntimeSignalTag",
    "StepStatus",
    "ToolFailureCode",
    "ToolingError",
    "ValidationError",
    "read_json_file",
    "to_json_safe",
    "write_text_file",
]


def __getattr__(name: str) -> object:
    if name == "DotenvEnvLoader":
        from .env import DotenvEnvLoader

        return DotenvEnvLoader
    if name in {"read_json_file", "write_text_file"}:
        from .io import read_json_file, write_text_file

        exports = {
            "read_json_file": read_json_file,
            "write_text_file": write_text_file,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
