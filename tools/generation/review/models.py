"""Typed contracts for scenario draft review and promotion."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.domain.models import GenerationDiagnostic


class ScenarioDraftParseStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class DraftReadinessCategory(StrEnum):
    PARSER_VALID_PARTIAL = "parser_valid_partial"
    PARSER_VALID_STRONGLY_SUPPORTED = "parser_valid_strongly_supported"
    PARSER_INVALID = "parser_invalid"
    UNSUPPORTED_DEFERRED = "unsupported_deferred"


class DraftPromotionAdvisory(StrEnum):
    SAFE_PREVIEW_ONLY = "safe_preview_only"
    PROMOTABLE_WITH_KNOWN_GAPS = "promotable_with_known_gaps"
    NOT_RECOMMENDED_FOR_PROMOTION = "not_recommended_for_promotion"
    INVALID_DRAFT = "invalid_draft"


class ScenarioRequirementStatus(StrEnum):
    SATISFIED = "satisfied"
    MISSING = "missing"
    PARTIALLY_SATISFIED = "partially_satisfied"


class DraftEditTargetType(StrEnum):
    ADD_REQUEST_BODY = "add_request_body"
    ADD_EXPECTED_ASSERTION = "add_expected_assertion"
    ADD_AUTH_HEADERS = "add_auth_headers"
    ADD_DB_VERIFICATION = "add_db_verification"
    ADD_CAPTURE = "add_capture"
    CLARIFY_NOTES_ONLY = "clarify_notes_only"
    FIX_PARSER_ERRORS = "fix_parser_errors"


class PatchTemplateType(StrEnum):
    SECTION_STUB = "section_stub"
    STRUCTURAL_HINT = "structural_hint"


class ScenarioCompileStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class CompileIssueType(StrEnum):
    PARSE_ERROR = "parse_error"
    COMPILE_ERROR = "compile_error"
    COMPILE_WARNING = "compile_warning"
    VARIABLE_REQUIREMENT = "variable_requirement"
    EXPECTATION_DSL = "expectation_dsl"
    CAPTURE_REFERENCE = "capture_reference"
    STEP_REFERENCE = "step_reference"


class ExecutionReadinessCategory(StrEnum):
    PARSER_INVALID = "parser_invalid"
    COMPILE_BLOCKED = "compile_blocked"
    COMPILE_VALID_BUT_INCOMPLETE = "compile_valid_but_incomplete"
    COMPILE_VALID_RUNNER_READY = "compile_valid_runner_ready"


@dataclass(slots=True)
class ScenarioRequirement:
    requirement_id: str
    description: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioRequirement":
        return cls(
            requirement_id=str(payload["requirement_id"]),
            description=str(payload["description"]),
            required=bool(payload.get("required", True)),
        )


@dataclass(slots=True)
class DraftRequirementCheck:
    requirement: ScenarioRequirement
    status: ScenarioRequirementStatus
    source: str = "unknown"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftRequirementCheck":
        return cls(
            requirement=ScenarioRequirement.from_dict(dict(payload["requirement"])),
            status=ScenarioRequirementStatus(str(payload["status"])),
            source=str(payload.get("source", "unknown")),
            notes=[str(item) for item in payload.get("notes", [])],
        )


@dataclass(slots=True)
class DraftChecklistResult:
    checklist_version: str = "v1"
    total_requirements: int = 0
    satisfied_count: int = 0
    missing_count: int = 0
    partial_count: int = 0
    completeness_ratio: float = 0.0
    checks: list[DraftRequirementCheck] = field(default_factory=list)
    diff_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftChecklistResult":
        return cls(
            checklist_version=str(payload.get("checklist_version", "v1")),
            total_requirements=int(payload.get("total_requirements", 0)),
            satisfied_count=int(payload.get("satisfied_count", 0)),
            missing_count=int(payload.get("missing_count", 0)),
            partial_count=int(payload.get("partial_count", 0)),
            completeness_ratio=float(payload.get("completeness_ratio", 0.0)),
            checks=[DraftRequirementCheck.from_dict(item) for item in payload.get("checks", [])],
            diff_lines=[str(item) for item in payload.get("diff_lines", [])],
        )


@dataclass(slots=True)
class PatchTemplate:
    template_id: str
    target_type: DraftEditTargetType
    section_name: str
    title: str
    description: str
    template_lines: list[str] = field(default_factory=list)
    usage_notes: list[str] = field(default_factory=list)
    template_type: PatchTemplateType = PatchTemplateType.SECTION_STUB

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PatchTemplate":
        return cls(
            template_id=str(payload["template_id"]),
            target_type=DraftEditTargetType(str(payload["target_type"])),
            section_name=str(payload["section_name"]),
            title=str(payload["title"]),
            description=str(payload["description"]),
            template_lines=[str(item) for item in payload.get("template_lines", [])],
            usage_notes=[str(item) for item in payload.get("usage_notes", [])],
            template_type=PatchTemplateType(str(payload.get("template_type", PatchTemplateType.SECTION_STUB.value))),
        )


@dataclass(slots=True)
class PatchTemplateCatalog:
    catalog_version: str = "v1"
    templates: list[PatchTemplate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PatchTemplateCatalog":
        return cls(
            catalog_version=str(payload.get("catalog_version", "v1")),
            templates=[PatchTemplate.from_dict(item) for item in payload.get("templates", [])],
        )


@dataclass(slots=True)
class DraftPatchSuggestion:
    template_id: str = ""
    template_preview: list[str] = field(default_factory=list)
    usage_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftPatchSuggestion":
        return cls(
            template_id=str(payload.get("template_id", "")),
            template_preview=[str(item) for item in payload.get("template_preview", [])],
            usage_notes=[str(item) for item in payload.get("usage_notes", [])],
        )


@dataclass(slots=True)
class DraftEditTarget:
    target_id: str
    draft_id: str
    section_name: str
    target_type: DraftEditTargetType
    reason: str
    related_requirements: list[str] = field(default_factory=list)
    priority: str = "normal"
    suggested_minimum_patch: str = ""
    patch_suggestion: DraftPatchSuggestion = field(default_factory=DraftPatchSuggestion)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftEditTarget":
        return cls(
            target_id=str(payload["target_id"]),
            draft_id=str(payload["draft_id"]),
            section_name=str(payload["section_name"]),
            target_type=DraftEditTargetType(str(payload["target_type"])),
            reason=str(payload["reason"]),
            related_requirements=[str(item) for item in payload.get("related_requirements", [])],
            priority=str(payload.get("priority", "normal")),
            suggested_minimum_patch=str(payload.get("suggested_minimum_patch", "")),
            patch_suggestion=DraftPatchSuggestion.from_dict(dict(payload.get("patch_suggestion") or {})),
        )


@dataclass(slots=True)
class DraftEditTargetList:
    draft_id: str
    targets: list[DraftEditTarget] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftEditTargetList":
        return cls(
            draft_id=str(payload["draft_id"]),
            targets=[DraftEditTarget.from_dict(item) for item in payload.get("targets", [])],
        )


@dataclass(slots=True)
class DraftGapSummary:
    gap_codes: list[str] = field(default_factory=list)
    gap_messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftGapSummary":
        return cls(
            gap_codes=[str(item) for item in payload.get("gap_codes", [])],
            gap_messages=[str(item) for item in payload.get("gap_messages", [])],
        )


@dataclass(slots=True)
class DraftReviewDiagnosticsSummary:
    parse_diagnostics_count: int = 0
    render_diagnostics_count: int = 0
    parse_messages: list[str] = field(default_factory=list)
    render_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftReviewDiagnosticsSummary":
        return cls(
            parse_diagnostics_count=int(payload.get("parse_diagnostics_count", 0)),
            render_diagnostics_count=int(payload.get("render_diagnostics_count", 0)),
            parse_messages=[str(item) for item in payload.get("parse_messages", [])],
            render_codes=[str(item) for item in payload.get("render_codes", [])],
        )


@dataclass(slots=True)
class DeferredDraftReviewItem:
    case_id: str
    title: str
    reason_code: str
    message: str
    readiness_category: DraftReadinessCategory = DraftReadinessCategory.UNSUPPORTED_DEFERRED
    gap_summary: DraftGapSummary = field(default_factory=DraftGapSummary)
    promotion_advisory: DraftPromotionAdvisory = DraftPromotionAdvisory.NOT_RECOMMENDED_FOR_PROMOTION
    checklist: DraftChecklistResult = field(default_factory=DraftChecklistResult)
    edit_targets: DraftEditTargetList = field(default_factory=lambda: DraftEditTargetList(draft_id=""))
    edit_target_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeferredDraftReviewItem":
        return cls(
            case_id=str(payload["case_id"]),
            title=str(payload["title"]),
            reason_code=str(payload["reason_code"]),
            message=str(payload["message"]),
            readiness_category=DraftReadinessCategory(
                str(payload.get("readiness_category", DraftReadinessCategory.UNSUPPORTED_DEFERRED.value))
            ),
            gap_summary=DraftGapSummary.from_dict(dict(payload.get("gap_summary") or {})),
            promotion_advisory=DraftPromotionAdvisory(
                str(
                    payload.get(
                        "promotion_advisory",
                        DraftPromotionAdvisory.NOT_RECOMMENDED_FOR_PROMOTION.value,
                    )
                )
            ),
            checklist=DraftChecklistResult.from_dict(dict(payload.get("checklist") or {})),
            edit_targets=DraftEditTargetList.from_dict(
                dict(payload.get("edit_targets") or {"draft_id": payload.get("case_id", "")})
            ),
            edit_target_count=int(payload.get("edit_target_count", 0)),
        )


@dataclass(slots=True)
class ScenarioDraftReviewItem:
    draft_id: str
    case_id: str
    title: str
    file_path: Path
    parse_status: ScenarioDraftParseStatus
    diagnostics_summary: list[str] = field(default_factory=list)
    has_unsupported_items: bool = False
    has_deferred_items: bool = False
    readiness_category: DraftReadinessCategory = DraftReadinessCategory.PARSER_VALID_PARTIAL
    route_status: str = "unknown"
    gap_summary: DraftGapSummary = field(default_factory=DraftGapSummary)
    promotion_advisory: DraftPromotionAdvisory = DraftPromotionAdvisory.SAFE_PREVIEW_ONLY
    diagnostics_details: DraftReviewDiagnosticsSummary = field(default_factory=DraftReviewDiagnosticsSummary)
    checklist: DraftChecklistResult = field(default_factory=DraftChecklistResult)
    edit_targets: DraftEditTargetList = field(default_factory=lambda: DraftEditTargetList(draft_id=""))
    edit_target_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioDraftReviewItem":
        return cls(
            draft_id=str(payload["draft_id"]),
            case_id=str(payload.get("case_id", "")),
            title=str(payload.get("title", "")),
            file_path=Path(str(payload["file_path"])),
            parse_status=ScenarioDraftParseStatus(str(payload["parse_status"])),
            diagnostics_summary=[str(item) for item in payload.get("diagnostics_summary", [])],
            has_unsupported_items=bool(payload.get("has_unsupported_items", False)),
            has_deferred_items=bool(payload.get("has_deferred_items", False)),
            readiness_category=DraftReadinessCategory(
                str(payload.get("readiness_category", DraftReadinessCategory.PARSER_VALID_PARTIAL.value))
            ),
            route_status=str(payload.get("route_status", "unknown")),
            gap_summary=DraftGapSummary.from_dict(dict(payload.get("gap_summary") or {})),
            promotion_advisory=DraftPromotionAdvisory(
                str(payload.get("promotion_advisory", DraftPromotionAdvisory.SAFE_PREVIEW_ONLY.value))
            ),
            diagnostics_details=DraftReviewDiagnosticsSummary.from_dict(
                dict(payload.get("diagnostics_details") or {})
            ),
            checklist=DraftChecklistResult.from_dict(dict(payload.get("checklist") or {})),
            edit_targets=DraftEditTargetList.from_dict(
                dict(payload.get("edit_targets") or {"draft_id": payload.get("draft_id", "")})
            ),
            edit_target_count=int(payload.get("edit_target_count", 0)),
        )


@dataclass(slots=True)
class ScenarioDraftReviewSet:
    run_id: str
    source_id: str
    artifact_dir: Path
    items: list[ScenarioDraftReviewItem] = field(default_factory=list)
    deferred_items: list[DeferredDraftReviewItem] = field(default_factory=list)
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioDraftReviewSet":
        return cls(
            run_id=str(payload["run_id"]),
            source_id=str(payload["source_id"]),
            artifact_dir=Path(str(payload["artifact_dir"])),
            items=[ScenarioDraftReviewItem.from_dict(item) for item in payload.get("items", [])],
            deferred_items=[
                DeferredDraftReviewItem.from_dict(item) for item in payload.get("deferred_items", [])
            ],
            diagnostics=[GenerationDiagnostic.from_dict(item) for item in payload.get("diagnostics", [])],
        )


@dataclass(slots=True)
class ScenarioPromotionRequest:
    run_id: str
    draft_id: str
    workspace_root: Path = Path(".")
    target_dir: Path = Path("scenarios/generated")
    allow_invalid: bool = False

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))


@dataclass(slots=True)
class ScenarioRevalidationRequest:
    file_path: Path
    validation_mode: str = "parser"

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))


@dataclass(slots=True)
class CompileIssue:
    issue_id: str
    issue_type: CompileIssueType
    message: str
    severity: str = "error"
    source: str = "compile"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CompileIssue":
        return cls(
            issue_id=str(payload["issue_id"]),
            issue_type=CompileIssueType(str(payload["issue_type"])),
            message=str(payload["message"]),
            severity=str(payload.get("severity", "error")),
            source=str(payload.get("source", "compile")),
            details=dict(payload.get("details") or {}),
        )


@dataclass(slots=True)
class ScenarioCompileValidationResult:
    file_path: Path
    parse_status: ScenarioDraftParseStatus
    compile_status: ScenarioCompileStatus = ScenarioCompileStatus.SKIPPED
    issues: list[CompileIssue] = field(default_factory=list)
    warnings: list[CompileIssue] = field(default_factory=list)
    readiness_category: ExecutionReadinessCategory = ExecutionReadinessCategory.PARSER_INVALID
    summary: str = ""
    checks: list[dict[str, Any]] = field(default_factory=list)
    required_external_inputs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioCompileValidationResult":
        return cls(
            file_path=Path(str(payload["file_path"])),
            parse_status=ScenarioDraftParseStatus(str(payload["parse_status"])),
            compile_status=ScenarioCompileStatus(
                str(payload.get("compile_status", ScenarioCompileStatus.SKIPPED.value))
            ),
            issues=[CompileIssue.from_dict(item) for item in payload.get("issues", [])],
            warnings=[CompileIssue.from_dict(item) for item in payload.get("warnings", [])],
            readiness_category=ExecutionReadinessCategory(
                str(payload.get("readiness_category", ExecutionReadinessCategory.PARSER_INVALID.value))
            ),
            summary=str(payload.get("summary", "")),
            checks=[dict(item) for item in payload.get("checks", [])],
            required_external_inputs=[dict(item) for item in payload.get("required_external_inputs", [])],
        )


@dataclass(slots=True)
class ScenarioRevalidationResult:
    file_path: Path
    parse_status: ScenarioDraftParseStatus
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    checklist: DraftChecklistResult = field(default_factory=DraftChecklistResult)
    gap_summary: DraftGapSummary = field(default_factory=DraftGapSummary)
    edit_targets: DraftEditTargetList = field(default_factory=lambda: DraftEditTargetList(draft_id=""))
    promotion_advisory: DraftPromotionAdvisory = DraftPromotionAdvisory.SAFE_PREVIEW_ONLY
    completeness_ratio: float = 0.0
    based_on_generated_draft: bool = False
    generation_run_id: str = ""
    draft_id: str = ""
    validation_mode: str = "parser"
    compile_validation: ScenarioCompileValidationResult | None = None
    execution_readiness_category: ExecutionReadinessCategory = ExecutionReadinessCategory.COMPILE_VALID_BUT_INCOMPLETE

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioRevalidationResult":
        return cls(
            file_path=Path(str(payload["file_path"])),
            parse_status=ScenarioDraftParseStatus(str(payload["parse_status"])),
            diagnostics=[dict(item) for item in payload.get("diagnostics", [])],
            checklist=DraftChecklistResult.from_dict(dict(payload.get("checklist") or {})),
            gap_summary=DraftGapSummary.from_dict(dict(payload.get("gap_summary") or {})),
            edit_targets=DraftEditTargetList.from_dict(
                dict(payload.get("edit_targets") or {"draft_id": payload.get("draft_id", "")})
            ),
            promotion_advisory=DraftPromotionAdvisory(
                str(payload.get("promotion_advisory", DraftPromotionAdvisory.SAFE_PREVIEW_ONLY.value))
            ),
            completeness_ratio=float(payload.get("completeness_ratio", 0.0)),
            based_on_generated_draft=bool(payload.get("based_on_generated_draft", False)),
            generation_run_id=str(payload.get("generation_run_id", "")),
            draft_id=str(payload.get("draft_id", "")),
            validation_mode=str(payload.get("validation_mode", "parser")),
            compile_validation=(
                None
                if not payload.get("compile_validation")
                else ScenarioCompileValidationResult.from_dict(dict(payload["compile_validation"]))
            ),
            execution_readiness_category=ExecutionReadinessCategory(
                str(
                    payload.get(
                        "execution_readiness_category",
                        ExecutionReadinessCategory.COMPILE_VALID_BUT_INCOMPLETE.value,
                    )
                )
            ),
        )


@dataclass(slots=True)
class ScenarioPromotionResult:
    run_id: str
    draft_id: str
    status: StepStatus
    source_path: Path | None = None
    target_path: Path | None = None
    promotion_result_path: Path | None = None
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = to_json_safe(asdict(self))
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioPromotionResult":
        return cls(
            run_id=str(payload["run_id"]),
            draft_id=str(payload["draft_id"]),
            status=StepStatus(str(payload["status"])),
            source_path=_optional_path(payload.get("source_path")),
            target_path=_optional_path(payload.get("target_path")),
            promotion_result_path=_optional_path(payload.get("promotion_result_path")),
            diagnostics=[GenerationDiagnostic.from_dict(item) for item in payload.get("diagnostics", [])],
        )


def _optional_path(value: object) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))
