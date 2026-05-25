"""Response-field diagnostics for authored API assertions."""

from __future__ import annotations

import re
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic

from ..diagnostics import authoring_diagnostic
from ..models import AuthoringCase, AuthoringPlan


_RESPONSE_LENGTH_ASSERTION_RE = re.compile(
    r"\bresponse\s+(?:`(?P<quoted_path>[^`]+)`|(?P<plain_path>[A-Za-z_][A-Za-z0-9_.\[\]{}]*))\s+length\b",
    re.IGNORECASE,
)


def _response_field_contract_diagnostics(
    authoring_plan: AuthoringPlan,
    case: AuthoringCase,
    case_ref: str,
) -> list[GenerationDiagnostic]:
    asserted_fields = _asserted_collection_response_fields(case)
    if not asserted_fields:
        return []

    evidence_values = _response_body_evidence_values(authoring_plan, case)
    if not evidence_values:
        return [
            authoring_diagnostic(
                "authoring_response_field_evidence_required",
                (
                    "Case asserts response collection fields without response serializer/schema evidence. "
                    "This can render a runnable scenario with a plausible but wrong response path, such as "
                    "`template_items` when the implementation returns `items`."
                ),
                source_ref=case_ref,
                details={
                    "asserted_fields": sorted(asserted_fields),
                    "suggestion": (
                        "Add response_body_evidence/response_schema/response_serializer_evidence to the matching "
                        "operation or case metadata, with explicit response field names from serializer/OpenAPI evidence."
                    ),
                },
            )
        ]

    if not any(_evidence_value_has_response_schema_source(value) for value in evidence_values):
        return [
            authoring_diagnostic(
                "authoring_response_field_schema_source_required",
                (
                    "Case has response field evidence, but it is not tied to a response serializer, schema, "
                    "OpenAPI response contract, or explicit response-body schema."
                ),
                source_ref=case_ref,
                details={"asserted_fields": sorted(asserted_fields)},
            )
        ]

    field_evidence = _response_evidence_fields(_schema_backed_evidence_values(evidence_values))
    missing_fields = sorted(field for field in asserted_fields if field not in field_evidence)
    if not missing_fields:
        return []
    return [
        authoring_diagnostic(
            "authoring_response_field_evidence_required",
            (
                "Case asserts response collection fields that are not named by response serializer/schema evidence. "
                "Use the implementation-backed response field name, or add stronger evidence before promotion."
            ),
            source_ref=case_ref,
            details={
                "asserted_fields": sorted(asserted_fields),
                "evidence_fields": sorted(field_evidence),
                "missing_fields": missing_fields,
            },
        )
    ]


def _asserted_collection_response_fields(case: AuthoringCase) -> set[str]:
    checks = [] if case.oracle is None else case.oracle.business_checks
    fields: set[str] = set()
    for check in checks:
        match = _RESPONSE_LENGTH_ASSERTION_RE.search(str(check))
        if not match:
            continue
        root = _root_response_field(match.group("quoted_path") or match.group("plain_path") or "")
        if root and root != "id":
            fields.add(root)
    return fields


def _root_response_field(path: str) -> str:
    parts = [part.strip().lower() for part in re.split(r"[.\[]", str(path or "")) if part.strip()]
    if not parts:
        return ""
    return parts[0].strip("`] ")


def _response_body_evidence_values(authoring_plan: AuthoringPlan, case: AuthoringCase) -> list[Any]:
    values = [
        case.metadata.get("response_body_evidence"),
        case.metadata.get("response_body_schema"),
        case.metadata.get("response_schema"),
        case.metadata.get("response_evidence"),
        case.metadata.get("response_serializer_evidence"),
    ]
    operation = _matching_execute_operation(authoring_plan, case)
    if operation is not None:
        values.append(operation.response_body_evidence)
    return [value for value in values if _value_has_evidence(value)]


def _matching_execute_operation(authoring_plan: AuthoringPlan, case: AuthoringCase):
    if case.execute is None or case.execute.route is None:
        return None
    method = case.execute.route.method.strip().upper()
    path = case.execute.route.path.strip()
    for entity_spec in authoring_plan.entities.values():
        for operation in entity_spec.operations.values():
            if operation.route is None:
                continue
            if operation.route.method.strip().upper() == method and operation.route.path.strip() == path:
                return operation
    return None


def _value_has_evidence(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list)):
        return bool(value)
    return False


def _schema_backed_evidence_values(values: list[Any]) -> list[Any]:
    schema_backed: list[Any] = []
    for value in values:
        schema_backed.extend(_schema_backed_evidence_items(value))
    return schema_backed


def _schema_backed_evidence_items(value: Any) -> list[Any]:
    if value is None or isinstance(value, str):
        return []
    if isinstance(value, dict):
        if _dict_has_response_schema_source(value):
            return [value]
        schema_backed: list[Any] = []
        for nested in value.values():
            if isinstance(nested, (dict, list, tuple, set)):
                schema_backed.extend(_schema_backed_evidence_items(nested))
        return schema_backed
    if isinstance(value, (list, tuple, set)):
        schema_backed: list[Any] = []
        for item in value:
            schema_backed.extend(_schema_backed_evidence_items(item))
        return schema_backed
    return []


def _evidence_value_has_response_schema_source(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return False
    if isinstance(value, dict):
        if _dict_has_response_schema_source(value):
            return True
        return any(
            _evidence_value_has_response_schema_source(nested)
            for nested in value.values()
            if isinstance(nested, (dict, list, tuple, set))
        )
    if isinstance(value, (list, tuple, set)):
        return any(_evidence_value_has_response_schema_source(item) for item in value)
    return False


def _dict_has_response_schema_source(value: dict[Any, Any]) -> bool:
    normalized_keys = {str(key).strip().lower() for key in value}
    if normalized_keys.intersection({"properties", "response_body_schema", "body_schema", "response_schema", "schema"}):
        return True
    for key, nested in value.items():
        normalized_key = str(key).strip().lower()
        if normalized_key in {
            "source_role",
            "role",
            "source_type",
            "evidence_role",
            "kind",
        } and _value_is_response_schema_role(nested):
            return True
    return False


def _value_is_response_schema_role(value: Any) -> bool:
    if isinstance(value, (list, tuple, set)):
        return any(_value_is_response_schema_role(item) for item in value)
    if isinstance(value, dict):
        return False
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in {
        "response_schema",
        "response_body_schema",
        "response_body",
        "response_serializer",
        "output_serializer",
        "serializer",
        "schema",
        "openapi",
    }


def _response_evidence_fields(values: list[Any]) -> set[str]:
    fields: set[str] = set()
    for value in values:
        fields.update(_fields_from_evidence_value(value))
    return fields


def _fields_from_evidence_value(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return set()
    if isinstance(value, dict):
        fields: set[str] = set()
        for key, nested in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in {
                "field",
                "fields",
                "required",
                "required_fields",
                "body_fields",
                "response_fields",
                "normalized_response_fields",
                "properties",
            }:
                fields.update(_field_names_from_declared_value(nested))
            elif isinstance(nested, (dict, list, tuple, set)):
                fields.update(_fields_from_evidence_value(nested))
        return fields
    if isinstance(value, (list, tuple, set)):
        fields: set[str] = set()
        for item in value:
            fields.update(_fields_from_evidence_value(item))
        return fields
    return set()


def _field_names_from_declared_value(value: Any) -> set[str]:
    if isinstance(value, str):
        return {_root_response_field(value)} if value.strip() else set()
    if isinstance(value, dict):
        return {_root_response_field(str(key)) for key in value if str(key).strip()}
    if isinstance(value, (list, tuple, set)):
        fields: set[str] = set()
        for item in value:
            fields.update(_field_names_from_declared_value(item))
        return fields
    return set()
