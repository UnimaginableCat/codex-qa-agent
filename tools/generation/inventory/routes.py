"""Route contract validation rules for operation inventory files."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.inventory.common import (
    _diagnostic,
    _is_valid_optional_state_or_state_list,
    _is_valid_request_constraints,
)


_ALLOWED_SAME_STATE_BEHAVIORS = {"reject", "idempotent_success"}
_MUTATING_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_ACTION_LIKE_ROUTE_SEGMENTS = {
    "add",
    "add-item",
    "calculate",
    "create",
    "download",
    "duplicate",
    "export",
    "export-excel",
    "import",
    "report",
    "reorder",
    "search",
    "upload",
}
_ROUTE_MAPPING_SOURCE_SUFFIXES = (
    "/urls.py",
    "/routes.py",
    "/router.py",
    "/routing.py",
    "/urls.ts",
    "/routes.ts",
    "/router.ts",
    "/routing.ts",
    "/urls.js",
    "/routes.js",
    "/router.js",
    "/routing.js",
)
_METHOD_CAPABILITY_TOKENS = (
    "method_handler",
    "handler",
    "controller",
    "view",
    "action",
    "implementation",
    "request_handler",
    "http_method",
    "method source",
)
_ROUTE_MAPPING_CAPABILITY_TOKENS = (
    "route_mapping",
    "urlconf",
    "url_conf",
    "router",
    "routing",
    "mount",
)


def _route_inventory_diagnostics(
    items: list[Any],
    *,
    path: Path,
    require_method_evidence: bool = False,
    require_success_status_evidence: bool = False,
    require_runtime_path_evidence: bool = False,
    require_action_like_method_evidence: bool = True,
    require_action_like_status_evidence: bool = True,
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

        status_evidence_required = (
            require_success_status_evidence
            or (
                require_action_like_status_evidence
                and _requires_success_status_evidence(item)
            )
        )
        diagnostics.extend(
            _route_required_contract_diagnostics(
                item,
                path=path,
                route_index=index,
                require_success_status=status_evidence_required,
            )
        )
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
        diagnostics.extend(
            _route_success_status_evidence_diagnostics(
                item,
                path=path,
                route_index=index,
                required=status_evidence_required,
            )
        )
        diagnostics.extend(
            _route_runtime_path_evidence_diagnostics(
                item,
                path=path,
                route_index=index,
                required=require_runtime_path_evidence,
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
    require_success_status: bool,
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
    if item.get("success_status") is None and require_success_status:
        diagnostics.append(
            _diagnostic(
                code="adapter_operation_inventory_success_status_missing",
                message=(
                    "Routes covered by success status evidence requirements must declare success_status explicitly "
                    "so generated cases do not infer HTTP success codes from method or endpoint naming."
                ),
                path=path,
                details={"route_index": route_index, "method": method, "path": route_path},
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
                "Record method-capable evidence from a handler/controller/view/action implementation or test. "
                "Route mapping sources such as URLConf/router files prove mounting, not the implemented HTTP "
                "method, and endpoint names such as search, export, or download are not method evidence."
            ),
            path=path,
            details={"route_index": route_index, "method": item.get("method"), "path": item.get("path")},
        )
    ]


def _route_success_status_evidence_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    route_index: int,
    required: bool,
) -> list[GenerationDiagnostic]:
    success_status = item.get("success_status")
    if success_status is None or not isinstance(success_status, int):
        return []
    if not required or _has_success_status_evidence(
        item.get("success_status_evidence") or item.get("status_evidence"),
        status=success_status,
    ):
        return []
    return [
        _diagnostic(
            code="adapter_operation_inventory_route_success_status_evidence_missing",
            message=(
                "Route success_status evidence is required for mutating/action-like endpoints or by "
                "metadata.contracts.routes.success_status_evidence_required. Record structured evidence from "
                "handler/controller/view/service code, tests, OpenAPI, or docs that explicitly mentions the "
                "declared HTTP success status. Do not infer 201 from POST, create, duplicate, or endpoint names."
            ),
            path=path,
            details={
                "route_index": route_index,
                "method": item.get("method"),
                "path": item.get("path"),
                "success_status": success_status,
            },
        )
    ]


def _route_runtime_path_evidence_diagnostics(
    item: dict[str, Any],
    *,
    path: Path,
    route_index: int,
    required: bool,
) -> list[GenerationDiagnostic]:
    if not required or _has_runtime_path_evidence(item.get("runtime_path_evidence"), route_path=item.get("path")):
        return []
    return [
        _diagnostic(
            code="adapter_operation_inventory_route_runtime_path_evidence_missing",
            message=(
                "Runtime path evidence is required by metadata.contracts.routes.runtime_path_evidence_required. "
                "Record structured evidence for the final request path after API_BASE_URL, using root URLConf, "
                "API gateway/deployment routing, OpenAPI/schema, or a runtime smoke check. App-local urls.py "
                "evidence alone is not sufficient."
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
        source_ref = str(value.get("source_ref") or value.get("source") or "").strip()
        has_source = bool(source_ref)
        if not _method_evidence_source_can_prove_method(value, source_ref):
            return False
        evidence_text = str(value.get("method_source") or value.get("evidence") or "").strip()
        has_evidence = bool(evidence_text)
        return has_source and has_evidence and _method_evidence_mentions_declared_method(evidence_text, method)
    return False


def _has_success_status_evidence(value: Any, *, status: int) -> bool:
    if isinstance(value, str):
        return False
    if isinstance(value, list):
        return any(_has_success_status_evidence(item, status=status) for item in value)
    if isinstance(value, dict):
        source_ref = str(value.get("source_ref") or value.get("source") or "").strip()
        if not source_ref or _is_route_mapping_source(source_ref):
            return False
        explicit_status = value.get("status")
        if explicit_status is None:
            explicit_status = value.get("success_status")
        if explicit_status == status or str(explicit_status).strip() == str(status):
            return True
        evidence_text = " ".join(
            str(value.get(key) or "").strip()
            for key in (
                "status_source",
                "status_evidence",
                "response_status",
                "expected_status",
                "evidence",
            )
        )
        return _status_evidence_mentions_declared_status(evidence_text, status)
    return False


def _status_evidence_mentions_declared_status(evidence_text: str, status: int) -> bool:
    if not evidence_text.strip():
        return False
    return bool(re.search(rf"(?<!\d){re.escape(str(status))}(?!\d)", evidence_text))


def _method_evidence_source_can_prove_method(value: dict[str, Any], source_ref: str) -> bool:
    if _is_route_mapping_source(source_ref):
        return False
    capability_text = _evidence_capability_text(value)
    if any(token in capability_text for token in _ROUTE_MAPPING_CAPABILITY_TOKENS):
        return False
    if any(token in capability_text for token in _METHOD_CAPABILITY_TOKENS):
        return True
    return True


def _evidence_capability_text(value: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "source_role",
        "source_type",
        "evidence_role",
        "evidence_type",
        "capability",
        "capabilities",
        "proves",
        "proof_type",
    ):
        if key in value:
            parts.append(_flatten_evidence_text(value.get(key)))
    return " ".join(parts).replace("-", "_").lower()


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


def _has_runtime_path_evidence(value: Any, *, route_path: Any) -> bool:
    if isinstance(value, str):
        return False
    if isinstance(value, list):
        return any(_has_runtime_path_evidence(item, route_path=route_path) for item in value)
    if not isinstance(value, dict):
        return False

    source_ref = str(value.get("source_ref") or value.get("source") or "").strip()
    evidence_text = str(value.get("evidence") or value.get("runtime_evidence") or "").strip()
    if not source_ref or not evidence_text:
        return False
    if _is_app_local_urlconf_source(source_ref):
        return False

    runtime_path = _runtime_evidence_path(value)
    if not runtime_path:
        return False
    return _route_path_shape(runtime_path) == _route_path_shape(str(route_path or "").strip())


def _runtime_evidence_path(value: dict[str, Any]) -> str:
    for key in ("runtime_path", "mounted_path", "external_path", "path_after_base_url"):
        candidate = str(value.get(key) or "").strip()
        if candidate:
            return _path_part(candidate)
    verified_url = str(value.get("verified_url") or value.get("full_url") or "").strip()
    if verified_url:
        return _path_part(verified_url)
    return ""


def _path_part(value: str) -> str:
    if "://" not in value:
        return value
    parsed = urlsplit(value)
    return parsed.path or "/"


def _route_path_shape(path: str) -> str:
    return re.sub(r"{{\s*[^{}]+?\s*}}", "{{*}}", path.strip())


def _is_app_local_urlconf_source(source_ref: str) -> bool:
    normalized = _strip_source_location_suffix(source_ref).replace("\\", "/").lower()
    return "/apps/" in normalized and normalized.endswith("/urls.py")


def _is_route_mapping_source(source_ref: str) -> bool:
    normalized = _strip_source_location_suffix(source_ref).replace("\\", "/").lower()
    return any(
        normalized.endswith(suffix) or normalized.endswith(suffix.lstrip("/"))
        for suffix in _ROUTE_MAPPING_SOURCE_SUFFIXES
    )


def _strip_source_location_suffix(source_ref: str) -> str:
    stripped = source_ref.strip()
    stripped = re.sub(r"#l\d+$", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r":\d+(?::\d+)?$", "", stripped)
    return stripped


def _flatten_evidence_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten_evidence_text(nested)}" for key, nested in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_evidence_text(item) for item in value)
    return str(value)


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


def _requires_success_status_evidence(item: dict[str, Any]) -> bool:
    method = str(item.get("method") or "").strip().upper()
    if method in _MUTATING_HTTP_METHODS:
        return True
    return _is_action_like_route_path(str(item.get("path") or ""))
