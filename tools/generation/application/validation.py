"""Status and message projection for generation application results."""

from __future__ import annotations

from tools.common.statuses import StepStatus
from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic

BLOCKING_DIAGNOSTIC_CODES = {
    "source_content_empty",
    "source_path_missing",
    "source_path_unreadable",
    "unsupported_source_format",
    "unsupported_output_mode",
    "unsupported_input_mode",
    "agent_plan_missing",
    "agent_plan_missing_source_id",
    "agent_plan_missing_project",
    "agent_plan_missing_title",
    "agent_plan_no_cases",
    "agent_plan_case_missing_title",
    "agent_plan_case_missing_objective",
    "enrichment_unsupported_current_phase",
    "no_test_cases_detected",
}


def derive_generation_status(
    diagnostics: list[GenerationDiagnostic],
    *,
    allow_empty_plan: bool = False,
) -> StepStatus:
    blocking_codes = BLOCKING_DIAGNOSTIC_CODES
    if allow_empty_plan:
        blocking_codes = blocking_codes - {"no_test_cases_detected"}
    if any(diagnostic.code in blocking_codes for diagnostic in diagnostics):
        return StepStatus.BLOCKED
    if any(diagnostic.severity == DiagnosticSeverity.ERROR for diagnostic in diagnostics):
        return StepStatus.ERROR
    return StepStatus.PASS


def build_generation_message(status: StepStatus, diagnostics: list[GenerationDiagnostic]) -> str:
    warning_count = sum(
        1 for diagnostic in diagnostics if diagnostic.severity == DiagnosticSeverity.WARNING
    )
    if status == StepStatus.BLOCKED:
        return "Test-plan generation was blocked by source input or generation policy issues."
    if status == StepStatus.ERROR:
        return "Test-plan generation failed with errors."
    if warning_count:
        return f"Test-plan generation completed with {warning_count} warning(s)."
    return "Test-plan generation completed."

