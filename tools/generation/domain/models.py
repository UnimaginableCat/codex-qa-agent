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


@dataclass(slots=True)
class AgentPlannedTestCaseInput:
    """Agent-authored semantic case before canonical plan assembly."""

    title: str
    objective: str
    kind: str = "functional"
    case_id: str = ""
    preconditions: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    expected_outcomes: list[str] = field(default_factory=list)
    priority: str = "normal"
    tags: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
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
            expected_outcomes=[str(item) for item in payload.get("expected_outcomes", [])],
            priority=str(payload.get("priority", "normal")),
            tags=[str(item) for item in payload.get("tags", [])],
            unresolved_items=[str(item) for item in payload.get("unresolved_items", [])],
            assumptions=[str(item) for item in payload.get("assumptions", [])],
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
    expected_results: list[str] = field(default_factory=list)
    priority: str = "normal"
    assumptions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
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
            expected_results=[str(item) for item in payload.get("expected_results", [])],
            priority=str(payload.get("priority", "normal")),
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            open_questions=[str(item) for item in payload.get("open_questions", [])],
            tags=[str(item) for item in payload.get("tags", [])],
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
    runs_root_dir: Path
    run_state_dir: Path
    artifacts_root_dir: Path
    artifact_dir: Path
    started_at: str
    variables: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GenerationRunContext":
        return cls(
            run_id=str(payload["run_id"]),
            workspace_root=Path(str(payload["workspace_root"])),
            source_id=str(payload["source_id"]),
            project=str(payload["project"]),
            runs_root_dir=Path(str(payload["runs_root_dir"])),
            run_state_dir=Path(str(payload["run_state_dir"])),
            artifacts_root_dir=Path(str(payload["artifacts_root_dir"])),
            artifact_dir=Path(str(payload["artifact_dir"])),
            started_at=str(payload["started_at"]),
            variables=dict(payload.get("variables") or {}),
        )


def _optional_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))
