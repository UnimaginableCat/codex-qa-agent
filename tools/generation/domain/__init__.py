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
    PlannedTestCase,
    ProseTestCaseDraft,
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
    "PlannedTestCase",
    "ProseTestCaseDraft",
    "SourceInputFormat",
    "TraceabilityLink",
    "TraceabilityMap",
]
