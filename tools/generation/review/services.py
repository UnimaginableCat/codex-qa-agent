"""Services for reviewing and promoting generated scenario drafts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from tools.common.io import read_json_file
from tools.common.statuses import StepStatus
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic, GenerationRunContext
from tools.generation.persistence.artifacts import (
    GENERATION_RUNS_DIRNAME,
    FileGenerationArtifactStore,
)
from tools.generation.rendering.models import ScenarioDraft, ScenarioDraftValidationResult, ScenarioRenderResult

from .models import (
    CompileIssue,
    CompileIssueType,
    DeferredDraftReviewItem,
    DraftChecklistResult,
    DraftEditTarget,
    DraftEditTargetList,
    DraftEditTargetType,
    DraftGapSummary,
    DraftPromotionAdvisory,
    DraftRequirementCheck,
    DraftReadinessCategory,
    DraftReviewDiagnosticsSummary,
    ExecutionEnvironmentReadinessCategory,
    ExecutionReadinessCategory,
    PreflightIssue,
    PreflightIssueType,
    ScenarioRequirement,
    ScenarioRequirementStatus,
    ScenarioCompileStatus,
    ScenarioCompileValidationResult,
    ScenarioDraftParseStatus,
    ScenarioDraftReviewItem,
    ScenarioDraftReviewSet,
    ScenarioPromotionRequest,
    ScenarioPromotionResult,
    ScenarioPreflightStatus,
    ScenarioPreflightValidationResult,
    ScenarioRevalidationRequest,
    ScenarioRevalidationResult,
)
from .templates import PatchTemplateCatalogService
from tools.scenario_runner.domain.models import ScenarioDefinition, ScenarioStepType
from tools.scenario_runner.orchestration.compiler import CompiledScenario, ScenarioCompiler
from tools.scenario_runner.orchestration.preflight import ScenarioPreflightChecker
from tools.scenario_runner.parser import MarkdownScenarioParser


@dataclass(slots=True)
class ScenarioDraftReviewService:
    """Load generated draft artifacts and expose operator-facing review data."""

    def review(self, run_id: str, *, workspace_root: Path = Path(".")) -> ScenarioDraftReviewSet:
        run_context = _load_run_context(workspace_root, run_id)
        render_result = _load_render_result(run_context)
        validation_by_id = {
            validation.draft_id: validation for validation in render_result.validation_results
        }
        unsupported_by_case_id = _group_unsupported_checks(render_result)
        deferred_by_case_id = {item.case_id: item for item in render_result.draft_set.deferred_items}
        render_diagnostics_by_case_id = _group_render_diagnostics(render_result)
        items = [
            _build_review_item(
                run_context,
                draft,
                validation_by_id.get(draft.draft_id),
                unsupported_by_case_id.get(draft.case_id, []),
                deferred_by_case_id.get(draft.case_id),
                render_diagnostics_by_case_id.get(draft.case_id, []),
            )
            for draft in render_result.draft_set.drafts
        ]
        deferred_items = [
            _build_deferred_review_item(item, unsupported_by_case_id.get(item.case_id, []))
            for item in render_result.draft_set.deferred_items
        ]
        diagnostics: list[GenerationDiagnostic] = []
        if not items:
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_draft_review_empty",
                    message="No scenario drafts were found for this generation run.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=run_id,
                )
            )
        return ScenarioDraftReviewSet(
            run_id=run_context.run_id,
            source_id=run_context.source_id,
            artifact_dir=run_context.artifact_dir,
            items=items,
            deferred_items=deferred_items,
            diagnostics=diagnostics,
        )


@dataclass(slots=True)
class ScenarioDraftPromotionService:
    """Promote explicitly selected parser-valid drafts into scenarios/."""

    review_service: ScenarioDraftReviewService = field(default_factory=ScenarioDraftReviewService)
    artifact_store: FileGenerationArtifactStore = field(default_factory=FileGenerationArtifactStore)

    def promote(self, request: ScenarioPromotionRequest) -> ScenarioPromotionResult:
        diagnostics: list[GenerationDiagnostic] = []
        try:
            run_context = _load_run_context(request.workspace_root, request.run_id)
            render_result = _load_render_result(run_context)
        except Exception as exc:  # noqa: BLE001
            result = ScenarioPromotionResult(
                run_id=request.run_id,
                draft_id=request.draft_id,
                status=StepStatus.ERROR,
                diagnostics=[
                    GenerationDiagnostic(
                        code="scenario_promotion_artifacts_unavailable",
                        message=f"Could not load generation draft artifacts: {exc}",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=request.run_id,
                    )
                ],
            )
            return result

        draft = _find_draft(render_result, request.draft_id)
        validation = _find_validation(render_result, request.draft_id)
        if draft is None:
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_draft_missing",
                    message="Selected draft id does not exist in this generation run.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=request.draft_id,
                )
            )
            return self._finalize(run_context, request, StepStatus.ERROR, diagnostics)

        source_path = run_context.artifact_dir / draft.relative_path
        if not source_path.exists():
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_source_missing",
                    message="Selected draft file is missing from generation artifacts.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(source_path),
                )
            )
            return self._finalize(
                run_context,
                request,
                StepStatus.ERROR,
                diagnostics,
                source_path=source_path,
            )
        if validation is None or not validation.parse_valid:
            if not request.allow_invalid:
                diagnostics.append(
                    GenerationDiagnostic(
                        code="scenario_promotion_invalid_draft",
                        message="Selected draft is not parser-valid; use allow_invalid only after operator review.",
                        severity=DiagnosticSeverity.ERROR,
                        source_ref=request.draft_id,
                    )
                )
                return self._finalize(
                    run_context,
                    request,
                    StepStatus.ERROR,
                    diagnostics,
                    source_path=source_path,
                )
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_invalid_override",
                    message="Invalid draft promotion was allowed by explicit override.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=request.draft_id,
                )
            )

        try:
            target_dir = _resolve_target_dir(request.workspace_root, request.target_dir)
        except ValueError as exc:
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_invalid_target_dir",
                    message=str(exc),
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(request.target_dir),
                )
            )
            return self._finalize(
                run_context,
                request,
                StepStatus.ERROR,
                diagnostics,
                source_path=source_path,
            )
        target_path = target_dir / f"{_slugify(run_context.source_id)}-{_slugify(request.draft_id)}.md"
        if target_path.exists():
            diagnostics.append(
                GenerationDiagnostic(
                    code="scenario_promotion_target_exists",
                    message="Promotion target already exists; existing scenario files are never overwritten.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=str(target_path),
                )
            )
            return self._finalize(
                run_context,
                request,
                StepStatus.ERROR,
                diagnostics,
                source_path=source_path,
                target_path=target_path,
            )

        target_dir.mkdir(parents=True, exist_ok=True)
        draft_content = source_path.read_text(encoding="utf-8")
        target_path.write_text(_promotion_header(run_context.run_id, request.draft_id) + draft_content, encoding="utf-8")
        return self._finalize(
            run_context,
            request,
            StepStatus.PASS,
            diagnostics,
            source_path=source_path,
            target_path=target_path,
        )

    def _finalize(
        self,
        run_context: GenerationRunContext,
        request: ScenarioPromotionRequest,
        status: StepStatus,
        diagnostics: list[GenerationDiagnostic],
        *,
        source_path: Path | None = None,
        target_path: Path | None = None,
    ) -> ScenarioPromotionResult:
        result = ScenarioPromotionResult(
            run_id=request.run_id,
            draft_id=request.draft_id,
            status=status,
            source_path=source_path,
            target_path=target_path,
            diagnostics=diagnostics,
        )
        promotion_result_path = self.artifact_store.write_promotion_result(run_context, result)
        result.promotion_result_path = promotion_result_path
        self.artifact_store.write_promotion_result(run_context, result)
        return result


@dataclass(slots=True)
class ScenarioRevalidationService:
    """Parser-only validation for manually edited draft or promoted scenario files."""

    parser: MarkdownScenarioParser = field(default_factory=MarkdownScenarioParser)
    compile_validator: "ScenarioCompileValidationService" = field(default_factory=lambda: ScenarioCompileValidationService())
    preflight_validator: "ScenarioPreflightValidationService" = field(default_factory=lambda: ScenarioPreflightValidationService())

    def validate(self, request: ScenarioRevalidationRequest) -> ScenarioRevalidationResult:
        file_path = Path(request.file_path)
        markdown = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        parse_result = self.parser.parse_result(file_path)
        parse_status = (
            ScenarioDraftParseStatus.INVALID
            if parse_result.has_errors
            else ScenarioDraftParseStatus.VALID
        )
        metadata = _promotion_metadata(markdown)
        draft_id = metadata.get("draft_id") or _slugify(file_path.stem)
        draft = ScenarioDraft(
            draft_id=draft_id,
            case_id=draft_id,
            title=_revalidation_title(parse_result.scenario, file_path),
            markdown=markdown,
            relative_path=file_path,
            metadata={},
        )
        route_binding = _route_binding_from_scenario(parse_result.scenario)
        validation = ScenarioDraftValidationResult(
            draft_id=draft.draft_id,
            case_id=draft.case_id,
            path=file_path,
            parse_valid=parse_status == ScenarioDraftParseStatus.VALID,
            diagnostics=[diagnostic.to_dict() for diagnostic in parse_result.diagnostics],
        )
        gap_summary = _revalidation_gap_summary(
            draft,
            validation,
            route_binding=route_binding,
            scenario=parse_result.scenario,
        )
        checklist = _build_draft_checklist(
            draft,
            parse_status=parse_status,
            route_binding=route_binding,
            gap_summary=gap_summary,
        )
        readiness_category = _draft_readiness_category(parse_status, route_binding)
        promotion_advisory = _promotion_advisory(
            parse_status=parse_status,
            readiness_category=readiness_category,
            has_unsupported_items=False,
            has_deferred_items=False,
            checklist=checklist,
        )
        edit_targets = _build_edit_targets(
            draft,
            checklist=checklist,
            gap_summary=gap_summary,
            parse_status=parse_status,
            route_binding=route_binding,
        )
        compile_validation = None
        execution_readiness = _parser_only_readiness(parse_status, checklist)
        preflight_validation = None
        environment_readiness = None
        if request.validation_mode in {"compile", "preflight"}:
            compile_validation = self.compile_validator.validate(
                file_path=file_path,
                parse_status=parse_status,
                scenario=parse_result.scenario,
                checklist=checklist,
            )
            execution_readiness = compile_validation.readiness_category
            gap_summary = _merge_compile_gaps(gap_summary, compile_validation)
            edit_targets = _build_edit_targets(
                draft,
                checklist=checklist,
                gap_summary=gap_summary,
                parse_status=parse_status,
                route_binding=route_binding,
            )
        if request.validation_mode == "preflight":
            preflight_validation = self.preflight_validator.validate(
                file_path=file_path,
                workspace_root=Path(request.workspace_root),
                parse_status=parse_status,
                scenario=parse_result.scenario,
            )
            environment_readiness = preflight_validation.readiness_category
            gap_summary = _merge_preflight_gaps(gap_summary, preflight_validation)
            edit_targets = _build_edit_targets(
                draft,
                checklist=checklist,
                gap_summary=gap_summary,
                parse_status=parse_status,
                route_binding=route_binding,
            )

        return ScenarioRevalidationResult(
            file_path=file_path,
            parse_status=parse_status,
            diagnostics=[diagnostic.to_dict() for diagnostic in parse_result.diagnostics],
            checklist=checklist,
            gap_summary=gap_summary,
            edit_targets=edit_targets,
            promotion_advisory=promotion_advisory,
            completeness_ratio=checklist.completeness_ratio,
            based_on_generated_draft=bool(metadata),
            generation_run_id=metadata.get("generation_run_id", ""),
            draft_id=draft_id,
            validation_mode=request.validation_mode,
            compile_validation=compile_validation,
            preflight_validation=preflight_validation,
            execution_readiness_category=execution_readiness,
            environment_readiness_category=environment_readiness,
        )


@dataclass(slots=True)
class ScenarioCompileValidationService:
    """Run scenario compiler checks without preflight, execution, API, or DB calls."""

    compiler: ScenarioCompiler = field(default_factory=ScenarioCompiler)

    def validate(
        self,
        *,
        file_path: Path,
        parse_status: ScenarioDraftParseStatus,
        scenario: ScenarioDefinition | None,
        checklist: DraftChecklistResult,
    ) -> ScenarioCompileValidationResult:
        if parse_status == ScenarioDraftParseStatus.INVALID or scenario is None:
            issue = CompileIssue(
                issue_id="parse:parser_invalid",
                issue_type=CompileIssueType.PARSE_ERROR,
                message="Compile validation was skipped because parser validation failed.",
                severity="error",
                source="parser",
            )
            return ScenarioCompileValidationResult(
                file_path=file_path,
                parse_status=parse_status,
                compile_status=ScenarioCompileStatus.SKIPPED,
                issues=[issue],
                readiness_category=ExecutionReadinessCategory.PARSER_INVALID,
                summary="Parser invalid; compile-only validation was skipped.",
            )

        compiled = self.compiler.compile(scenario)
        compile_result = compiled.compile_result
        issues = [_compile_issue_from_execution_issue(issue, index) for index, issue in enumerate(compile_result.issues)]
        warnings = [
            _compile_warning_from_external_input(requirement, index)
            for index, requirement in enumerate(compile_result.required_external_inputs)
        ]
        compile_status = (
            ScenarioCompileStatus.SUCCESS
            if compile_result.passed
            else ScenarioCompileStatus.FAILED
        )
        readiness = _compile_readiness(
            parse_status=parse_status,
            compile_status=compile_status,
            checklist=checklist,
            warnings=warnings,
        )
        return ScenarioCompileValidationResult(
            file_path=file_path,
            parse_status=parse_status,
            compile_status=compile_status,
            issues=issues,
            warnings=warnings,
            readiness_category=readiness,
            summary=_compile_summary(compile_status, readiness, issues, warnings),
            checks=[check.to_dict() for check in compile_result.checks],
            required_external_inputs=[item.to_dict() for item in compile_result.required_external_inputs],
        )


@dataclass(slots=True)
class ScenarioPreflightValidationService:
    """Run scenario_runner preflight checks without executing scenario steps."""

    compiler: ScenarioCompiler = field(default_factory=ScenarioCompiler)
    preflight_checker: ScenarioPreflightChecker = field(default_factory=ScenarioPreflightChecker)

    def validate(
        self,
        *,
        file_path: Path,
        workspace_root: Path,
        parse_status: ScenarioDraftParseStatus,
        scenario: ScenarioDefinition | None,
    ) -> ScenarioPreflightValidationResult:
        if parse_status == ScenarioDraftParseStatus.INVALID or scenario is None:
            issue = PreflightIssue(
                issue_type=PreflightIssueType.PARSE_ERROR,
                message="Preflight validation was skipped because parser validation failed.",
                severity="error",
                source="parser",
            )
            return ScenarioPreflightValidationResult(
                file_path=file_path,
                parse_status=parse_status,
                compile_status=ScenarioCompileStatus.SKIPPED,
                preflight_status=ScenarioPreflightStatus.SKIPPED,
                readiness_category=ExecutionEnvironmentReadinessCategory.SKIPPED_DUE_TO_PARSER_ERROR,
                issues=[issue],
                summary="Parser invalid; preflight validation was skipped.",
            )

        compiled = self.compiler.compile(scenario)
        if not compiled.compile_result.passed:
            issues = [
                PreflightIssue(
                    issue_type=PreflightIssueType.COMPILE_ERROR,
                    message=issue.message,
                    severity=str((issue.outcome or StepStatus.BLOCKED).value).lower(),
                    source="scenario_compiler",
                    details=issue.to_dict(),
                )
                for issue in compiled.compile_result.issues
            ]
            if not issues:
                issues.append(
                    PreflightIssue(
                        issue_type=PreflightIssueType.COMPILE_ERROR,
                        message="Preflight validation was skipped because compile validation failed.",
                        severity="blocked",
                        source="scenario_compiler",
                    )
                )
            return ScenarioPreflightValidationResult(
                file_path=file_path,
                parse_status=parse_status,
                compile_status=ScenarioCompileStatus.FAILED,
                preflight_status=ScenarioPreflightStatus.SKIPPED,
                readiness_category=ExecutionEnvironmentReadinessCategory.SKIPPED_DUE_TO_COMPILE_ERROR,
                issues=issues,
                summary="Compile blocked; preflight validation was skipped.",
            )

        preflight_result = self.preflight_checker.run(
            CompiledScenario(
                scenario_definition=scenario,
                compile_result=compiled.compile_result,
            ),
            workspace_root,
        )
        issues = [
            _preflight_issue_from_check(check)
            for check in preflight_result.failed_checks()
        ]
        preflight_status = (
            ScenarioPreflightStatus.SUCCESS
            if preflight_result.passed
            else ScenarioPreflightStatus.FAILED
        )
        readiness = _preflight_readiness(preflight_status, issues, warnings=[])
        return ScenarioPreflightValidationResult(
            file_path=file_path,
            parse_status=parse_status,
            compile_status=ScenarioCompileStatus.SUCCESS,
            preflight_status=preflight_status,
            readiness_category=readiness,
            issues=issues,
            warnings=[],
            checks=[check.to_dict() for check in preflight_result.checks],
            summary=_preflight_summary(readiness, issues, warnings=[]),
        )


def _compile_issue_from_execution_issue(issue: object, index: int) -> CompileIssue:
    payload = issue.to_dict()
    code = str(payload.get("code", f"compile_issue_{index}"))
    return CompileIssue(
        issue_id=f"compile:{code}:{index}",
        issue_type=_compile_issue_type(code),
        message=str(payload.get("message", "")),
        severity=str(payload.get("outcome") or "error").lower(),
        source="scenario_compiler",
        details=payload,
    )


def _compile_warning_from_external_input(requirement: object, index: int) -> CompileIssue:
    payload = requirement.to_dict()
    variable_name = str(payload.get("variable_name", ""))
    return CompileIssue(
        issue_id=f"compile:external_input:{variable_name}:{index}",
        issue_type=CompileIssueType.VARIABLE_REQUIREMENT,
        message=f"External variable '{variable_name}' must be resolvable before runner execution.",
        severity="warning",
        source="scenario_compiler",
        details=payload,
    )


def _compile_issue_type(code: str) -> CompileIssueType:
    if "expectation" in code:
        return CompileIssueType.EXPECTATION_DSL
    if "capture" in code:
        return CompileIssueType.CAPTURE_REFERENCE
    if "variable" in code:
        return CompileIssueType.VARIABLE_REQUIREMENT
    if "reference" in code or "step" in code:
        return CompileIssueType.STEP_REFERENCE
    return CompileIssueType.COMPILE_ERROR


def _compile_readiness(
    *,
    parse_status: ScenarioDraftParseStatus,
    compile_status: ScenarioCompileStatus,
    checklist: DraftChecklistResult,
    warnings: list[CompileIssue],
) -> ExecutionReadinessCategory:
    if parse_status == ScenarioDraftParseStatus.INVALID:
        return ExecutionReadinessCategory.PARSER_INVALID
    if compile_status != ScenarioCompileStatus.SUCCESS:
        return ExecutionReadinessCategory.COMPILE_BLOCKED
    if warnings:
        return ExecutionReadinessCategory.COMPILE_VALID_BUT_INCOMPLETE
    if any(check.status != ScenarioRequirementStatus.SATISFIED for check in checklist.checks):
        return ExecutionReadinessCategory.COMPILE_VALID_BUT_INCOMPLETE
    return ExecutionReadinessCategory.COMPILE_VALID_RUNNER_READY


def _compile_summary(
    compile_status: ScenarioCompileStatus,
    readiness: ExecutionReadinessCategory,
    issues: list[CompileIssue],
    warnings: list[CompileIssue],
) -> str:
    if compile_status == ScenarioCompileStatus.SKIPPED:
        return "Compile-only validation was skipped."
    if compile_status == ScenarioCompileStatus.FAILED:
        return f"Compile-only validation failed with {len(issues)} issue(s)."
    if readiness == ExecutionReadinessCategory.COMPILE_VALID_BUT_INCOMPLETE:
        return f"Compile-only validation passed with {len(warnings)} warning(s) or remaining checklist gaps."
    return "Compile-only validation passed and the scenario is structurally runner-ready."


def _parser_only_readiness(
    parse_status: ScenarioDraftParseStatus,
    checklist: DraftChecklistResult,
) -> ExecutionReadinessCategory:
    if parse_status == ScenarioDraftParseStatus.INVALID:
        return ExecutionReadinessCategory.PARSER_INVALID
    if any(check.status != ScenarioRequirementStatus.SATISFIED for check in checklist.checks):
        return ExecutionReadinessCategory.COMPILE_VALID_BUT_INCOMPLETE
    return ExecutionReadinessCategory.COMPILE_VALID_BUT_INCOMPLETE


def _merge_compile_gaps(
    gap_summary: DraftGapSummary,
    compile_validation: ScenarioCompileValidationResult,
) -> DraftGapSummary:
    gap_codes = list(gap_summary.gap_codes)
    gap_messages = list(gap_summary.gap_messages)
    if compile_validation.readiness_category == ExecutionReadinessCategory.COMPILE_BLOCKED:
        gap_codes.append("compile_blocked")
        gap_messages.append("Compile-only validation failed before runner execution.")
    for issue in compile_validation.issues:
        gap_codes.append(issue.details.get("code", issue.issue_type.value))
        gap_messages.append(issue.message)
    if compile_validation.warnings:
        gap_codes.append("external_inputs_required")
        gap_messages.append("One or more external variables must be resolved before execution.")
    for warning in compile_validation.warnings:
        gap_codes.append(warning.issue_type.value)
        gap_messages.append(warning.message)
    return DraftGapSummary(
        gap_codes=_dedupe_preserve_order([str(item) for item in gap_codes]),
        gap_messages=_dedupe_preserve_order([str(item) for item in gap_messages]),
    )


def _preflight_issue_from_check(check: object) -> PreflightIssue:
    payload = check.to_dict()
    name = str(payload.get("name", "preflight_check"))
    return PreflightIssue(
        issue_type=_preflight_issue_type(name),
        message=str(payload.get("message", "")),
        severity=str(payload.get("status", "blocked")).lower(),
        source="scenario_preflight_checker",
        details=payload,
    )


def _preflight_issue_type(check_name: str) -> PreflightIssueType:
    if check_name == "environment_file_exists":
        return PreflightIssueType.MISSING_ENVIRONMENT
    if check_name == "target_project_path_exists":
        return PreflightIssueType.MISSING_PROJECT
    if check_name.startswith("dependency_"):
        return PreflightIssueType.MISSING_DEPENDENCY
    if check_name == "external_inputs_resolvable":
        return PreflightIssueType.EXTERNAL_VARIABLE
    if check_name.startswith("output_directory_available"):
        return PreflightIssueType.WORKSPACE_OUTPUT
    if check_name in {
        "scenario_file_exists",
        "scenario_name_present",
        "project_path_present",
        "environment_path_present",
        "variables_section_valid",
        "steps_present",
        "step_numbers_unique",
    }:
        return PreflightIssueType.SCENARIO_SHAPE
    return PreflightIssueType.UNKNOWN


def _preflight_readiness(
    preflight_status: ScenarioPreflightStatus,
    issues: list[PreflightIssue],
    warnings: list[PreflightIssue],
) -> ExecutionEnvironmentReadinessCategory:
    if preflight_status != ScenarioPreflightStatus.SUCCESS or issues:
        return ExecutionEnvironmentReadinessCategory.PREFLIGHT_BLOCKED
    if warnings:
        return ExecutionEnvironmentReadinessCategory.PREFLIGHT_READY_WITH_WARNINGS
    return ExecutionEnvironmentReadinessCategory.PREFLIGHT_READY


def _preflight_summary(
    readiness: ExecutionEnvironmentReadinessCategory,
    issues: list[PreflightIssue],
    warnings: list[PreflightIssue],
) -> str:
    if readiness == ExecutionEnvironmentReadinessCategory.PREFLIGHT_BLOCKED:
        return f"Preflight validation failed with {len(issues)} issue(s)."
    if readiness == ExecutionEnvironmentReadinessCategory.PREFLIGHT_READY_WITH_WARNINGS:
        return f"Preflight validation passed with {len(warnings)} warning(s)."
    return "Preflight validation passed; workspace is ready for runner execution."


def _merge_preflight_gaps(
    gap_summary: DraftGapSummary,
    preflight_validation: ScenarioPreflightValidationResult,
) -> DraftGapSummary:
    gap_codes = list(gap_summary.gap_codes)
    gap_messages = list(gap_summary.gap_messages)
    if preflight_validation.readiness_category == ExecutionEnvironmentReadinessCategory.PREFLIGHT_BLOCKED:
        gap_codes.append("preflight_blocked")
        gap_messages.append("Preflight validation failed in the current workspace.")
    for issue in preflight_validation.issues:
        gap_codes.append(issue.issue_type.value)
        gap_messages.append(issue.message)
    for warning in preflight_validation.warnings:
        gap_codes.append(warning.issue_type.value)
        gap_messages.append(warning.message)
    return DraftGapSummary(
        gap_codes=_dedupe_preserve_order([str(item) for item in gap_codes]),
        gap_messages=_dedupe_preserve_order([str(item) for item in gap_messages]),
    )


def _load_run_context(workspace_root: Path, run_id: str) -> GenerationRunContext:
    context_path = workspace_root / GENERATION_RUNS_DIRNAME / run_id / "context.json"
    payload = read_json_file(context_path, "Generation run context")
    return GenerationRunContext.from_dict(dict(payload))


def _load_render_result(run_context: GenerationRunContext) -> ScenarioRenderResult:
    payload = read_json_file(run_context.artifact_dir / "scenario-render-result.json", "Scenario render result")
    return ScenarioRenderResult.from_dict(dict(payload))


def _build_review_item(
    run_context: GenerationRunContext,
    draft: ScenarioDraft,
    validation: ScenarioDraftValidationResult | None,
    unsupported_checks: list[object],
    deferred_item: object | None,
    render_diagnostics: list[GenerationDiagnostic],
) -> ScenarioDraftReviewItem:
    parse_status = (
        ScenarioDraftParseStatus.VALID
        if validation is not None and validation.parse_valid
        else ScenarioDraftParseStatus.INVALID
    )
    diagnostics_summary = []
    if validation is None:
        diagnostics_summary.append("No parser validation result was found for this draft.")
    else:
        diagnostics_summary.extend(str(item.get("message", "")) for item in validation.diagnostics if item.get("message"))
    route_binding = dict(draft.metadata.get("route_binding") or {})
    gap_summary = _draft_gap_summary(
        draft,
        validation,
        route_binding=route_binding,
        render_diagnostics=render_diagnostics,
        has_unsupported_items=bool(unsupported_checks),
        has_deferred_items=deferred_item is not None,
    )
    diagnostics_details = DraftReviewDiagnosticsSummary(
        parse_diagnostics_count=0 if validation is None else len(validation.diagnostics),
        render_diagnostics_count=len(render_diagnostics),
        parse_messages=diagnostics_summary,
        render_codes=[diagnostic.code for diagnostic in render_diagnostics],
    )
    readiness_category = _draft_readiness_category(parse_status, route_binding)
    promotion_advisory = _promotion_advisory(
        parse_status=parse_status,
        readiness_category=readiness_category,
        has_unsupported_items=bool(unsupported_checks),
        has_deferred_items=deferred_item is not None,
        checklist=_build_draft_checklist(
            draft,
            parse_status=parse_status,
            route_binding=route_binding,
            gap_summary=gap_summary,
        ),
    )
    checklist = _build_draft_checklist(
        draft,
        parse_status=parse_status,
        route_binding=route_binding,
        gap_summary=gap_summary,
    )
    edit_targets = _build_edit_targets(
        draft,
        checklist=checklist,
        gap_summary=gap_summary,
        parse_status=parse_status,
        route_binding=route_binding,
    )
    return ScenarioDraftReviewItem(
        draft_id=draft.draft_id,
        case_id=draft.case_id,
        title=draft.title,
        file_path=run_context.artifact_dir / draft.relative_path,
        parse_status=parse_status,
        diagnostics_summary=diagnostics_summary,
        has_unsupported_items=bool(unsupported_checks),
        has_deferred_items=deferred_item is not None,
        readiness_category=readiness_category,
        route_status=_route_status(route_binding),
        gap_summary=gap_summary,
        promotion_advisory=promotion_advisory,
        diagnostics_details=diagnostics_details,
        checklist=checklist,
        edit_targets=edit_targets,
        edit_target_count=len(edit_targets.targets),
    )


def _build_deferred_review_item(
    deferred_item: object,
    unsupported_checks: list[object],
) -> DeferredDraftReviewItem:
    gap_summary = _deferred_gap_summary(unsupported_checks)
    edit_targets = _build_deferred_edit_targets(deferred_item.case_id, gap_summary)
    return DeferredDraftReviewItem(
        case_id=deferred_item.case_id,
        title=deferred_item.title,
        reason_code=deferred_item.reason_code,
        message=deferred_item.message,
        gap_summary=gap_summary,
        promotion_advisory=DraftPromotionAdvisory.NOT_RECOMMENDED_FOR_PROMOTION,
        checklist=_build_deferred_checklist(gap_summary),
        edit_targets=edit_targets,
        edit_target_count=len(edit_targets.targets),
    )


def _find_draft(render_result: ScenarioRenderResult, draft_id: str) -> ScenarioDraft | None:
    for draft in render_result.draft_set.drafts:
        if draft.draft_id == draft_id:
            return draft
    return None


def _find_validation(
    render_result: ScenarioRenderResult,
    draft_id: str,
) -> ScenarioDraftValidationResult | None:
    for validation in render_result.validation_results:
        if validation.draft_id == draft_id:
            return validation
    return None


def _group_unsupported_checks(render_result: ScenarioRenderResult) -> dict[str, list[object]]:
    grouped: dict[str, list[object]] = {}
    for check in render_result.unsupported_checks:
        grouped.setdefault(check.case_id, []).append(check)
    return grouped


def _group_render_diagnostics(render_result: ScenarioRenderResult) -> dict[str, list[GenerationDiagnostic]]:
    grouped: dict[str, list[GenerationDiagnostic]] = {}
    for diagnostic in render_result.diagnostics:
        if diagnostic.source_ref:
            grouped.setdefault(diagnostic.source_ref, []).append(diagnostic)
    return grouped


def _draft_gap_summary(
    draft: ScenarioDraft,
    validation: ScenarioDraftValidationResult | None,
    *,
    route_binding: dict[str, object],
    render_diagnostics: list[GenerationDiagnostic],
    has_unsupported_items: bool,
    has_deferred_items: bool,
) -> DraftGapSummary:
    gap_codes: list[str] = []
    gap_messages: list[str] = []
    parse_valid = validation is not None and validation.parse_valid
    if not parse_valid:
        gap_codes.append("parser_invalid")
        gap_messages.append("Draft is not parser-valid.")

    method = str(route_binding.get("http_method") or "").upper()
    if method in {"POST", "PUT", "PATCH"}:
        gap_codes.append("request_body_not_inferred")
        gap_messages.append("Request body not inferred.")
    gap_codes.extend(
        [
            "auth_headers_unresolved",
            "assertions_not_generated",
            "db_verification_absent",
            "captures_not_generated",
        ]
    )
    gap_messages.extend(
        [
            "Auth/header requirements remain unresolved.",
            "Assertions were not generated.",
            "DB verification steps are absent.",
            "Captures were not generated.",
        ]
    )

    readiness = str(route_binding.get("readiness") or "")
    if readiness == "route_resolved":
        gap_codes.append("non_route_requirements_remaining")
        gap_messages.append("Route is resolved, but non-route execution details still remain.")

    for diagnostic in render_diagnostics:
        if diagnostic.code == "rendered_with_partial_information":
            continue
        if diagnostic.code not in gap_codes:
            gap_codes.append(diagnostic.code)
            gap_messages.append(diagnostic.message)
    if has_unsupported_items:
        gap_codes.append("unsupported_items_present")
        gap_messages.append("Unsupported review items are associated with this draft.")
    if has_deferred_items:
        gap_codes.append("deferred_items_present")
        gap_messages.append("Deferred review items are associated with this draft.")
    return DraftGapSummary(
        gap_codes=_dedupe_preserve_order(gap_codes),
        gap_messages=_dedupe_preserve_order(gap_messages),
    )


def _revalidation_gap_summary(
    draft: ScenarioDraft,
    validation: ScenarioDraftValidationResult,
    *,
    route_binding: dict[str, object],
    scenario: ScenarioDefinition | None,
) -> DraftGapSummary:
    gap_codes: list[str] = []
    gap_messages: list[str] = []
    if not validation.parse_valid:
        gap_codes.append("parser_invalid")
        gap_messages.append("Scenario file is not parser-valid.")

    api_step = _first_api_step(scenario)
    method = str(route_binding.get("http_method") or "").upper()
    if api_step is not None and method in {"POST", "PUT", "PATCH"} and api_step.api is not None and api_step.api.body is None:
        gap_codes.append("request_body_not_inferred")
        gap_messages.append("Request body or minimal request structure is missing.")

    has_step_expectation = any(
        step.api is not None and step.api.expected
        for step in (scenario.steps if scenario is not None else [])
        if step.step_type == ScenarioStepType.API
    )
    has_db_expectation = any(
        step.db is not None and step.db.expected
        for step in (scenario.steps if scenario is not None else [])
        if step.step_type == ScenarioStepType.DB
    )
    has_final_expectation = bool(scenario is not None and scenario.final_expectations)
    if not (has_step_expectation or has_db_expectation or has_final_expectation):
        gap_codes.append("assertions_not_generated")
        gap_messages.append("No concrete expected result or assertion was found.")

    if scenario is not None and len(scenario.steps) > 1:
        has_capture = any(
            (step.api is not None and step.api.capture) or (step.db is not None and step.db.capture)
            for step in scenario.steps
        )
        if not has_capture:
            gap_codes.append("captures_not_generated")
            gap_messages.append("Multiple-step scenario has no captures; add them only if later steps need prior values.")

    return DraftGapSummary(
        gap_codes=_dedupe_preserve_order(gap_codes),
        gap_messages=_dedupe_preserve_order(gap_messages),
    )


def _deferred_gap_summary(unsupported_checks: list[object]) -> DraftGapSummary:
    gap_codes: list[str] = []
    gap_messages: list[str] = []
    for check in unsupported_checks:
        gap_codes.append(str(check.reason_code))
        gap_messages.append(str(check.message))
    if not gap_codes:
        gap_codes.append("unsupported_for_preview")
        gap_messages.append("Draft preview is unsupported for this case.")
    return DraftGapSummary(
        gap_codes=_dedupe_preserve_order(gap_codes),
        gap_messages=_dedupe_preserve_order(gap_messages),
    )


def _draft_readiness_category(
    parse_status: ScenarioDraftParseStatus,
    route_binding: dict[str, object],
) -> DraftReadinessCategory:
    if parse_status == ScenarioDraftParseStatus.INVALID:
        return DraftReadinessCategory.PARSER_INVALID
    readiness = str(route_binding.get("readiness") or "")
    if readiness == "evidence_supported":
        return DraftReadinessCategory.PARSER_VALID_STRONGLY_SUPPORTED
    return DraftReadinessCategory.PARSER_VALID_PARTIAL


def _promotion_advisory(
    *,
    parse_status: ScenarioDraftParseStatus,
    readiness_category: DraftReadinessCategory,
    has_unsupported_items: bool,
    has_deferred_items: bool,
    checklist: DraftChecklistResult,
) -> DraftPromotionAdvisory:
    if parse_status == ScenarioDraftParseStatus.INVALID:
        return DraftPromotionAdvisory.INVALID_DRAFT
    if has_unsupported_items or has_deferred_items:
        return DraftPromotionAdvisory.NOT_RECOMMENDED_FOR_PROMOTION
    core_missing = {
        check.requirement.requirement_id
        for check in checklist.checks
        if check.requirement.required and check.status == ScenarioRequirementStatus.MISSING
    }
    if core_missing & {"parser_valid", "endpoint_path", "http_method"}:
        return DraftPromotionAdvisory.SAFE_PREVIEW_ONLY
    if not core_missing:
        return DraftPromotionAdvisory.PROMOTABLE_WITH_KNOWN_GAPS
    if readiness_category == DraftReadinessCategory.PARSER_VALID_STRONGLY_SUPPORTED:
        if not core_missing or core_missing <= {"request_structure", "assertions"}:
            return DraftPromotionAdvisory.PROMOTABLE_WITH_KNOWN_GAPS
    if readiness_category == DraftReadinessCategory.PARSER_VALID_STRONGLY_SUPPORTED:
        return DraftPromotionAdvisory.PROMOTABLE_WITH_KNOWN_GAPS
    return DraftPromotionAdvisory.SAFE_PREVIEW_ONLY


def _route_status(route_binding: dict[str, object]) -> str:
    if not route_binding:
        return "unresolved"
    source = str(route_binding.get("route_source") or "")
    confidence = str(route_binding.get("confidence") or "")
    if confidence == "weak_inference":
        return "low_confidence"
    if source == "route_hints":
        return "resolved_from_route_hints"
    if source == "evidence_hints":
        return "resolved_from_legacy_evidence"
    return "resolved"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _build_draft_checklist(
    draft: ScenarioDraft,
    *,
    parse_status: ScenarioDraftParseStatus,
    route_binding: dict[str, object],
    gap_summary: DraftGapSummary,
) -> DraftChecklistResult:
    requirement_defs = [
        ScenarioRequirement("parser_valid", "Draft parses successfully as scenario markdown."),
        ScenarioRequirement("endpoint_path", "Endpoint path is defined."),
        ScenarioRequirement("http_method", "HTTP method is defined."),
        ScenarioRequirement("request_structure", "Request structure is defined."),
        ScenarioRequirement("assertions", "Expected result or assertion is defined."),
        ScenarioRequirement("auth_strategy", "Auth/header strategy is defined.", required=False),
        ScenarioRequirement("db_verification", "DB verification is defined when needed.", required=False),
        ScenarioRequirement("captures", "Captures are defined when later steps need them.", required=False),
    ]
    gap_codes = set(gap_summary.gap_codes)
    checks = [
        _check_parser_valid(parse_status),
        _check_endpoint_path(route_binding, draft),
        _check_http_method(route_binding, draft),
        _check_request_structure(route_binding, draft, gap_codes),
        _check_assertions(draft, gap_codes),
        _check_auth_strategy(gap_codes),
        _check_db_verification(gap_codes),
        _check_captures(gap_codes),
    ]
    # keep requirement descriptions canonical even if helper changed fields
    checks_by_id = {check.requirement.requirement_id: check for check in checks}
    ordered_checks = []
    for requirement in requirement_defs:
        check = checks_by_id[requirement.requirement_id]
        check.requirement = requirement
        ordered_checks.append(check)

    satisfied = sum(1 for check in ordered_checks if check.status == ScenarioRequirementStatus.SATISFIED)
    missing = sum(1 for check in ordered_checks if check.status == ScenarioRequirementStatus.MISSING)
    partial = sum(
        1 for check in ordered_checks if check.status == ScenarioRequirementStatus.PARTIALLY_SATISFIED
    )
    total = len(ordered_checks)
    completeness_ratio = 0.0 if total == 0 else round((satisfied + 0.5 * partial) / total, 3)
    return DraftChecklistResult(
        checklist_version="v1",
        total_requirements=total,
        satisfied_count=satisfied,
        missing_count=missing,
        partial_count=partial,
        completeness_ratio=completeness_ratio,
        checks=ordered_checks,
        diff_lines=[_diff_line(check) for check in ordered_checks],
    )


def _build_deferred_checklist(gap_summary: DraftGapSummary) -> DraftChecklistResult:
    checks = [
        DraftRequirementCheck(
            requirement=ScenarioRequirement("parser_valid", "Draft parses successfully as scenario markdown."),
            status=ScenarioRequirementStatus.MISSING,
            source="unknown",
            notes=["No rendered draft is available for parser validation."],
        ),
        DraftRequirementCheck(
            requirement=ScenarioRequirement("endpoint_path", "Endpoint path is defined."),
            status=ScenarioRequirementStatus.MISSING,
            source="unknown",
            notes=list(gap_summary.gap_messages) or ["Endpoint route is not available for this case."],
        ),
        DraftRequirementCheck(
            requirement=ScenarioRequirement("http_method", "HTTP method is defined."),
            status=ScenarioRequirementStatus.MISSING,
            source="unknown",
            notes=list(gap_summary.gap_messages) or ["HTTP method is not available for this case."],
        ),
    ]
    total = len(checks)
    missing = total
    return DraftChecklistResult(
        checklist_version="v1",
        total_requirements=total,
        satisfied_count=0,
        missing_count=missing,
        partial_count=0,
        completeness_ratio=0.0,
        checks=checks,
        diff_lines=[_diff_line(check) for check in checks],
    )


def _check_parser_valid(parse_status: ScenarioDraftParseStatus) -> DraftRequirementCheck:
    status = (
        ScenarioRequirementStatus.SATISFIED
        if parse_status == ScenarioDraftParseStatus.VALID
        else ScenarioRequirementStatus.MISSING
    )
    notes = [] if status == ScenarioRequirementStatus.SATISFIED else ["Draft is not parser-valid."]
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("parser_valid", ""),
        status=status,
        source="parser",
        notes=notes,
    )


def _check_endpoint_path(route_binding: dict[str, object], draft: ScenarioDraft) -> DraftRequirementCheck:
    endpoint_path = str(route_binding.get("endpoint_path") or "")
    if endpoint_path:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("endpoint_path", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source=str(route_binding.get("route_source") or "route_binding"),
            notes=[f"Endpoint path resolved as {endpoint_path}."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("endpoint_path", ""),
        status=ScenarioRequirementStatus.MISSING,
        source="unknown",
        notes=["Endpoint path is missing from route binding and draft metadata."],
    )


def _check_http_method(route_binding: dict[str, object], draft: ScenarioDraft) -> DraftRequirementCheck:
    http_method = str(route_binding.get("http_method") or "").upper()
    if http_method:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("http_method", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source=str(route_binding.get("route_source") or "route_binding"),
            notes=[f"HTTP method resolved as {http_method}."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("http_method", ""),
        status=ScenarioRequirementStatus.MISSING,
        source="unknown",
        notes=["HTTP method is missing from route binding and draft metadata."],
    )


def _check_request_structure(
    route_binding: dict[str, object],
    draft: ScenarioDraft,
    gap_codes: set[str],
) -> DraftRequirementCheck:
    http_method = str(route_binding.get("http_method") or "").upper()
    if http_method in {"GET", "DELETE"}:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("request_structure", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source=str(route_binding.get("route_source") or "route_binding"),
            notes=["Method and path are enough for a minimal request shape."],
        )
    if "request_body_not_inferred" in gap_codes:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("request_structure", ""),
            status=ScenarioRequirementStatus.MISSING,
            source="unknown",
            notes=["Request body or minimal request structure must be added manually."],
        )
    if any(marker in draft.markdown for marker in ("Body:", "Payload:", "Request body:")):
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("request_structure", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source="draft",
            notes=["Request structure is present in the draft body."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("request_structure", ""),
        status=ScenarioRequirementStatus.PARTIALLY_SATISFIED,
        source="draft",
        notes=["Request structure is only partially defined."],
    )


def _check_assertions(draft: ScenarioDraft, gap_codes: set[str]) -> DraftRequirementCheck:
    has_expected_section = "Expected:" in draft.markdown or "## Final expectations" in draft.markdown
    if "assertions_not_generated" in gap_codes:
        status = (
            ScenarioRequirementStatus.PARTIALLY_SATISFIED
            if has_expected_section
            else ScenarioRequirementStatus.MISSING
        )
        notes = ["Expected section exists, but concrete assertions still need to be added."]
        if not has_expected_section:
            notes = ["Expected assertions are missing from the draft."]
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("assertions", ""),
            status=status,
            source="draft" if has_expected_section else "unknown",
            notes=notes,
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("assertions", ""),
        status=ScenarioRequirementStatus.SATISFIED if has_expected_section else ScenarioRequirementStatus.MISSING,
        source="draft" if has_expected_section else "unknown",
        notes=["Expected section is present."] if has_expected_section else ["Expected assertions are missing."],
    )


def _check_auth_strategy(gap_codes: set[str]) -> DraftRequirementCheck:
    if "auth_headers_unresolved" in gap_codes:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("auth_strategy", "", required=False),
            status=ScenarioRequirementStatus.PARTIALLY_SATISFIED,
            source="unknown",
            notes=["Auth or header requirements are not yet defined."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("auth_strategy", "", required=False),
        status=ScenarioRequirementStatus.SATISFIED,
        source="unknown",
        notes=["No unresolved auth requirement was detected in current artifacts."],
    )


def _check_db_verification(gap_codes: set[str]) -> DraftRequirementCheck:
    if "db_verification_absent" in gap_codes:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("db_verification", "", required=False),
            status=ScenarioRequirementStatus.PARTIALLY_SATISFIED,
            source="unknown",
            notes=["DB verification is absent and may need manual addition if the case requires persisted-state checks."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("db_verification", "", required=False),
        status=ScenarioRequirementStatus.SATISFIED,
        source="unknown",
        notes=["No unresolved DB verification requirement was detected in current artifacts."],
    )


def _check_captures(gap_codes: set[str]) -> DraftRequirementCheck:
    if "captures_not_generated" in gap_codes:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("captures", "", required=False),
            status=ScenarioRequirementStatus.PARTIALLY_SATISFIED,
            source="unknown",
            notes=["Captures are not generated and should be added only if later steps need them."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("captures", "", required=False),
        status=ScenarioRequirementStatus.SATISFIED,
        source="unknown",
        notes=["No unresolved capture requirement was detected in current artifacts."],
    )


def _diff_line(check: DraftRequirementCheck) -> str:
    status_prefix = {
        ScenarioRequirementStatus.SATISFIED: "OK",
        ScenarioRequirementStatus.MISSING: "MISSING",
        ScenarioRequirementStatus.PARTIALLY_SATISFIED: "PARTIAL",
    }[check.status]
    return f"{status_prefix} {check.requirement.description}"


def _build_edit_targets(
    draft: ScenarioDraft,
    *,
    checklist: DraftChecklistResult,
    gap_summary: DraftGapSummary,
    parse_status: ScenarioDraftParseStatus,
    route_binding: dict[str, object],
) -> DraftEditTargetList:
    targets: list[DraftEditTarget] = []
    if parse_status == ScenarioDraftParseStatus.INVALID:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.FIX_PARSER_ERRORS,
                section_name="Scenario root",
                reason="Draft is not parser-valid.",
                related_requirements=["parser_valid"],
                priority="high",
                suggested_minimum_patch="Fix parser errors so the draft becomes valid scenario markdown before further edits.",
            )
        )

    status_by_requirement = {
        check.requirement.requirement_id: check.status for check in checklist.checks
    }
    gap_codes = set(gap_summary.gap_codes)

    if "compile_unsupported_expectation" in gap_codes:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_EXPECTED_ASSERTION,
                section_name="Final expectations",
                reason="Compile validation found unsupported expectation DSL.",
                related_requirements=["assertions"],
                priority="high",
                suggested_minimum_patch="Replace unsupported expectation text with a runner-supported deterministic assertion.",
            )
        )

    if gap_codes & {
        "compile_capture_rule_invalid",
        "compile_capture_variable_invalid",
        "compile_step_self_capture_dependency",
        "compile_future_capture_dependency",
    }:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_CAPTURE,
                section_name="Steps",
                reason="Compile validation found an invalid or unresolved capture contract.",
                related_requirements=["captures"],
                priority="high",
                suggested_minimum_patch="Fix capture syntax or reorder steps so referenced captured variables exist before use.",
            )
        )

    if "external_inputs_required" in gap_codes:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Variables",
                reason="Compile validation found external variable inputs required before execution.",
                related_requirements=[],
                priority="normal",
                suggested_minimum_patch="Declare the variable source in Variables or ensure the environment provides it before runner execution.",
            )
        )

    if gap_codes & {"missing_environment", "missing_project", "missing_dependency", "workspace_output"}:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Preconditions",
                reason="Preflight validation found workspace or environment readiness issues.",
                related_requirements=[],
                priority="high",
                suggested_minimum_patch="Resolve the referenced environment file, target project path, dependency, or writable output directory before execution.",
            )
        )

    if "external_variable" in gap_codes:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Variables",
                reason="Preflight validation found unresolved external variables.",
                related_requirements=[],
                priority="high",
                suggested_minimum_patch="Provide the required variable through the Variables section or selected environment before execution.",
            )
        )

    if status_by_requirement.get("request_structure") == ScenarioRequirementStatus.MISSING:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_REQUEST_BODY,
                section_name="Steps",
                reason="Request structure is missing for the rendered API step.",
                related_requirements=["request_structure"],
                priority="high",
                suggested_minimum_patch="Add a minimal request body or request shape under the API step so the operator can execute the route intentionally.",
            )
        )

    assertions_status = status_by_requirement.get("assertions")
    if assertions_status in {
        ScenarioRequirementStatus.MISSING,
        ScenarioRequirementStatus.PARTIALLY_SATISFIED,
    }:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_EXPECTED_ASSERTION,
                section_name="Final expectations",
                reason="Expected assertions are missing or only partially defined.",
                related_requirements=["assertions"],
                priority="high",
                suggested_minimum_patch="Add at least one deterministic assertion describing the expected HTTP outcome or observable behavior.",
            )
        )

    if status_by_requirement.get("auth_strategy") == ScenarioRequirementStatus.PARTIALLY_SATISFIED:
        section_name = "Preconditions" if "auth_headers_unresolved" in gap_codes else "Steps"
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_AUTH_HEADERS,
                section_name=section_name,
                reason="Auth or header requirements are unresolved.",
                related_requirements=["auth_strategy"],
                priority="normal",
                suggested_minimum_patch="State the required auth/header strategy in Preconditions or add the required headers directly to the API step.",
            )
        )

    if status_by_requirement.get("db_verification") == ScenarioRequirementStatus.PARTIALLY_SATISFIED:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_DB_VERIFICATION,
                section_name="Notes",
                reason="DB verification is absent and may be needed for persisted-state checks.",
                related_requirements=["db_verification"],
                priority="normal",
                suggested_minimum_patch="Add a note or follow-up verification target that states what persisted state must be checked after execution.",
            )
        )

    if status_by_requirement.get("captures") == ScenarioRequirementStatus.PARTIALLY_SATISFIED:
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.ADD_CAPTURE,
                section_name="Steps",
                reason="Captures are not defined for values that may be needed later.",
                related_requirements=["captures"],
                priority="low",
                suggested_minimum_patch="Add a capture only if later steps or checks need a value from the current API response.",
            )
        )

    if not targets and str(route_binding.get("readiness") or "") == "route_resolved":
        targets.append(
            _edit_target(
                draft_id=draft.draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Notes",
                reason="Route is resolved, but the draft still carries non-route gaps.",
                related_requirements=[],
                priority="low",
                suggested_minimum_patch="Clarify in Notes which remaining environment, auth, or business details must be supplied before execution.",
            )
        )

    return DraftEditTargetList(draft_id=draft.draft_id, targets=targets)


def _build_deferred_edit_targets(draft_id: str, gap_summary: DraftGapSummary) -> DraftEditTargetList:
    targets: list[DraftEditTarget] = []
    gap_codes = set(gap_summary.gap_codes)
    if "ambiguous_route_mapping" in gap_codes or "missing_endpoint_evidence" in gap_codes:
        targets.append(
            _edit_target(
                draft_id=draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Notes",
                reason="Draft cannot be rendered safely because route binding is missing or ambiguous.",
                related_requirements=["endpoint_path", "http_method"],
                priority="high",
                suggested_minimum_patch="Clarify the exact route and method in Notes or upstream plan metadata before trying to render or promote the scenario.",
            )
        )
    if not targets:
        targets.append(
            _edit_target(
                draft_id=draft_id,
                target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
                section_name="Notes",
                reason="Draft preview is unsupported and requires clarification before promotion.",
                related_requirements=[],
                priority="normal",
                suggested_minimum_patch="Document the missing scenario details in Notes before promoting or executing anything.",
            )
        )
    return DraftEditTargetList(draft_id=draft_id, targets=targets)


def _edit_target(
    *,
    draft_id: str,
    target_type: DraftEditTargetType,
    section_name: str,
    reason: str,
    related_requirements: list[str],
    priority: str,
    suggested_minimum_patch: str,
) -> DraftEditTarget:
    target_id = f"{draft_id}:{target_type.value}:{_slugify(section_name)}"
    return DraftEditTarget(
        target_id=target_id,
        draft_id=draft_id,
        section_name=section_name,
        target_type=target_type,
        reason=reason,
        related_requirements=related_requirements,
        priority=priority,
        suggested_minimum_patch=suggested_minimum_patch,
        patch_suggestion=PatchTemplateCatalogService().suggestion_for(target_type),
    )


def _route_binding_from_scenario(scenario: ScenarioDefinition | None) -> dict[str, object]:
    api_step = _first_api_step(scenario)
    if api_step is None or api_step.api is None:
        return {}
    if not api_step.api.method or not api_step.api.path:
        return {}
    return {
        "endpoint_path": api_step.api.path,
        "http_method": api_step.api.method,
        "handler_name": api_step.api.name,
        "route_source": "manual_scenario",
        "confidence": "explicit",
        "readiness": "manual_revalidated",
    }


def _first_api_step(scenario: ScenarioDefinition | None):
    if scenario is None:
        return None
    for step in scenario.steps:
        if step.step_type == ScenarioStepType.API and step.api is not None:
            return step
    return None


def _revalidation_title(scenario: ScenarioDefinition | None, file_path: Path) -> str:
    if scenario is not None and scenario.scenario_name:
        return scenario.scenario_name
    return file_path.stem


def _promotion_metadata(markdown: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if not markdown.lstrip().startswith("<!--"):
        return metadata
    end_index = markdown.find("-->")
    if end_index < 0:
        return metadata
    comment = markdown[:end_index]
    for line in comment.splitlines():
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key in {"generated_by", "generation_run_id", "draft_id", "source"}:
            metadata[key] = value
    if metadata.get("generated_by") != "codex-qa-agent":
        return {}
    return metadata


def _resolve_target_dir(workspace_root: Path, target_dir: Path) -> Path:
    target = target_dir if target_dir.is_absolute() else workspace_root / target_dir
    scenarios_root = (workspace_root / "scenarios").resolve()
    resolved = target.resolve()
    if resolved != scenarios_root and scenarios_root not in resolved.parents:
        raise ValueError("Promotion target directory must be under scenarios/.")
    return target


def _promotion_header(run_id: str, draft_id: str) -> str:
    return (
        "<!--\n"
        "generated_by: codex-qa-agent\n"
        f"generation_run_id: {run_id}\n"
        f"draft_id: {draft_id}\n"
        "source: draft-rendering-preview\n"
        "-->\n\n"
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug.lower() or "scenario"
