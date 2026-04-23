"""Domain contracts for generation pipeline inputs, plans, and traceability."""

from .contracts import GenerationArtifactStore
from .gaps import format_case_gap_note, gap_code_for_category, project_case_gap
from .models import (
    AgentPlannedTestCaseInput,
    AgentTestPlanInput,
    DiagnosticSeverity,
    GapCategory,
    GenerationDiagnostic,
    GenerationRunContext,
    GenerationSourceInput,
    NormalizedProseSource,
    NormalizedTestPlan,
    PlannedCaseSupport,
    PlannedCaseGap,
    PlannedRouteIntent,
    PlannedTestCase,
    ProseTestCaseDraft,
    RouteSupportHint,
    SourceInputFormat,
    TraceabilityLink,
    TraceabilityMap,
)

__all__ = [
    "AgentPlannedTestCaseInput",
    "AgentTestPlanInput",
    "DiagnosticSeverity",
    "format_case_gap_note",
    "GapCategory",
    "gap_code_for_category",
    "GenerationArtifactStore",
    "GenerationDiagnostic",
    "GenerationRunContext",
    "GenerationSourceInput",
    "NormalizedProseSource",
    "NormalizedTestPlan",
    "PlannedCaseSupport",
    "PlannedCaseGap",
    "PlannedRouteIntent",
    "PlannedTestCase",
    "ProseTestCaseDraft",
    "project_case_gap",
    "RouteSupportHint",
    "SourceInputFormat",
    "TraceabilityLink",
    "TraceabilityMap",
]
