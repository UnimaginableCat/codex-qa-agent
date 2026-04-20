"""DB-specific error types."""

from tools.common.errors import ValidationError


class SqlSafetyError(ValidationError):
    """Raised when SQL is not allowed for read-only execution."""
