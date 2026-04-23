"""Shared helpers for projecting typed planned-case gaps into operator-facing output."""

from __future__ import annotations

from tools.generation.domain.models import GapCategory, PlannedCaseGap


def gap_code_for_category(category: GapCategory) -> str:
    mapping = {
        GapCategory.ENDPOINT_DETAIL: "endpoint_detail_unresolved",
        GapCategory.EXECUTABLE_DETAIL: "executable_detail_unresolved",
        GapCategory.AUTH_STRATEGY: "auth_strategy_unresolved",
        GapCategory.ENVIRONMENT: "environment_unresolved",
        GapCategory.ASSERTION_DETAIL: "assertion_detail_unresolved",
        GapCategory.DATA_SETUP: "data_setup_unresolved",
    }
    return mapping.get(category, "")


def project_case_gap(gap: PlannedCaseGap) -> tuple[str, str]:
    return gap_code_for_category(gap.category), gap.message


def format_case_gap_note(gap: PlannedCaseGap) -> str:
    category = gap.category.value or GapCategory.UNKNOWN.value
    if gap.message:
        return f"Typed gap [{category}]: {gap.message}"
    return f"Typed gap [{category}]."
