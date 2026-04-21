"""Path tokenization and lookup helpers for scenario runner payloads."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class PathLookupResult:
    exists: bool
    value: Any = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PathSegment:
    value: str
    from_brackets: bool = False


_BRACKET_INDEX_RE = re.compile(r"\[(.*?)\]")


def resolve_path(root: Any, field_path: str) -> PathLookupResult:
    path_segments = tokenize_path(field_path)
    if not path_segments:
        return PathLookupResult(False, None, "Field path is empty.")
    if root is None:
        return PathLookupResult(False, None, "Root value is missing.")

    current = root
    traversed: list[str] = []
    for segment in path_segments:
        if not segment.value:
            return PathLookupResult(False, None, f"Field path '{field_path}' contains an empty segment.")
        current_location = _format_traversed_path(traversed)

        if segment.from_brackets:
            if not segment.value.isdigit():
                return PathLookupResult(
                    False,
                    None,
                    f"Expected numeric list index in brackets at {current_location}; got '{segment.value}'.",
                )
            if not isinstance(current, list):
                return PathLookupResult(
                    False,
                    None,
                    f"Expected list at {current_location} for index {segment.value}; got {type(current).__name__}.",
                )
            index = int(segment.value)
            if index >= len(current):
                return PathLookupResult(
                    False,
                    None,
                    f"List index {index} is out of range at {current_location}; length is {len(current)}.",
                )
            current = current[index]
            traversed.append(f"[{index}]")
            continue

        if isinstance(current, dict):
            if segment.value not in current:
                return PathLookupResult(
                    False,
                    None,
                    f"Missing path segment '{segment.value}' at {current_location}.",
                )
            current = current[segment.value]
            traversed.append(segment.value)
            continue

        if isinstance(current, list):
            if not segment.value.isdigit():
                return PathLookupResult(
                    False,
                    None,
                    f"Expected numeric list index at segment '{segment.value}' in path '{field_path}'.",
                )
            index = int(segment.value)
            if index >= len(current):
                return PathLookupResult(
                    False,
                    None,
                    f"List index {index} is out of range at {current_location}; length is {len(current)}.",
                )
            current = current[index]
            traversed.append(f"[{index}]")
            continue

        return PathLookupResult(
            False,
            None,
            f"Cannot resolve segment '{segment.value}' at {current_location}; actual type is {type(current).__name__}.",
        )
    return PathLookupResult(True, current, f"Resolved path '{field_path}'.")


def tokenize_path(field_path: str) -> list[PathSegment]:
    normalized_path = _strip_wrapping_quotes(field_path.strip()).strip()
    if not normalized_path:
        return []

    segments: list[PathSegment] = []
    for dotted_part in normalized_path.split("."):
        part = _strip_wrapping_quotes(dotted_part.strip()).strip()
        if not part:
            segments.append(PathSegment(""))
            continue

        cursor = 0
        first_bracket = part.find("[")
        key_end = first_bracket if first_bracket >= 0 else len(part)
        key = _strip_wrapping_quotes(part[:key_end].strip()).strip()
        if key:
            segments.append(PathSegment(key))
        cursor = key_end

        while cursor < len(part):
            if part[cursor] != "[":
                segments.append(PathSegment(part[cursor:].strip()))
                break
            match = _BRACKET_INDEX_RE.match(part, cursor)
            if match is None:
                segments.append(PathSegment(part[cursor:].strip(), from_brackets=True))
                break
            segments.append(PathSegment(match.group(1).strip(), from_brackets=True))
            cursor = match.end()

    return segments


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        return value[1:-1]
    return value


def _format_traversed_path(traversed: list[str]) -> str:
    if not traversed:
        return "<root>"
    rendered = ""
    for segment in traversed:
        if segment.startswith("["):
            rendered += segment
        else:
            rendered = segment if not rendered else f"{rendered}.{segment}"
    return rendered
