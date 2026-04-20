"""Shared error types for tooling packages."""


class ToolingError(Exception):
    """Base exception for tooling failures."""


class FileLoadError(ToolingError):
    """Raised when a file cannot be loaded."""


class JsonFileLoadError(FileLoadError):
    """Raised when a JSON file cannot be loaded or parsed."""


class EnvFileLoadError(FileLoadError):
    """Raised when an env file cannot be loaded."""


class ValidationError(ToolingError):
    """Raised when input/config content is invalid."""
