"""Preflight-readiness review logic."""

from __future__ import annotations

from tools.generation.review.models import (
    DraftGapSummary,
    ExecutionEnvironmentReadinessCategory,
    PreflightIssue,
    PreflightIssueType,
    ScenarioPreflightStatus,
    ScenarioPreflightValidationResult,
)

from ..common import _dedupe_preserve_order


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
