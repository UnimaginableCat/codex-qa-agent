"""Compile-readiness review logic."""

from __future__ import annotations

from tools.generation.review.models import (
    CompileIssue,
    CompileIssueType,
    DraftChecklistResult,
    DraftGapSummary,
    ExecutionReadinessCategory,
    ScenarioCompileStatus,
    ScenarioCompileValidationResult,
    ScenarioDraftParseStatus,
    ScenarioRequirementStatus,
)
from tools.scenario_runner.domain.models import ScenarioDefinition

from ..common import _dedupe_preserve_order


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

def _compile_issues_from_step_parse_warnings(
    scenario: ScenarioDefinition,
    *,
    start_index: int,
) -> list[CompileIssue]:
    issues: list[CompileIssue] = []
    for step in scenario.steps:
        parse_warnings = step.metadata.get("parse_warnings", [])
        if not isinstance(parse_warnings, list):
            continue
        for warning in parse_warnings:
            message = str(warning)
            if "field" not in message or "unknown and was ignored" not in message:
                continue
            issues.append(
                CompileIssue(
                    issue_id=f"parse-warning:{start_index + len(issues)}",
                    issue_type=CompileIssueType.PARSE_ERROR,
                    message=(
                        "Scenario step contains an unsupported field that the parser ignored. "
                        "Remove the field or add official parser/compiler/runtime support before execution."
                    ),
                    severity="error",
                    source="parser",
                    details={"code": "unsupported_step_field_ignored", "step_id": step.step_id, "warning": message},
                )
            )
    return issues

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
        if warnings:
            return (
                "Compile-only validation passed, but external inputs are still required before execution. "
                "Environment-backed variables are not resolved in compile mode; run preflight to verify runtime readiness."
            )
        return "Compile-only validation passed with remaining checklist gaps before runner execution."
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
