"""Runtime guards for the local QA tools workspace."""

from __future__ import annotations

import sys

from .errors import ToolingError

MIN_SUPPORTED_PYTHON = (3, 14)


class UnsupportedPythonVersionError(ToolingError):
    """Raised when the current interpreter is older than the supported minimum."""

    def __init__(
        self,
        current_version: tuple[int, int, int],
        minimum_version: tuple[int, int],
    ) -> None:
        self.current_version = current_version
        self.minimum_version = minimum_version
        super().__init__(
            "Unsupported Python runtime "
            f"{self.current_version_text}. This tools workspace requires Python "
            f"{self.minimum_version_text}+."
        )

    @property
    def current_version_text(self) -> str:
        major, minor, micro = self.current_version
        return f"{major}.{minor}.{micro}"

    @property
    def minimum_version_text(self) -> str:
        major, minor = self.minimum_version
        return f"{major}.{minor}"


def ensure_supported_python_version() -> None:
    """Raise when the current interpreter is older than the supported minimum."""

    current_version = sys.version_info[:3]
    if current_version < MIN_SUPPORTED_PYTHON:
        raise UnsupportedPythonVersionError(
            current_version=current_version,
            minimum_version=MIN_SUPPORTED_PYTHON,
        )
