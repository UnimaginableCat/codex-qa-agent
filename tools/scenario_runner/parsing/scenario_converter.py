"""Conversion helpers from parsing IR to runtime scenario domain objects."""

from __future__ import annotations

from typing import Any

from tools.scenario_runner.domain.models import (
    ApiStepDefinition,
    DbStepDefinition,
    ScenarioStep,
    ScenarioStepType,
)

from .contracts.errors import ScenarioParseError
from .steps.ir import ParsedStepDraft


def convert_step_drafts(
    drafts: list[ParsedStepDraft],
    *,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> list[ScenarioStep]:
    """Convert parsed step drafts into runtime ScenarioStep objects."""

    return [convert_step_draft(draft, error_type=error_type) for draft in drafts]


def convert_step_draft(
    draft: ParsedStepDraft,
    *,
    error_type: type[ScenarioParseError] = ScenarioParseError,
) -> ScenarioStep:
    """Convert one parsed step draft into the stable runtime step domain model."""

    raw_type = str(draft.fields.get("type", "")).strip().lower()
    if not raw_type:
        raise error_type(f"Step {draft.step_number} is malformed: missing 'Type:'.")

    try:
        step_type = ScenarioStepType(raw_type)
    except ValueError as exc:
        raise error_type(
            f"Step {draft.step_number} is malformed: unsupported type '{raw_type}'."
        ) from exc

    step_name = str(draft.fields.get("name") or "").strip()
    if not step_name:
        raise error_type(f"Step {draft.step_number} is malformed: missing 'Name:'.")

    step_id = f"step-{draft.step_number}"
    capture = _normalize_string_list(draft.fields.get("capture"))
    expected = _normalize_string_list(draft.fields.get("expected"))
    metadata = {"parse_warnings": draft.warnings, "source_line": draft.line_number}

    if step_type == ScenarioStepType.API:
        method = str(draft.fields.get("method", "")).strip().upper()
        path = str(draft.fields.get("path", "")).strip()
        if not method:
            raise error_type(
                f"Step {draft.step_number} is malformed: API step missing 'Method:'."
            )
        if not path:
            raise error_type(
                f"Step {draft.step_number} is malformed: API step missing 'Path:'."
            )
        api_definition = ApiStepDefinition(
            name=step_name,
            method=method,
            path=path,
            headers=_normalize_mapping(
                draft.fields.get("headers"),
                step_number=draft.step_number,
                field_name="headers",
                error_type=error_type,
            ),
            params=_normalize_mapping(
                draft.fields.get("params"),
                step_number=draft.step_number,
                field_name="params",
                error_type=error_type,
            ),
            body=draft.fields.get("body"),
            retry=_normalize_optional_mapping(
                draft.fields.get("retry"),
                step_number=draft.step_number,
                field_name="retry",
                error_type=error_type,
            ),
            capture=capture,
            expected=expected,
        )
        return ScenarioStep(
            step_id=step_id,
            step_number=draft.step_number,
            title=step_name,
            step_type=step_type,
            api=api_definition,
            metadata=metadata,
        )

    sql = str(draft.fields.get("sql", "")).strip()
    if not sql:
        raise error_type(f"Step {draft.step_number} is malformed: DB step missing 'SQL:'.")

    db_definition = DbStepDefinition(
        name=step_name,
        sql=sql,
        params=_normalize_mapping(
            draft.fields.get("params"),
            step_number=draft.step_number,
            field_name="params",
            error_type=error_type,
        ),
        capture=capture,
        expected=expected,
    )
    return ScenarioStep(
        step_id=step_id,
        step_number=draft.step_number,
        title=step_name,
        step_type=step_type,
        db=db_definition,
        metadata=metadata,
    )


def _normalize_mapping(
    value: Any,
    *,
    step_number: int,
    field_name: str,
    error_type: type[ScenarioParseError],
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise error_type(
            f"Step {step_number} is malformed: '{field_name}' must contain a JSON object."
        )
    return value


def _normalize_optional_mapping(
    value: Any,
    *,
    step_number: int,
    field_name: str,
    error_type: type[ScenarioParseError],
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise error_type(
            f"Step {step_number} is malformed: '{field_name}' must contain an object."
        )
    return value


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []
