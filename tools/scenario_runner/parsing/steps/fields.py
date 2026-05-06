"""Field extraction for raw scenario step blocks."""

from __future__ import annotations

import json
import re
from typing import cast

from ..contracts.errors import ScenarioParseError
from ..contracts.result import JsonObject, JsonValue
from .blocks import MARKDOWN_STEP_RE
from .ir import ParsedStepDraft, StepBlock, StepFieldKind, StepFields

FIELD_RE = re.compile(r"^(?P<name>[A-Za-z ]+):(?:\s*(?P<value>.*))?$")
KNOWN_STEP_FIELDS = {field.value for field in StepFieldKind}
_SIMPLE_VALUE_FIELDS = {
    StepFieldKind.TYPE.value,
    StepFieldKind.NAME.value,
    StepFieldKind.ACTOR.value,
    StepFieldKind.METHOD.value,
    StepFieldKind.PATH.value,
}
_JSON_BLOCK_FIELDS = {
    StepFieldKind.HEADERS.value,
    StepFieldKind.BODY.value,
    StepFieldKind.PARAMS.value,
}
_BULLET_FIELDS = {StepFieldKind.CAPTURE.value, StepFieldKind.EXPECTED.value}


def parse_step_block(
    block: StepBlock,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> ParsedStepDraft:
    """Extract typed field values from one raw step block."""

    fields: StepFields = {}
    warnings: list[str] = []
    index = 0

    while index < len(block.lines):
        stripped_line = block.lines[index].strip()
        if not stripped_line:
            index += 1
            continue

        field_match = FIELD_RE.match(stripped_line)
        if not field_match:
            warnings.append(
                f"Step {block.step_number} contains unrecognized content at relative line {index + 1}: "
                f"{stripped_line!r}"
            )
            index += 1
            continue

        field_name = field_match.group("name").strip().lower()
        inline_value = (field_match.group("value") or "").strip()
        if field_name in fields:
            raise error_type(
                f"Step {block.step_number} is malformed: duplicate field '{field_name}' "
                f"at relative line {index + 1}."
            )

        if field_name in _SIMPLE_VALUE_FIELDS:
            fields[field_name] = inline_value
            index += 1
            continue

        if field_name in _JSON_BLOCK_FIELDS:
            block_text, index = consume_block(
                block.lines,
                index + 1,
                block.step_number,
                field_name,
                error_type=error_type,
            )
            if inline_value and not block_text:
                block_text = inline_value
            if not block_text:
                fields[field_name] = {} if field_name != StepFieldKind.BODY.value else None
                continue
            fields[field_name] = parse_json_block(block_text, block.step_number, field_name, error_type=error_type)
            continue

        if field_name == StepFieldKind.RETRY.value:
            block_text, index = consume_block(
                block.lines,
                index + 1,
                block.step_number,
                field_name,
                error_type=error_type,
            )
            if inline_value and not block_text:
                block_text = inline_value
            fields[field_name] = parse_retry_block(block_text, block.step_number, error_type=error_type)
            continue

        if field_name == StepFieldKind.SQL.value:
            block_text, index = consume_block(
                block.lines,
                index + 1,
                block.step_number,
                field_name,
                error_type=error_type,
            )
            sql_value = inline_value if inline_value else block_text
            fields[field_name] = sql_value.strip()
            continue

        if field_name in _BULLET_FIELDS:
            bullet_values, next_index = consume_bullets(block.lines, index + 1)
            if inline_value:
                bullet_values.insert(0, inline_value)
            fields[field_name] = bullet_values
            index = next_index
            continue

        warnings.append(f"Step {block.step_number} field '{field_name}' is unknown and was ignored.")
        index += 1

    return ParsedStepDraft(
        step_number=block.step_number,
        line_number=block.line_number,
        fields=fields,
        warnings=warnings,
    )


def consume_block(
    lines: list[str],
    start_index: int,
    step_number: int,
    field_name: str,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> tuple[str, int]:
    index = start_index
    while index < len(lines) and not lines[index].strip():
        index += 1

    if index >= len(lines):
        return "", index

    stripped_line = lines[index].strip()
    if stripped_line.startswith("```"):
        return consume_fenced_block(lines, index, step_number, field_name, error_type=error_type)

    collected: list[str] = []
    while index < len(lines):
        candidate = lines[index]
        stripped_candidate = candidate.strip()
        if is_step_field(stripped_candidate) or MARKDOWN_STEP_RE.match(stripped_candidate):
            break
        collected.append(candidate)
        index += 1

    return "\n".join(trim_empty_lines(collected)).strip(), index


def consume_fenced_block(
    lines: list[str],
    start_index: int,
    step_number: int,
    field_name: str,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> tuple[str, int]:
    index = start_index + 1
    collected: list[str] = []

    while index < len(lines):
        if lines[index].strip().startswith("```"):
            return "\n".join(collected).strip(), index + 1
        collected.append(lines[index])
        index += 1

    raise error_type(
        f"Step {step_number} has malformed fenced block for '{field_name}': missing closing ```."
    )


def consume_bullets(lines: list[str], start_index: int) -> tuple[list[str], int]:
    index = start_index
    values: list[str] = []

    while index < len(lines):
        stripped_line = lines[index].strip()
        if not stripped_line:
            index += 1
            continue
        if not stripped_line.startswith("- "):
            break
        values.append(stripped_line[2:].strip())
        index += 1

    return values, index


def parse_json_block(
    block_text: str,
    step_number: int,
    field_name: str,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> JsonValue:
    try:
        return cast(JsonValue, json.loads(block_text))
    except json.JSONDecodeError as exc:
        raise error_type(f"Step {step_number} has invalid JSON in '{field_name}': {exc.msg}.") from exc


def parse_retry_block(
    block_text: str,
    step_number: int,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> JsonObject | None:
    normalized = block_text.strip()
    if not normalized:
        return None
    if normalized.startswith("{"):
        parsed = parse_json_block(normalized, step_number, "retry", error_type=error_type)
        if not isinstance(parsed, dict):
            raise error_type(f"Step {step_number} is malformed: 'retry' must contain an object.")
        return cast(JsonObject, parsed)

    values: JsonObject = {}
    lines = normalized.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if ":" not in stripped:
            raise error_type(
                f"Step {step_number} has invalid retry config at relative line {index + 1}: {stripped!r}."
            )
        key, raw_value = (part.strip() for part in stripped.split(":", 1))
        if not key:
            raise error_type(f"Step {step_number} has invalid retry config with empty key.")
        if raw_value:
            values[key] = parse_scalar_retry_value(raw_value)
            index += 1
            continue

        list_values: list[JsonValue] = []
        index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            if not candidate:
                index += 1
                continue
            if not candidate.startswith("- "):
                break
            list_values.append(parse_scalar_retry_value(candidate[2:].strip()))
            index += 1
        values[key] = list_values
    return values


def parse_scalar_retry_value(value: str) -> JsonValue:
    normalized = value.strip()
    lowered = normalized.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"-?\d+", normalized):
        return int(normalized)
    if re.fullmatch(r"-?(?:\d+\.\d+|\d+\.|\.\d+)", normalized):
        return float(normalized)
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        return normalized[1:-1]
    return normalized


def trim_empty_lines(lines: list[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and not trimmed[0].strip():
        trimmed.pop(0)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def is_step_field(line: str) -> bool:
    field_match = FIELD_RE.match(line)
    return bool(field_match and field_match.group("name").strip().lower() in KNOWN_STEP_FIELDS)
