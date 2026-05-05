"""Typed models for the compact authoring-plan contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.domain.models import AgentTestPlanInput, GenerationDiagnostic


class AuthoringStateChange(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MUTATE = "mutate"
    NONE = "none"
    READ_ONLY = "read_only"
    READONLY = "readonly"

    @classmethod
    def from_raw(cls, value: Any) -> "AuthoringStateChange | None":
        normalized = normalize_state_change_value(value)
        if not normalized:
            return None
        try:
            return cls(normalized)
        except ValueError:
            return None

    @classmethod
    def allowed_values(cls) -> tuple[str, ...]:
        return tuple(item.value for item in cls)

    @property
    def requires_persistence(self) -> bool:
        return self in {
            AuthoringStateChange.CREATE,
            AuthoringStateChange.UPDATE,
            AuthoringStateChange.DELETE,
            AuthoringStateChange.MUTATE,
        }


AUTHORING_STATE_CHANGE_ALLOWED_TEXT = ", ".join(AuthoringStateChange.allowed_values())


def normalize_state_change_value(value: Any) -> str:
    return str(value or "").strip().lower()


def parse_state_change_or_raw(value: Any) -> AuthoringStateChange | str:
    parsed = AuthoringStateChange.from_raw(value)
    if parsed is not None:
        return parsed
    return str(value or "").strip()


@dataclass(slots=True)
class AuthoringScope:
    surface: str = ""
    style: str = ""
    include: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoringScope":
        return cls(
            surface=str(payload.get("surface", "")),
            style=str(payload.get("style", "")),
            include=[str(item) for item in payload.get("include", [])],
        )


@dataclass(slots=True)
class AuthoringDefaults:
    environment: str = ""
    auth: str = ""
    actor: str = ""
    headers: dict[str, Any] = field(default_factory=dict)
    scenario_variables: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoringDefaults":
        return cls(
            environment=str(payload.get("environment", "")),
            auth=str(payload.get("auth", "")),
            actor=str(payload.get("actor", "")),
            headers=dict(payload.get("headers") or {}),
            scenario_variables=[str(item) for item in payload.get("scenario_variables", [])],
        )


@dataclass(slots=True)
class AuthoringRoute:
    method: str = ""
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoringRoute":
        return cls(
            method=str(payload.get("method", "")),
            path=str(payload.get("path", "")),
        )


@dataclass(slots=True)
class AuthoringExecute:
    route: AuthoringRoute | None = None
    headers: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    auth_strategy: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoringExecute":
        route_payload = payload.get("route")
        return cls(
            route=None if not isinstance(route_payload, dict) else AuthoringRoute.from_dict(route_payload),
            headers=dict(payload.get("headers") or {}),
            params=dict(payload.get("params") or {}),
            body=payload.get("body"),
            auth_strategy=[str(item) for item in payload.get("auth_strategy", [])],
        )


@dataclass(slots=True)
class AuthoringPersistedStateRef:
    entity: str = ""
    operation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoringPersistedStateRef":
        return cls(
            entity=str(payload.get("entity", "")),
            operation=str(payload.get("operation", "")),
        )


@dataclass(slots=True)
class AuthoringOracle:
    status_code: int | None = None
    business_checks: list[str] = field(default_factory=list)
    captures: list[str] = field(default_factory=list)
    persisted_state: AuthoringPersistedStateRef | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoringOracle":
        status_code = payload.get("status_code")
        persisted_payload = payload.get("persisted_state")
        return cls(
            status_code=_maybe_int(status_code),
            business_checks=[str(item) for item in payload.get("business_checks", [])],
            captures=[str(item) for item in payload.get("captures", [])],
            persisted_state=(
                None
                if not isinstance(persisted_payload, dict)
                else AuthoringPersistedStateRef.from_dict(persisted_payload)
            ),
        )


@dataclass(slots=True)
class AuthoringEntityOperation:
    route: AuthoringRoute | None = None
    request_headers: dict[str, Any] = field(default_factory=dict)
    request_params: dict[str, Any] = field(default_factory=dict)
    request_body: Any = None
    request_constraints: list[dict[str, Any]] = field(default_factory=list)
    auth_strategy: list[str] = field(default_factory=list)
    oracle: AuthoringOracle | None = None
    sql: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    expected_outcomes: list[str] = field(default_factory=list)
    captures: list[str] = field(default_factory=list)
    column_types: dict[str, str] = field(default_factory=dict)
    permission_state_effects: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoringEntityOperation":
        execute_payload = payload.get("execute") if isinstance(payload.get("execute"), dict) else None
        route_payload = None
        headers: dict[str, Any] = {}
        request_params: dict[str, Any] = {}
        request_body: Any = None
        auth_strategy: list[str] = []
        if execute_payload is not None:
            route_payload = execute_payload.get("route")
            headers = dict(execute_payload.get("headers") or {})
            request_params = dict(execute_payload.get("params") or {})
            request_body = execute_payload.get("body")
            auth_strategy = [str(item) for item in execute_payload.get("auth_strategy", [])]
        else:
            route_payload = payload.get("route")
            headers = dict(payload.get("request_headers") or payload.get("headers") or {})
            request_params = dict(payload.get("request_params") or {})
            request_body = payload.get("request_body")
            auth_strategy = [str(item) for item in payload.get("auth_strategy", [])]
        oracle_payload = payload.get("oracle")
        return cls(
            route=None if not isinstance(route_payload, dict) else AuthoringRoute.from_dict(route_payload),
            request_headers=headers,
            request_params=request_params,
            request_body=request_body,
            request_constraints=[
                dict(item) for item in payload.get("request_constraints", []) if isinstance(item, dict)
            ],
            auth_strategy=auth_strategy,
            oracle=None if not isinstance(oracle_payload, dict) else AuthoringOracle.from_dict(oracle_payload),
            sql=str(payload.get("sql", "")),
            params=dict(payload.get("params") or {}),
            expected_outcomes=[str(item) for item in payload.get("expected_outcomes", [])],
            captures=[str(item) for item in payload.get("captures", []) or payload.get("capture", [])],
            column_types={str(key): str(value) for key, value in dict(payload.get("column_types") or {}).items()},
            permission_state_effects=[
                dict(item) for item in payload.get("permission_state_effects", []) if isinstance(item, dict)
            ],
        )


@dataclass(slots=True)
class AuthoringEntitySpec:
    id_field: str = ""
    key_fields: list[str] = field(default_factory=list)
    operations: dict[str, AuthoringEntityOperation] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoringEntitySpec":
        operations_payload = payload.get("operations")
        if not isinstance(operations_payload, dict):
            operations_payload = {
                key: value
                for key, value in payload.items()
                if key not in {"id_field", "metadata"} and isinstance(value, dict)
            }
        operations = {
            str(name): AuthoringEntityOperation.from_dict(dict(value))
            for name, value in operations_payload.items()
            if isinstance(value, dict)
        }
        key_fields_payload = payload.get("key_fields")
        return cls(
            id_field=str(payload.get("id_field", "")),
            key_fields=[str(item) for item in key_fields_payload] if isinstance(key_fields_payload, list) else [],
            operations=operations,
        )


@dataclass(slots=True)
class AuthoringSetupStep:
    use_entity: str = ""
    operation: str = ""
    actor: str = ""

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoringSetupStep":
        return cls(
            use_entity=str(payload.get("use_entity", "")),
            operation=str(payload.get("operation", "")),
            actor=str(payload.get("actor", "")),
        )


@dataclass(slots=True)
class AuthoringCase:
    id: str = ""
    kind: str = ""
    title: str = ""
    objective: str = ""
    state_change: AuthoringStateChange | str = ""
    setup: list[AuthoringSetupStep] = field(default_factory=list)
    execute: AuthoringExecute | None = None
    oracle: AuthoringOracle | None = None
    priority: str = "normal"
    tags: list[str] = field(default_factory=list)
    scenario_variables: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    required_permission_state: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoringCase":
        execute_payload = payload.get("execute") if isinstance(payload.get("execute"), dict) else None
        if execute_payload is None and isinstance(payload.get("route_hint"), dict):
            execute_payload = {"route": payload.get("route_hint")}
        oracle_payload = payload.get("oracle")
        if not isinstance(oracle_payload, dict):
            oracle_payload = payload.get("assert")
        return cls(
            id=str(payload.get("id", "")),
            kind=str(payload.get("kind", "")),
            title=str(payload.get("title", "")),
            objective=str(payload.get("objective", "")),
            state_change=parse_state_change_or_raw(payload.get("state_change", "")),
            setup=[
                AuthoringSetupStep.from_dict(item)
                for item in payload.get("setup", [])
                if isinstance(item, dict)
            ],
            execute=None if execute_payload is None else AuthoringExecute.from_dict(execute_payload),
            oracle=None if not isinstance(oracle_payload, dict) else AuthoringOracle.from_dict(oracle_payload),
            priority=str(payload.get("priority", "normal")),
            tags=[str(item) for item in payload.get("tags", [])],
            scenario_variables=[str(item) for item in payload.get("scenario_variables", [])],
            metadata=dict(payload.get("metadata") or {}),
            required_permission_state=[
                dict(item) for item in payload.get("required_permission_state", []) if isinstance(item, dict)
            ],
        )


@dataclass(slots=True)
class AuthoringPlan:
    version: int = 1
    source_id: str = ""
    project: str = ""
    title: str = ""
    goal: str = ""
    scope: AuthoringScope = field(default_factory=AuthoringScope)
    defaults: AuthoringDefaults = field(default_factory=AuthoringDefaults)
    entities: dict[str, AuthoringEntitySpec] = field(default_factory=dict)
    cases: list[AuthoringCase] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AuthoringPlan":
        scope_payload = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        defaults_payload = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}
        entities_payload = payload.get("entities") if isinstance(payload.get("entities"), dict) else {}
        return cls(
            version=_maybe_int(payload.get("version")) or 1,
            source_id=str(payload.get("source_id", "")),
            project=str(payload.get("project", "")),
            title=str(payload.get("title", "")),
            goal=str(payload.get("goal", "")),
            scope=AuthoringScope.from_dict(scope_payload),
            defaults=AuthoringDefaults.from_dict(defaults_payload),
            entities={
                str(name): AuthoringEntitySpec.from_dict(dict(value))
                for name, value in entities_payload.items()
                if isinstance(value, dict)
            },
            cases=[
                AuthoringCase.from_dict(item)
                for item in payload.get("cases", [])
                if isinstance(item, dict)
            ],
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            open_questions=[str(item) for item in payload.get("open_questions", [])],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class AuthoringPlanLoadResult:
    file_path: Path
    authoring_plan: AuthoringPlan | None = None
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))


@dataclass(slots=True)
class AuthoringPlanCompileResult:
    status: StepStatus
    message: str
    file_path: Path | None = None
    authoring_plan: AuthoringPlan | None = None
    compiled_plan: AgentTestPlanInput | None = None
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)
    case_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = to_json_safe(asdict(self))
        payload["status"] = self.status.value
        return payload


def _maybe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
