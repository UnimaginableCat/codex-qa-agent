"""Runtime guards for the local QA tools workspace."""

from __future__ import annotations

from pathlib import Path
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


class WorkspaceVenvError(ToolingError):
    """Raised when workspace tooling is not running from the workspace venv."""

    def __init__(
        self,
        *,
        current_executable: Path,
        workspace_root: Path,
        expected_prefixes: tuple[Path, ...],
    ) -> None:
        self.current_executable = current_executable
        self.workspace_root = workspace_root
        self.expected_prefixes = expected_prefixes
        super().__init__(
            "Workspace tooling must run through a venv located directly under the workspace root. "
            f"Current interpreter is '{current_executable}'. "
            "Use one of: "
            + ", ".join(str(path) for path in expected_prefixes)
        )


def ensure_supported_python_version() -> None:
    """Raise when the current interpreter is older than the supported minimum."""

    current_version = sys.version_info[:3]
    if current_version < MIN_SUPPORTED_PYTHON:
        raise UnsupportedPythonVersionError(
            current_version=current_version,
            minimum_version=MIN_SUPPORTED_PYTHON,
        )


def ensure_workspace_venv(*, workspace_root: Path, executable: str | None = None) -> None:
    """Raise unless the interpreter lives inside a root-level workspace .venv* directory."""

    root = workspace_root.resolve()
    current_executable = Path(executable or sys.executable).resolve()
    expected_prefixes = _workspace_venv_prefixes(root)
    if any(_is_relative_to(current_executable, prefix) for prefix in expected_prefixes):
        return
    raise WorkspaceVenvError(
        current_executable=current_executable,
        workspace_root=root,
        expected_prefixes=expected_prefixes,
    )


def _workspace_venv_prefixes(workspace_root: Path) -> tuple[Path, ...]:
    prefixes: list[Path] = []
    if workspace_root.exists():
        for child in workspace_root.iterdir():
            if child.is_dir() and child.name.startswith(".venv"):
                prefixes.append(child.resolve())
    for fallback_name in (".venv314", ".venv"):
        fallback = (workspace_root / fallback_name).resolve()
        if fallback not in prefixes:
            prefixes.append(fallback)
    return tuple(prefixes)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
