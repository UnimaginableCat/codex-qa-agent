"""Reusable scenario runner skeleton for QA orchestration.

Keep this package initializer lightweight: ``python -m tools.scenario_runner.cli``
imports it before the CLI module can enforce the workspace-venv guard.
"""

from __future__ import annotations


_EXPORTS: dict[str, tuple[str, str]] = {
    "ApiStepDefinition": (".domain", "ApiStepDefinition"),
    "AbortDisposition": (".domain", "AbortDisposition"),
    "AvailableOperatorAction": (".domain", "AvailableOperatorAction"),
    "CompletionDisposition": (".domain", "CompletionDisposition"),
    "ContinuationPolicy": (".domain", "ContinuationPolicy"),
    "DbStepDefinition": (".domain", "DbStepDefinition"),
    "DecisionResolution": (".domain", "DecisionResolution"),
    "DecisionPoint": (".domain", "DecisionPoint"),
    "ExpectationCheckResult": (".domain", "ExpectationCheckResult"),
    "RunContext": (".domain", "RunContext"),
    "ScenarioDefinition": (".domain", "ScenarioDefinition"),
    "ScenarioExecutionSummary": (".domain", "ScenarioExecutionSummary"),
    "ScenarioStep": (".domain", "ScenarioStep"),
    "StepExecutionLifecycleState": (".domain", "StepExecutionLifecycleState"),
    "StepExecutionState": (".domain", "StepExecutionState"),
    "StepExecutionResult": (".domain", "StepExecutionResult"),
    "ExecutionEvent": (".domain", "ExecutionEvent"),
    "ExecutionIssue": (".domain", "ExecutionIssue"),
    "ExecutionOutcome": (".domain", "ExecutionOutcome"),
    "ExecutionPhase": (".domain", "ExecutionPhase"),
    "GuidedAction": (".domain", "GuidedAction"),
    "GuidedActionType": (".domain", "GuidedActionType"),
    "GuidedDiagnostic": (".domain", "GuidedDiagnostic"),
    "GuidedDiagnosticTag": (".domain", "GuidedDiagnosticTag"),
    "OperatorActionSelection": (".domain", "OperatorActionSelection"),
    "OperatorActionType": (".domain", "OperatorActionType"),
    "PauseState": (".domain", "PauseState"),
    "ResumeRequest": (".domain", "ResumeRequest"),
    "ResumeToken": (".domain", "ResumeToken"),
    "ResumeStrategy": (".domain", "ResumeStrategy"),
    "RunMode": (".domain", "RunMode"),
    "RunTermination": (".domain", "RunTermination"),
    "RunTerminationKind": (".domain", "RunTerminationKind"),
    "ScenarioRunLifecycleState": (".domain", "ScenarioRunLifecycleState"),
    "ScenarioRunState": (".domain", "ScenarioRunState"),
    "RunContinuationState": (".domain", "RunContinuationState"),
    "SkipDisposition": (".domain", "SkipDisposition"),
    "StepTermination": (".domain", "StepTermination"),
    "StepTerminationKind": (".domain", "StepTerminationKind"),
    "TerminationReason": (".domain", "TerminationReason"),
    "TerminationReasonSource": (".domain", "TerminationReasonSource"),
    "CompileCheckResult": (".orchestration", "CompileCheckResult"),
    "CompileResult": (".orchestration", "CompileResult"),
    "CompiledScenario": (".orchestration", "CompiledScenario"),
    "ExternalVariableRequirement": (".orchestration", "ExternalVariableRequirement"),
    "PreflightCheckResult": (".orchestration", "PreflightCheckResult"),
    "PreflightResult": (".orchestration", "PreflightResult"),
    "ScenarioCompiler": (".orchestration", "ScenarioCompiler"),
    "ScenarioExecutionEngine": (".orchestration", "ScenarioExecutionEngine"),
    "ScenarioExecutionSession": (".orchestration", "ScenarioExecutionSession"),
    "ScenarioPreflightChecker": (".orchestration", "ScenarioPreflightChecker"),
    "ScenarioRunnerService": (".orchestration", "ScenarioRunnerService"),
    "resolve_operator_action_selection": (".orchestration", "resolve_operator_action_selection"),
    "PlaceholderInterpolator": (".runtime", "PlaceholderInterpolator"),
    "REDACTED": (".runtime", "REDACTED"),
    "ScenarioStepValidator": (".runtime", "ScenarioStepValidator"),
    "SensitiveDataRedactor": (".runtime", "SensitiveDataRedactor"),
    "StepExecutorFactory": (".runtime", "StepExecutorFactory"),
    "redact_sensitive_data": (".runtime", "redact_sensitive_data"),
    "MarkdownScenarioParser": (".parser", "MarkdownScenarioParser"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = _EXPORTS[name]
    from importlib import import_module

    module = import_module(module_name, package=__name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
