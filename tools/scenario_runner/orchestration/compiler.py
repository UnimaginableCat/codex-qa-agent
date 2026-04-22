"""Compile-time scenario contract checks before environment preflight and runtime execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus

from ..domain.execution import (
    ExecutionIssue,
    ExecutionIssueKind,
    ExecutionPhase,
    StepReference,
)
from ..domain.models import (
    ScenarioDefinition,
    ScenarioStep,
    ScenarioStepType,
    ScenarioVariableDefinition,
    ScenarioVariableSource,
)
from ..projections.summary import resolve_final_status
from ..runtime.validators import ScenarioStepValidator
from ..runtime.variables import _collect_placeholder_names, is_known_runtime_variable_name

_VARIABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class CompileCheckResult:
    name: str
    status: StepStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return to_json_safe(payload)


@dataclass(frozen=True, slots=True)
class ExternalVariableRequirement:
    variable_name: str
    step: StepReference | None = None
    usage_kind: str = "step_payload"
    source_name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "variable_name": self.variable_name,
                "step": None if self.step is None else self.step.to_dict(),
                "usage_kind": self.usage_kind,
                "source_name": self.source_name,
                "details": self.details,
            }
        )


@dataclass(frozen=True, slots=True)
class CompileResult:
    checks: list[CompileCheckResult]
    issues: list[ExecutionIssue] = field(default_factory=list)
    required_external_inputs: list[ExternalVariableRequirement] = field(default_factory=list)

    @property
    def status(self) -> StepStatus:
        return resolve_final_status([check.status for check in self.checks])

    @property
    def passed(self) -> bool:
        return self.status == StepStatus.PASS

    def failed_checks(self) -> list[CompileCheckResult]:
        return [check for check in self.checks if check.status != StepStatus.PASS]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checks": [check.to_dict() for check in self.checks],
            "issues": [issue.to_dict() for issue in self.issues],
            "required_external_inputs": [item.to_dict() for item in self.required_external_inputs],
        }


@dataclass(frozen=True, slots=True)
class CompiledScenario:
    scenario_definition: ScenarioDefinition
    compile_result: CompileResult


@dataclass(slots=True)
class _CompileAnalysis:
    variable_issues: list[ExecutionIssue] = field(default_factory=list)
    capture_issues: list[ExecutionIssue] = field(default_factory=list)
    reference_issues: list[ExecutionIssue] = field(default_factory=list)
    expectation_issues: list[ExecutionIssue] = field(default_factory=list)
    required_external_inputs: list[ExternalVariableRequirement] = field(default_factory=list)


class ScenarioCompiler:
    """Build a stricter execution contract before environment preflight and step runtime."""

    def __init__(self, step_validator: ScenarioStepValidator | None = None) -> None:
        self._step_validator = step_validator or ScenarioStepValidator()

    def compile(self, scenario_definition: ScenarioDefinition) -> CompiledScenario:
        variable_metadata_issues = self._variable_metadata_issues(scenario_definition)
        analysis = self._analyze_step_contracts(scenario_definition)
        checks = [
            self._build_check(
                name="variables_section_valid",
                issues=variable_metadata_issues,
                success_message="Scenario variable definitions are machine-readable.",
                failure_message="Variables section contains invalid definition(s); scenario execution is blocked before runtime.",
            ),
            self._build_check(
                name="variable_dependencies_resolvable",
                issues=analysis.variable_issues,
                success_message="Required variable dependencies are structurally resolvable before the consuming step runs.",
                failure_message="Scenario contains variable dependencies that cannot be satisfied before runtime.",
            ),
            self._build_check(
                name="capture_contract_valid",
                issues=analysis.capture_issues,
                success_message="Capture rules have a valid structural contract.",
                failure_message="Scenario contains malformed or inconsistent capture rules.",
            ),
            self._build_check(
                name="step_references_resolvable",
                issues=analysis.reference_issues,
                success_message="Step payload and expectation references are structurally resolvable.",
                failure_message="Scenario contains step references that cannot be satisfied before execution.",
            ),
            self._build_check(
                name="expectations_supported",
                issues=analysis.expectation_issues,
                success_message="Expectation rules use supported syntax.",
                failure_message="Scenario contains unsupported expectation rules.",
            ),
        ]
        compile_result = CompileResult(
            checks=checks,
            issues=(
                variable_metadata_issues
                + analysis.variable_issues
                + analysis.capture_issues
                + analysis.reference_issues
                + analysis.expectation_issues
            ),
            required_external_inputs=self._dedupe_external_inputs(analysis.required_external_inputs),
        )
        return CompiledScenario(
            scenario_definition=scenario_definition,
            compile_result=compile_result,
        )

    def _variable_metadata_issues(self, scenario_definition: ScenarioDefinition) -> list[ExecutionIssue]:
        errors = [
            str(item)
            for item in scenario_definition.metadata.get("variables_validation_errors", [])
            if str(item).strip()
        ]
        if not errors:
            return []
        return [
            ExecutionIssue(
                code="compile_variables_section_invalid",
                message=(
                    "Variables section contains invalid definition(s); scenario execution is blocked before "
                    f"runtime. {'; '.join(errors)}"
                ),
                phase=ExecutionPhase.COMPILATION,
                issue_type=ExecutionIssueKind.VALIDATION,
                outcome=StepStatus.BLOCKED,
                details={"errors": errors},
            )
        ]

    def _analyze_step_contracts(self, scenario_definition: ScenarioDefinition) -> _CompileAnalysis:
        analysis = _CompileAnalysis()
        variable_definitions = {definition.name: definition for definition in scenario_definition.variables}
        variable_dependencies = self._variable_dependencies(scenario_definition.variables)
        capture_names_by_step: list[set[str]] = []
        capture_producers: dict[str, list[tuple[int, StepReference]]] = {}

        for step_index, step in enumerate(scenario_definition.steps):
            step_reference = StepReference.from_step(step)
            self._validate_step_definition(step_reference, step, analysis)
            capture_names = self._validate_capture_rules(step_reference, step, analysis)
            capture_names_by_step.append(capture_names)
            for capture_name in capture_names:
                capture_producers.setdefault(capture_name, []).append((step_index, step_reference))

        produced_before_step: set[str] = set()
        for step_index, step in enumerate(scenario_definition.steps):
            step_reference = StepReference.from_step(step)
            current_capture_names = capture_names_by_step[step_index]

            for requirement_name, usage_kind, source_name in self._iter_step_requirements(step):
                allow_current_step_capture = usage_kind == "expectation"
                external_inputs, resolution_issues = self._classify_requirement(
                    requirement_name,
                    variable_definitions=variable_definitions,
                    variable_dependencies=variable_dependencies,
                    produced_before_step=produced_before_step,
                    current_capture_names=current_capture_names,
                    capture_producers=capture_producers,
                    current_step_index=step_index,
                    step=step_reference,
                    usage_kind=usage_kind,
                    source_name=source_name,
                    allow_current_step_capture=allow_current_step_capture,
                    visiting=set(),
                )
                for issue in resolution_issues:
                    if issue.code.startswith("compile_variable_"):
                        analysis.variable_issues.append(issue)
                    else:
                        analysis.reference_issues.append(issue)
                for external_name in sorted(external_inputs):
                    analysis.required_external_inputs.append(
                        ExternalVariableRequirement(
                            variable_name=external_name,
                            step=step_reference,
                            usage_kind=usage_kind,
                            source_name=source_name,
                            details={"requested_variable": requirement_name},
                        )
                    )

            for diagnostic in self._step_validator.inspect_contract(step):
                if diagnostic.supported:
                    continue
                analysis.expectation_issues.append(
                    ExecutionIssue(
                        code="compile_unsupported_expectation",
                        message=diagnostic.detail,
                        phase=ExecutionPhase.COMPILATION,
                        issue_type=ExecutionIssueKind.VALIDATION,
                        outcome=StepStatus.BLOCKED,
                        step=step_reference,
                        details={"rule": diagnostic.rule, "step_type": diagnostic.step_type.value},
                    )
                )

            produced_before_step.update(current_capture_names)

        return analysis

    @staticmethod
    def _variable_dependencies(
        definitions: list[ScenarioVariableDefinition],
    ) -> dict[str, set[str]]:
        dependencies: dict[str, set[str]] = {}
        for definition in definitions:
            if definition.source == ScenarioVariableSource.TEMPLATE:
                dependencies[definition.name] = _collect_placeholder_names(definition.raw_value)
            elif definition.source == ScenarioVariableSource.DERIVED:
                dependencies[definition.name] = (
                    {definition.source_name} if definition.source_name else set()
                )
        return dependencies

    def _validate_capture_rules(
        self,
        step_reference: StepReference,
        step: ScenarioStep,
        analysis: _CompileAnalysis,
    ) -> set[str]:
        capture_names: set[str] = set()
        for capture_rule in self._capture_rules(step):
            source_expression, variable_name = self._parse_capture_rule(capture_rule)
            if source_expression is None or variable_name is None:
                analysis.capture_issues.append(
                    ExecutionIssue(
                        code="compile_capture_rule_invalid",
                        message=(
                            f"Invalid capture rule '{capture_rule}'. Expected format "
                            "'<source> -> <variable_name>'."
                        ),
                        phase=ExecutionPhase.COMPILATION,
                        issue_type=ExecutionIssueKind.VALIDATION,
                        outcome=StepStatus.BLOCKED,
                        step=step_reference,
                        details={"rule": capture_rule},
                    )
                )
                continue
            if not _VARIABLE_NAME_RE.fullmatch(variable_name):
                analysis.capture_issues.append(
                    ExecutionIssue(
                        code="compile_capture_variable_invalid",
                        message=(
                            f"Capture rule '{capture_rule}' uses invalid variable name '{variable_name}'."
                        ),
                        phase=ExecutionPhase.COMPILATION,
                        issue_type=ExecutionIssueKind.VALIDATION,
                        outcome=StepStatus.BLOCKED,
                        step=step_reference,
                        details={"rule": capture_rule, "variable_name": variable_name},
                    )
                )
                continue
            capture_names.add(variable_name)
        return capture_names

    @staticmethod
    def _capture_rules(step: ScenarioStep) -> list[str]:
        if step.step_type == ScenarioStepType.API:
            return [] if step.api is None else list(step.api.capture)
        return [] if step.db is None else list(step.db.capture)

    @staticmethod
    def _validate_step_definition(
        step_reference: StepReference,
        step: ScenarioStep,
        analysis: _CompileAnalysis,
    ) -> None:
        if step.step_type == ScenarioStepType.API and step.api is None:
            analysis.reference_issues.append(
                ExecutionIssue(
                    code="compile_api_step_definition_missing",
                    message=f"Step '{step.step_id}' is declared as API but has no API definition.",
                    phase=ExecutionPhase.COMPILATION,
                    issue_type=ExecutionIssueKind.VALIDATION,
                    outcome=StepStatus.BLOCKED,
                    step=step_reference,
                )
            )
        if step.step_type == ScenarioStepType.DB and step.db is None:
            analysis.reference_issues.append(
                ExecutionIssue(
                    code="compile_db_step_definition_missing",
                    message=f"Step '{step.step_id}' is declared as DB but has no DB definition.",
                    phase=ExecutionPhase.COMPILATION,
                    issue_type=ExecutionIssueKind.VALIDATION,
                    outcome=StepStatus.BLOCKED,
                    step=step_reference,
                )
            )

    @staticmethod
    def _parse_capture_rule(capture_rule: str) -> tuple[str | None, str | None]:
        if "->" not in capture_rule:
            return None, None
        source_expression, variable_name = (part.strip() for part in capture_rule.split("->", 1))
        if not source_expression or not variable_name:
            return None, None
        return source_expression, variable_name

    @staticmethod
    def _iter_step_requirements(step: ScenarioStep) -> list[tuple[str, str, str]]:
        requirements: list[tuple[str, str, str]] = []
        if step.api is not None:
            for field_name, value in (
                ("api.method", step.api.method),
                ("api.path", step.api.path),
                ("api.headers", step.api.headers),
                ("api.params", step.api.params),
                ("api.body", step.api.body),
                ("api.retry", step.api.retry),
            ):
                for requirement_name in sorted(_collect_placeholder_names(value)):
                    requirements.append((requirement_name, "step_payload", field_name))
            for rule in step.api.expected:
                for requirement_name in sorted(_collect_placeholder_names(rule)):
                    requirements.append((requirement_name, "expectation", rule))
        if step.db is not None:
            for field_name, value in (
                ("db.sql", step.db.sql),
                ("db.params", step.db.params),
            ):
                for requirement_name in sorted(_collect_placeholder_names(value)):
                    requirements.append((requirement_name, "step_payload", field_name))
            for rule in step.db.expected:
                for requirement_name in sorted(_collect_placeholder_names(rule)):
                    requirements.append((requirement_name, "expectation", rule))
        return requirements

    def _classify_requirement(
        self,
        requirement_name: str,
        *,
        variable_definitions: dict[str, ScenarioVariableDefinition],
        variable_dependencies: dict[str, set[str]],
        produced_before_step: set[str],
        current_capture_names: set[str],
        capture_producers: dict[str, list[tuple[int, StepReference]]],
        current_step_index: int,
        step: StepReference,
        usage_kind: str,
        source_name: str,
        allow_current_step_capture: bool,
        visiting: set[str],
    ) -> tuple[set[str], list[ExecutionIssue]]:
        if requirement_name in produced_before_step:
            return set(), []
        if allow_current_step_capture and requirement_name in current_capture_names:
            return set(), []

        definition = variable_definitions.get(requirement_name)
        if definition is None and is_known_runtime_variable_name(requirement_name):
            return set(), []
        if definition is None:
            structural_issue = self._missing_requirement_issue(
                requirement_name=requirement_name,
                current_capture_names=current_capture_names,
                capture_producers=capture_producers,
                current_step_index=current_step_index,
                step=step,
                usage_kind=usage_kind,
                source_name=source_name,
                allow_current_step_capture=allow_current_step_capture,
            )
            if structural_issue is not None:
                return set(), [structural_issue]
            return {requirement_name}, []

        if definition.source == ScenarioVariableSource.ENV:
            return {definition.name}, []
        if definition.source in {
            ScenarioVariableSource.LITERAL,
            ScenarioVariableSource.GENERATED,
            ScenarioVariableSource.RUNTIME,
        }:
            return set(), []

        if requirement_name in visiting:
            return set(), [
                ExecutionIssue(
                    code="compile_variable_dependency_cycle",
                    message=(
                        f"Variable '{requirement_name}' participates in a cyclic dependency and cannot be "
                        "resolved before runtime."
                    ),
                    phase=ExecutionPhase.COMPILATION,
                    issue_type=ExecutionIssueKind.VALIDATION,
                    outcome=StepStatus.BLOCKED,
                    step=step,
                    details={
                        "variable_name": requirement_name,
                        "usage_kind": usage_kind,
                        "source_name": source_name,
                    },
                )
            ]

        external_inputs: set[str] = set()
        issues: list[ExecutionIssue] = []
        next_visiting = set(visiting)
        next_visiting.add(requirement_name)
        for dependency_name in sorted(variable_dependencies.get(requirement_name, set())):
            nested_external_inputs, nested_issues = self._classify_requirement(
                dependency_name,
                variable_definitions=variable_definitions,
                variable_dependencies=variable_dependencies,
                produced_before_step=produced_before_step,
                current_capture_names=current_capture_names,
                capture_producers=capture_producers,
                current_step_index=current_step_index,
                step=step,
                usage_kind=usage_kind,
                source_name=source_name,
                allow_current_step_capture=allow_current_step_capture,
                visiting=next_visiting,
            )
            external_inputs.update(nested_external_inputs)
            issues.extend(nested_issues)
        return external_inputs, issues

    @staticmethod
    def _missing_requirement_issue(
        *,
        requirement_name: str,
        current_capture_names: set[str],
        capture_producers: dict[str, list[tuple[int, StepReference]]],
        current_step_index: int,
        step: StepReference,
        usage_kind: str,
        source_name: str,
        allow_current_step_capture: bool,
    ) -> ExecutionIssue | None:
        if requirement_name in current_capture_names and not allow_current_step_capture:
            return ExecutionIssue(
                code="compile_step_self_capture_dependency",
                message=(
                    f"Step '{step.step_id}' uses variable '{requirement_name}' before that same step captures it."
                ),
                phase=ExecutionPhase.COMPILATION,
                issue_type=ExecutionIssueKind.VALIDATION,
                outcome=StepStatus.BLOCKED,
                step=step,
                details={
                    "variable_name": requirement_name,
                    "usage_kind": usage_kind,
                    "source_name": source_name,
                },
            )

        for producer_index, producer_step in capture_producers.get(requirement_name, []):
            if producer_index > current_step_index:
                return ExecutionIssue(
                    code="compile_future_capture_dependency",
                    message=(
                        f"Step '{step.step_id}' depends on variable '{requirement_name}', but it is only "
                        f"captured later by step '{producer_step.step_id}'."
                    ),
                    phase=ExecutionPhase.COMPILATION,
                    issue_type=ExecutionIssueKind.VALIDATION,
                    outcome=StepStatus.BLOCKED,
                    step=step,
                    details={
                        "variable_name": requirement_name,
                        "producer_step_id": producer_step.step_id,
                        "usage_kind": usage_kind,
                        "source_name": source_name,
                    },
                )
        return None

    @staticmethod
    def _build_check(
        *,
        name: str,
        issues: list[ExecutionIssue],
        success_message: str,
        failure_message: str,
    ) -> CompileCheckResult:
        if not issues:
            return CompileCheckResult(name=name, status=StepStatus.PASS, message=success_message)
        return CompileCheckResult(
            name=name,
            status=resolve_final_status([issue.outcome or StepStatus.BLOCKED for issue in issues]),
            message=failure_message,
            details={"issues": [issue.to_dict() for issue in issues]},
        )

    @staticmethod
    def _dedupe_external_inputs(
        requirements: list[ExternalVariableRequirement],
    ) -> list[ExternalVariableRequirement]:
        deduped: list[ExternalVariableRequirement] = []
        seen: set[tuple[str, str | None, str, str | None]] = set()
        for requirement in requirements:
            key = (
                requirement.variable_name,
                requirement.step.step_id if requirement.step is not None else None,
                requirement.usage_kind,
                requirement.source_name,
            )
            if key in seen:
                continue
            deduped.append(requirement)
            seen.add(key)
        return deduped
