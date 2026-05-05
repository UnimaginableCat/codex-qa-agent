"""Scenario compile and preflight validation services."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tools.common.statuses import StepStatus
from tools.scenario_runner.domain.models import ScenarioDefinition
from tools.scenario_runner.orchestration.compiler import CompiledScenario, ScenarioCompiler
from tools.scenario_runner.orchestration.preflight import ScenarioPreflightChecker

from ..validation import (
    _compile_issue_from_execution_issue,
    _compile_issues_from_step_parse_warnings,
    _compile_readiness,
    _compile_summary,
    _compile_warning_from_external_input,
    _preflight_issue_from_check,
    _preflight_readiness,
    _preflight_summary,
)
from ..models import (
    CompileIssue,
    CompileIssueType,
    DraftChecklistResult,
    ExecutionEnvironmentReadinessCategory,
    ExecutionReadinessCategory,
    PreflightIssue,
    PreflightIssueType,
    ScenarioCompileStatus,
    ScenarioCompileValidationResult,
    ScenarioDraftParseStatus,
    ScenarioPreflightStatus,
    ScenarioPreflightValidationResult,
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
        issues.extend(_compile_issues_from_step_parse_warnings(scenario, start_index=len(issues)))
        warnings = [
            _compile_warning_from_external_input(requirement, index)
            for index, requirement in enumerate(compile_result.required_external_inputs)
        ]
        compile_status = (
            ScenarioCompileStatus.SUCCESS
            if compile_result.passed and not issues
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
