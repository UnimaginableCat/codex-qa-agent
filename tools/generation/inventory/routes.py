"""Route contract validation rules for operation inventory files."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.inventory.common import (
    _diagnostic,
    _is_valid_optional_state_or_state_list,
    _is_valid_request_constraints,
)


_ALLOWED_SAME_STATE_BEHAVIORS = {"reject", "idempotent_success"}
_ACTION_LIKE_ROUTE_SEGMENTS = {
    "calculate",
    "download",
    "export",
    "export-excel",
    "import",
    "report",
    "search",
    "upload",
}


def _route_inventory_diagnostics(
    items: list[Any],
    *,
    path: Path,
    require_method_evidence: bool = False,
    require_action_like_method_evidence: bool = True,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            diagnostics.append(
                _diagnostic(
                    code="adapter_operation_inventory_route_invalid",
                    message="Each route inventory item must be a YAML object.",
                    path=path,
                    details={"route_index": index},
                )
            )
            continue

        diagnostics.extend(_route_required_contract_diagnostics(item, path=path, route_index=index))
        diagnostics.extend(
            _route_method_evidence_diagnostics(
                item,
                path=path,
                route_index=index,
                required=(
                    require_method_evidence
                    or (
                        require_action_like_method_evidence
                        and _is_action_like_route_path(str(item.get("path") or ""))
                    )
                ),
            )
        )
        diagnostics.extend(_route_state_contract_diagnostics(item, path=path, route_index=index))
        diagnostics.extend(_route_same_state_contract_diagnostics(item, path=path, route_index=index))
    return diagnostics


def _route_required_contract_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    route_index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    method = str(item.get("method") or "").strip()
    route_path = str(item.get("path") or "").strip()
    if not method or not route_path:
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_route_missing_fields",
                message="Each route inventory item must include method and path.",
                path=path,
                details={"route_index": route_index},
            )
        )
    if item.get("success_status") is not None and not isinstance(item.get("success_status"), int):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_success_status_invalid",
                message="Route success_status must be an integer.",
                path=path,
                details={"route_index": route_index},
            )
        )
    failure_statuses = item.get("failure_statuses", [])
    if failure_statuses is not None and not isinstance(failure_statuses, list):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_failure_statuses_invalid",
                message="Route failure_statuses must be a YAML array when present.",
                path=path,
                details={"route_index": route_index},
            )
        )
    request_constraints = item.get("request_constraints")
    if request_constraints is not None and not _is_valid_request_constraints(request_constraints):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_request_constraints_invalid",
                message="Entity operation request_constraints must be a YAML array of objects with field and format.",
                path=path,
                details={"route_index": route_index},
            )
        )
    return diagnostics


def _route_method_evidence_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    route_index: int,
    required: bool,
) -> list[GenerationDiagnostic]:
    if not required or _has_method_evidence(item.get("method_evidence"), method=item.get("method")):
        return []
    return [
        _diagnostic(
            code="adapter_operation_inventory_route_method_evidence_missing",
            message=(
                "Route method evidence is required by metadata.contracts.routes.method_evidence_required "
                "or because the path is an action-like endpoint. "
                "Record the router/controller/source line that proves the HTTP method; do not infer methods "
                "from endpoint names such as search, export, or download."
            ),
            path=path,
            details={"route_index": route_index, "method": item.get("method"), "path": item.get("path")},
        )
    ]


def _route_state_contract_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    route_index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    precondition_state = item.get("precondition_state")
    if not _is_valid_optional_state_or_state_list(precondition_state):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_precondition_state_invalid",
                message="Route precondition_state must be a string or YAML array of strings when present.",
                path=path,
                details={"route_index": route_index},
            )
        )
    target_state = item.get("target_state")
    if target_state is not None and not isinstance(target_state, str):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_target_state_invalid",
                message="Route target_state must be a string when present.",
                path=path,
                details={"route_index": route_index},
            )
        )
    return diagnostics


def _route_same_state_contract_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    route_index: int,
) -> list[GenerationDiagnostic]:
    same_state_behavior = item.get("same_state_behavior")
    if same_state_behavior is None:
        return []

    diagnostics: list[GenerationDiagnostic] = []
    normalized_same_state_behavior = (
        str(same_state_behavior).strip().lower()
        if isinstance(same_state_behavior, str)
        else ""
    )
    same_state_status = item.get("same_state_status")
    failure_statuses = item.get("failure_statuses", [])
    target_state = item.get("target_state")

    if normalized_same_state_behavior not in _ALLOWED_SAME_STATE_BEHAVIORS:
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_same_state_behavior_invalid",
                message="Route same_state_behavior must be `reject` or `idempotent_success` when present.",
                path=path,
                details={"route_index": route_index, "same_state_behavior": same_state_behavior},
            )
        )
    if same_state_status is not None and not isinstance(same_state_status, int):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_same_state_status_invalid",
                message="Route same_state_status must be an integer when present.",
                path=path,
                details={"route_index": route_index},
            )
        )
    if same_state_status is None:
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_same_state_contract_incomplete",
                message="Route same_state_behavior requires same_state_status.",
                path=path,
                details={"route_index": route_index, "same_state_behavior": same_state_behavior},
            )
        )
    if not str(target_state or "").strip():
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_same_state_contract_incomplete",
                message="Route same_state_behavior requires target_state so same-state lifecycle cases have an explicit source of truth.",
                path=path,
                details={"route_index": route_index, "same_state_behavior": same_state_behavior},
            )
        )
    if not _has_same_state_evidence(item.get("same_state_evidence")):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_same_state_evidence_missing",
                message=(
                    "Route same_state_behavior must include same_state_evidence with the code or test source "
                    "used to confirm whether reissuing the command rejects or succeeds idempotently."
                ),
                path=path,
                details={"route_index": route_index, "same_state_behavior": same_state_behavior},
            )
        )

    if isinstance(same_state_status, int):
        diagnostics.extend(
            _same_state_status_consistency_diagnostics(
                same_state_behavior=normalized_same_state_behavior,
                same_state_status=same_state_status,
                failure_statuses=failure_statuses,
                path=path,
                route_index=route_index,
            )
        )
    return diagnostics


def _same_state_status_consistency_diagnostics(
    *,
    same_state_behavior: str,
    same_state_status: int,
    failure_statuses: Any,
    path: Path,
    route_index: int,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if same_state_behavior == "idempotent_success" and not (200 <= same_state_status < 300):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_same_state_contract_inconsistent",
                message="same_state_behavior=idempotent_success requires a 2xx same_state_status.",
                path=path,
                details={"route_index": route_index, "same_state_status": same_state_status},
            )
        )
    if same_state_behavior == "reject" and 200 <= same_state_status < 300:
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_same_state_contract_inconsistent",
                message="same_state_behavior=reject must not use a 2xx same_state_status.",
                path=path,
                details={"route_index": route_index, "same_state_status": same_state_status},
            )
        )
    if (
        same_state_behavior == "reject"
        and isinstance(failure_statuses, list)
        and failure_statuses
        and same_state_status not in failure_statuses
    ):
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_same_state_contract_inconsistent",
                message="Rejecting same-state behavior must list same_state_status in failure_statuses.",
                path=path,
                details={"route_index": route_index, "same_state_status": same_state_status},
            )
        )
    return diagnostics


def _has_same_state_evidence(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(isinstance(item, str) and item.strip() for item in value)
    return False


def _has_method_evidence(value: Any, *, method: Any) -> bool:
    if isinstance(value, str):
        return False
    if isinstance(value, list):
        return any(_has_method_evidence(item, method=method) for item in value)
    if isinstance(value, dict):
        has_source = bool(str(value.get("source_ref") or value.get("source") or "").strip())
        evidence_text = str(value.get("method_source") or value.get("evidence") or "").strip()
        has_evidence = bool(evidence_text)
        return has_source and has_evidence and _method_evidence_mentions_declared_method(evidence_text, method)
    return False


def _method_evidence_mentions_declared_method(evidence_text: str, method: Any) -> bool:
    normalized_method = str(method or "").strip().lower()
    if not normalized_method:
        return False
    normalized_evidence = evidence_text.lower()
    if re.search(rf"\b{re.escape(normalized_method)}\b", normalized_evidence):
        return True
    handler_patterns = (
        rf"\.{re.escape(normalized_method)}\b",
        rf"\bdef\s+{re.escape(normalized_method)}\b",
        rf"\b{re.escape(normalized_method)}\s*\(",
    )
    return any(re.search(pattern, normalized_evidence) for pattern in handler_patterns)


def _is_action_like_route_path(route_path: str) -> bool:
    for segment in route_path.strip("/").split("/"):
        normalized_segment = segment.strip().lower()
        if not normalized_segment or normalized_segment.startswith("{{"):
            continue
        if normalized_segment in _ACTION_LIKE_ROUTE_SEGMENTS:
            return True
        tokens = {
            token
            for token in re.split(r"[-_.]+", normalized_segment)
            if token
        }
        if tokens & _ACTION_LIKE_ROUTE_SEGMENTS:
            return True
    return False
