"""Domain contracts for generation pipeline inputs, plans, and traceability."""

from .contracts import GenerationArtifactStore
from .models import (
    AgentPlannedTestCaseInput,
    AgentTestPlanInput,
    DiagnosticSeverity,
    GenerationDiagnostic,
    GenerationRunContext,
    GenerationSourceInput,
    NormalizedProseSource,
    NormalizedTestPlan,
    PlannedCaseSupport,
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
    "GenerationArtifactStore",
    "GenerationDiagnostic",
    "GenerationRunContext",
    "GenerationSourceInput",
    "NormalizedProseSource",
    "NormalizedTestPlan",
    "PlannedCaseSupport",
    "PlannedRouteIntent",
    "PlannedTestCase",
    "ProseTestCaseDraft",
    "RouteSupportHint",
    "SourceInputFormat",
    "TraceabilityLink",
    "TraceabilityMap",
]
