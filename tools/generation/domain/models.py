"""Typed generation pipeline domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe


class DiagnosticSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class SourceInputFormat(StrEnum):
    PROSE = "prose"
    STRUCTURED = "structured"


class GapCategory(StrEnum):
    ENDPOINT_DETAIL = "endpoint_detail"
    EXECUTABLE_DETAIL = "executable_detail"
    AUTH_STRATEGY = "auth_strategy"
    ENVIRONMENT = "environment"
    ASSERTION_DETAIL = "assertion_detail"
    DATA_SETUP = "data_setup"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class PlannedCaseGap:
    """Typed unresolved gap for a planned test case."""

    category: GapCategory
    message: str
    source: str = "agent_authored"

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlannedCaseGap":
        raw_category = str(payload.get("category", GapCategory.UNKNOWN.value))
        try:
            category = GapCategory(raw_category)
        except ValueError:
            category = GapCategory.UNKNOWN
        return cls(
            category=category,
            message=str(payload.get("message", "")),
            source=str(payload.get("source", "agent_authored")),
        )


@dataclass(slots=True)
class PlannedRouteIntent:
    """Typed route intent that can be authored directly in a planned case."""

    http_method: str
    endpoint_path: str
    path_kind: str = ""
    source: str = "agent_authored"

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlannedRouteIntent":
        return cls(
            http_method=str(payload.get("http_method", "")),
            endpoint_path=str(payload.get("endpoint_path", "")),
            path_kind=str(payload.get("path_kind", "")),
            source=str(payload.get("source", "agent_authored")),
        )


@dataclass(slots=True)
class PlannedDbVerification:
    """Typed DB verification step that can accompany a planned case."""

    sql: str
    params: dict[str, Any] = field(default_factory=dict)
    expected_outcomes: list[str] = field(default_factory=list)
    capture: list[str] = field(default_factory=list)
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlannedDbVerification":
        return cls(
            sql=str(payload.get("sql", "")),
            params=dict(payload.get("params") or {}),
            expected_outcomes=[str(item) for item in payload.get("expected_outcomes", [])],
            capture=[str(item) for item in payload.get("capture", [])],
            name=str(payload.get("name", "")),
        )


@dataclass(slots=True)
class PlannedWorkflowStep:
    """Typed workflow step inside one planned end-to-end test case."""

    step_type: str = "api"
    title: str = ""
    route: PlannedRouteIntent | None = None
    request_headers: dict[str, Any] = field(default_factory=dict)
    request_params: dict[str, Any] = field(default_factory=dict)
    request_body: Any = None
    requires_request_body: bool = False
    auth_strategy: list[str] = field(default_factory=list)
    requires_auth_strategy: bool = False
    sql: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    capture: list[str] = field(default_factory=list)
    expected_outcomes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlannedWorkflowStep":
        return cls(
            step_type=str(payload.get("step_type", "api")),
            title=str(payload.get("title", "")),
            route=(
                None
                if payload.get("route") is None
                else PlannedRouteIntent.from_dict(dict(payload.get("route") or {}))
            ),
            request_headers=dict(payload.get("request_headers") or {}),
            request_params=dict(payload.get("request_params") or {}),
            request_body=payload.get("request_body"),
            requires_request_body=bool(payload.get("requires_request_body", False)),
            auth_strategy=[str(item) for item in payload.get("auth_strategy", [])],
            requires_auth_strategy=bool(payload.get("requires_auth_strategy", False)),
            sql=str(payload.get("sql", "")),
            params=dict(payload.get("params") or {}),
            capture=[str(item) for item in payload.get("capture", [])],
            expected_outcomes=[str(item) for item in payload.get("expected_outcomes", [])],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class RouteSupportHint:
    """Typed route support projected from authored data or compatible metadata."""

    fact_id: str = ""
    endpoint_path: str = ""
    http_method: str = ""
    confidence: str = ""
    handler_name: str = ""
    controller_name: str = ""
    framework_hint: str = ""
    match_reasons: list[str] = field(default_factory=list)
    route_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RouteSupportHint":
        return cls(
            fact_id=str(payload.get("fact_id", "")),
            endpoint_path=str(payload.get("endpoint_path", "")),
            http_method=str(payload.get("http_method", "")),
            confidence=str(payload.get("confidence", "")),
            handler_name=str(payload.get("handler_name", "")),
            controller_name=str(payload.get("controller_name", "")),
            framework_hint=str(payload.get("framework_hint", "")),
            match_reasons=[str(item) for item in payload.get("match_reasons", [])],
            route_source=str(payload.get("route_source", "")),
        )


@dataclass(slots=True)
class PlannedCaseSupport:
    """Typed support state for a planned test case after deterministic route projection."""

    readiness: str = ""
    route_hints: list[RouteSupportHint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlannedCaseSupport":
        return cls(
            readiness=str(payload.get("readiness", "")),
            route_hints=[RouteSupportHint.from_dict(item) for item in payload.get("route_hints", [])],
        )


@dataclass(slots=True)
class AgentPlannedTestCaseInput:
    """Agent-authored semantic case before canonical plan assembly."""

    title: str
    objective: str
    kind: str = "functional"
    case_id: str = ""
    preconditions: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    auth_strategy: list[str] = field(default_factory=list)
    requires_auth_strategy: bool = False
    request_headers: dict[str, Any] = field(default_factory=dict)
    request_params: dict[str, Any] = field(default_factory=dict)
    request_body: Any = None
    requires_request_body: bool = False
    observable_outcomes: list[str] = field(default_factory=list)
    expected_outcomes: list[str] = field(default_factory=list)
    capture: list[str] = field(default_factory=list)
    workflow_steps: list[PlannedWorkflowStep] = field(default_factory=list)
    requires_db_verification: bool = False
    priority: str = "normal"
    tags: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)
    gaps: list[PlannedCaseGap] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    route: PlannedRouteIntent | None = None
    db_verification: PlannedDbVerification | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentPlannedTestCaseInput":
        return cls(
            title=str(payload.get("title", "")),
            objective=str(payload.get("objective", "")),
            kind=str(payload.get("kind", "functional")),
            case_id=str(payload.get("case_id", "")),
            preconditions=[str(item) for item in payload.get("preconditions", [])],
            actions=[str(item) for item in payload.get("actions", [])],
            auth_strategy=[str(item) for item in payload.get("auth_strategy", [])],
            requires_auth_strategy=bool(payload.get("requires_auth_strategy", False)),
            request_headers=dict(payload.get("request_headers") or {}),
            request_params=dict(payload.get("request_params") or {}),
            request_body=payload.get("request_body"),
            requires_request_body=bool(payload.get("requires_request_body", False)),
            observable_outcomes=[str(item) for item in payload.get("observable_outcomes", [])],
            expected_outcomes=[str(item) for item in payload.get("expected_outcomes", [])],
            capture=[str(item) for item in payload.get("capture", [])],
            workflow_steps=[PlannedWorkflowStep.from_dict(item) for item in payload.get("workflow_steps", [])],
            requires_db_verification=bool(payload.get("requires_db_verification", False)),
            priority=str(payload.get("priority", "normal")),
            tags=[str(item) for item in payload.get("tags", [])],
            unresolved_items=[str(item) for item in payload.get("unresolved_items", [])],
            gaps=[PlannedCaseGap.from_dict(item) for item in payload.get("gaps", [])],
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            route=(
                None
                if payload.get("route") is None
                else PlannedRouteIntent.from_dict(dict(payload.get("route") or {}))
            ),
            db_verification=(
                None
                if payload.get("db_verification") is None
                else PlannedDbVerification.from_dict(dict(payload.get("db_verification") or {}))
            ),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class AgentTestPlanInput:
    """Agent-authored plan draft accepted as the preferred generation input path."""

    source_id: str
    project: str
    title: str
    goal: str = ""
    planned_test_cases: list[AgentPlannedTestCaseInput] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    evidence_scope: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentTestPlanInput":
        return cls(
            source_id=str(payload.get("source_id", "")),
            project=str(payload.get("project", "")),
            title=str(payload.get("title", "")),
            goal=str(payload.get("goal", "")),
            planned_test_cases=[
                AgentPlannedTestCaseInput.from_dict(item)
                for item in payload.get("planned_test_cases", [])
            ],
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            open_questions=[str(item) for item in payload.get("open_questions", [])],
            evidence_scope=(
                None
                if payload.get("evidence_scope") is None
                else dict(payload.get("evidence_scope") or {})
            ),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class GenerationSourceInput:
    """Source material accepted by the generation pipeline."""

    source_id: str
    project: str
    input_format: SourceInputFormat = SourceInputFormat.PROSE
    name: str = ""
    content: str = ""
    source_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GenerationSourceInput":
        return cls(
            source_id=str(payload["source_id"]),
            project=str(payload["project"]),
            input_format=SourceInputFormat(str(payload.get("input_format", SourceInputFormat.PROSE.value))),
            name=str(payload.get("name", "")),
            content=str(payload.get("content", "")),
            source_path=_optional_path(payload.get("source_path")),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class PlannedTestCase:
    """A planner-level test case, before scenario synthesis."""

    case_id: str
    title: str
    objective: str
    source_refs: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    auth_strategy: list[str] = field(default_factory=list)
    requires_auth_strategy: bool = False
    request_headers: dict[str, Any] = field(default_factory=dict)
    request_params: dict[str, Any] = field(default_factory=dict)
    request_body: Any = None
    requires_request_body: bool = False
    observable_outcomes: list[str] = field(default_factory=list)
    expected_results: list[str] = field(default_factory=list)
    capture: list[str] = field(default_factory=list)
    workflow_steps: list[PlannedWorkflowStep] = field(default_factory=list)
    requires_db_verification: bool = False
    priority: str = "normal"
    assumptions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    gaps: list[PlannedCaseGap] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    planned_route: PlannedRouteIntent | None = None
    db_verification: PlannedDbVerification | None = None
    support: PlannedCaseSupport | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlannedTestCase":
        return cls(
            case_id=str(payload["case_id"]),
            title=str(payload["title"]),
            objective=str(payload.get("objective", "")),
            source_refs=[str(item) for item in payload.get("source_refs", [])],
            preconditions=[str(item) for item in payload.get("preconditions", [])],
            steps=[str(item) for item in payload.get("steps", [])],
            auth_strategy=[str(item) for item in payload.get("auth_strategy", [])],
            requires_auth_strategy=bool(payload.get("requires_auth_strategy", False)),
            request_headers=dict(payload.get("request_headers") or {}),
            request_params=dict(payload.get("request_params") or {}),
            request_body=payload.get("request_body"),
            requires_request_body=bool(payload.get("requires_request_body", False)),
            observable_outcomes=[str(item) for item in payload.get("observable_outcomes", [])],
            expected_results=[str(item) for item in payload.get("expected_results", [])],
            capture=[str(item) for item in payload.get("capture", [])],
            workflow_steps=[PlannedWorkflowStep.from_dict(item) for item in payload.get("workflow_steps", [])],
            requires_db_verification=bool(payload.get("requires_db_verification", False)),
            priority=str(payload.get("priority", "normal")),
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            open_questions=[str(item) for item in payload.get("open_questions", [])],
            gaps=[PlannedCaseGap.from_dict(item) for item in payload.get("gaps", [])],
            tags=[str(item) for item in payload.get("tags", [])],
            planned_route=(
                None
                if payload.get("planned_route") is None
                else PlannedRouteIntent.from_dict(dict(payload.get("planned_route") or {}))
            ),
            db_verification=(
                None
                if payload.get("db_verification") is None
                else PlannedDbVerification.from_dict(dict(payload.get("db_verification") or {}))
            ),
            support=(
                None
                if payload.get("support") is None
                else PlannedCaseSupport.from_dict(dict(payload.get("support") or {}))
            ),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class ProseTestCaseDraft:
    """Deterministically extracted prose-level test case draft."""

    draft_id: str
    title: str
    objective: str
    source_ref: str
    preconditions: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    expected_results: list[str] = field(default_factory=list)
    priority: str = "normal"
    assumptions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProseTestCaseDraft":
        return cls(
            draft_id=str(payload["draft_id"]),
            title=str(payload["title"]),
            objective=str(payload.get("objective", "")),
            source_ref=str(payload["source_ref"]),
            preconditions=[str(item) for item in payload.get("preconditions", [])],
            steps=[str(item) for item in payload.get("steps", [])],
            expected_results=[str(item) for item in payload.get("expected_results", [])],
            priority=str(payload.get("priority", "normal")),
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            open_questions=[str(item) for item in payload.get("open_questions", [])],
            tags=[str(item) for item in payload.get("tags", [])],
        )


@dataclass(slots=True)
class NormalizedProseSource:
    """Intermediate normalized representation of prose generation input."""

    source_id: str
    project: str
    title: str
    normalized_text: str
    test_case_drafts: list[ProseTestCaseDraft] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NormalizedProseSource":
        return cls(
            source_id=str(payload["source_id"]),
            project=str(payload["project"]),
            title=str(payload.get("title", "")),
            normalized_text=str(payload.get("normalized_text", "")),
            test_case_drafts=[
                ProseTestCaseDraft.from_dict(item) for item in payload.get("test_case_drafts", [])
            ],
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            open_questions=[str(item) for item in payload.get("open_questions", [])],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class NormalizedTestPlan:
    """Normalized test-plan representation used before scenario synthesis."""

    plan_id: str
    source_id: str
    project: str
    title: str
    test_cases: list[PlannedTestCase] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NormalizedTestPlan":
        return cls(
            plan_id=str(payload["plan_id"]),
            source_id=str(payload["source_id"]),
            project=str(payload["project"]),
            title=str(payload.get("title", "")),
            test_cases=[
                PlannedTestCase.from_dict(item) for item in payload.get("test_cases", [])
            ],
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class GenerationDiagnostic:
    """Structured diagnostic emitted by generation stages."""

    code: str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.INFO
    source_ref: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GenerationDiagnostic":
        return cls(
            code=str(payload["code"]),
            message=str(payload["message"]),
            severity=DiagnosticSeverity(str(payload.get("severity", DiagnosticSeverity.INFO.value))),
            source_ref=None if payload.get("source_ref") is None else str(payload["source_ref"]),
            details=dict(payload.get("details") or {}),
        )


@dataclass(slots=True)
class TraceabilityLink:
    """A typed relation between source material and generated planning artifacts."""

    source_ref: str
    target_ref: str
    relation: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TraceabilityLink":
        return cls(
            source_ref=str(payload["source_ref"]),
            target_ref=str(payload["target_ref"]),
            relation=str(payload["relation"]),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class TraceabilityMap:
    """Traceability map for a generation run."""

    source_id: str
    links: list[TraceabilityLink] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TraceabilityMap":
        return cls(
            source_id=str(payload["source_id"]),
            links=[TraceabilityLink.from_dict(item) for item in payload.get("links", [])],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class GenerationRunContext:
    """Filesystem and identity context for one generation run."""

    run_id: str
    workspace_root: Path
    source_id: str
    project: str
    artifacts_root_dir: Path
    artifact_dir: Path
    started_at: str
    variables: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GenerationRunContext":
        artifact_dir = payload.get("artifact_dir") or payload.get("run_state_dir")
        if artifact_dir is None:
            raise KeyError("artifact_dir")
        return cls(
            run_id=str(payload["run_id"]),
            workspace_root=Path(str(payload["workspace_root"])),
            source_id=str(payload["source_id"]),
            project=str(payload["project"]),
            artifacts_root_dir=Path(str(payload["artifacts_root_dir"])),
            artifact_dir=Path(str(artifact_dir)),
            started_at=str(payload["started_at"]),
            variables=dict(payload.get("variables") or {}),
        )


def _optional_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))
