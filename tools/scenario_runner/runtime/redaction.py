"""Redaction helpers for persisted runner state and artifacts."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

REDACTED = "***REDACTED***"
_NON_SECRET_TOKEN_KEYS = {"resume_token"}
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)("
    r"password|passwd|secret|token|api[_-]?key|access[_-]?key|refresh[_-]?token|authorization|"
    r"cookies?|session(?:[_-]?(?:id|token))?"
    r")"
)
_HEADER_KEY_PATTERN = re.compile(r"(?i)^(authorization|cookie|set-cookie|x-api-key|proxy-authorization)$")
_DSN_CREDENTIALS_PATTERN = re.compile(
    r"(?P<scheme>\b[a-z][a-z0-9+.\-]*://)"
    r"(?P<username>[^:/@\s]+)"
    r":(?P<password>[^@\s]*)@",
    re.IGNORECASE,
)
_AUTH_HEADER_VALUE_PATTERN = re.compile(r"(?i)^(bearer|basic)\s+.+$")
_AUTH_HEADER_INLINE_PATTERN = re.compile(r"(?i)\b(authorization\s*:\s*)(bearer|basic)\s+\S+")
_COOKIE_INLINE_PATTERN = re.compile(r"(?i)\b(cookie|set-cookie)\s*:\s*([^\r\n]+)")
_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?P<key>password|passwd|secret|token|api[_-]?key|access[_-]?key|refresh[_-]?token)"
    r"(?P<separator>\s*[=:]\s*)(?P<value>[^\s,;]+)"
)


class SensitiveDataRedactor:
    """Recursively redacts secrets from persisted/logged structures."""

    def redact(self, value: Any) -> Any:
        return self._redact_value(value, parent_key=None)

    def _redact_value(self, value: Any, parent_key: str | None) -> Any:
        if isinstance(value, dict):
            return {
                key: self._redact_mapping_value(key, item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item, parent_key=parent_key) for item in value]
        if isinstance(value, tuple):
            return [self._redact_value(item, parent_key=parent_key) for item in value]
        if isinstance(value, str):
            return self._redact_string(value, parent_key=parent_key)
        return deepcopy(value)

    def _redact_mapping_value(self, key: Any, value: Any) -> Any:
        key_text = str(key)
        if self._is_sensitive_key(key_text):
            return REDACTED
        return self._redact_value(value, parent_key=key_text)

    def _redact_string(self, value: str, parent_key: str | None) -> str:
        if parent_key and self._is_header_key(parent_key):
            return REDACTED
        if parent_key and self._is_sensitive_key(parent_key):
            return REDACTED
        if _AUTH_HEADER_VALUE_PATTERN.fullmatch(value.strip()):
            return REDACTED

        redacted = value
        redacted = _DSN_CREDENTIALS_PATTERN.sub(
            lambda match: f"{match.group('scheme')}{match.group('username')}:{REDACTED}@",
            redacted,
        )
        redacted = _AUTH_HEADER_INLINE_PATTERN.sub(
            lambda match: f"{match.group(1)}{match.group(2)} {REDACTED}",
            redacted,
        )
        redacted = _COOKIE_INLINE_PATTERN.sub(lambda match: f"{match.group(1)}: {REDACTED}", redacted)
        redacted = _SENSITIVE_ASSIGNMENT_PATTERN.sub(
            lambda match: f"{match.group('key')}{match.group('separator')}{REDACTED}",
            redacted,
        )
        return redacted

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        if key.strip().lower() in _NON_SECRET_TOKEN_KEYS:
            return False
        return bool(_SENSITIVE_KEY_PATTERN.search(key))

    @staticmethod
    def _is_header_key(key: str) -> bool:
        return bool(_HEADER_KEY_PATTERN.fullmatch(key.strip()))


def redact_sensitive_data(value: Any) -> Any:
    """Return a redacted copy of a potentially sensitive structure."""

    return SensitiveDataRedactor().redact(value)
