from __future__ import annotations

from hashlib import sha1
import re


def slugify(
    value: str,
    *,
    fallback: str,
    invalid_chars_re: str = r"[^A-Za-z0-9_.-]+",
    lowercase: bool = True,
) -> str:
    normalized = value.strip()
    if lowercase:
        normalized = normalized.lower()
    normalized = re.sub(invalid_chars_re, "-", normalized).strip("-._")
    return normalized or fallback


def shorten_slug(
    value: str,
    *,
    max_length: int,
    fallback: str,
    hash_input: str | None = None,
    hash_length: int = 8,
) -> str:
    normalized = value.strip("-._") or fallback
    if len(normalized) <= max_length:
        return normalized

    digest = sha1((hash_input or normalized).encode("utf-8")).hexdigest()[:hash_length]
    prefix_length = max_length - hash_length - 1
    if prefix_length <= 0:
        return digest[:max_length]

    prefix = normalized[:prefix_length].rstrip("-._")
    if not prefix:
        return digest
    return f"{prefix}-{digest}"


def stable_slug(
    value: str,
    *,
    fallback: str,
    max_length: int | None = None,
    invalid_chars_re: str = r"[^A-Za-z0-9_.-]+",
    lowercase: bool = True,
    hash_input: str | None = None,
) -> str:
    slug = slugify(
        value,
        fallback=fallback,
        invalid_chars_re=invalid_chars_re,
        lowercase=lowercase,
    )
    if max_length is None:
        return slug
    return shorten_slug(
        slug,
        max_length=max_length,
        fallback=fallback,
        hash_input=hash_input or value,
    )
