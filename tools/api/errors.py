"""API-specific error types."""

from tools.common.errors import ValidationError


class AuthConfigurationError(ValidationError):
    """Raised when auth config is missing or invalid."""
