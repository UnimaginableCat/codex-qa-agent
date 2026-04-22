"""Preflight readiness checks for scenario execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import importlib.util
from pathlib import Path
from typing import Any

from tools.common.statuses import StepStatus

from .artifacts import ARTIFACTS_DIRNAME, PARSED_PLANS_DIRNAME, RUNS_DIRNAME
from .models import ScenarioDefinition, ScenarioStepType
from .summary import resolve_final_status


@dataclass(frozen=True, slots=True)
class PreflightCheckResult:
    name: str
    status: StepStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True, slots=True)
class PreflightResult:
    checks: list[PreflightCheckResult]

    @property
    def status(self) -> StepStatus:
        return resolve_final_status([check.status for check in self.checks])

    @property
    def passed(self) -> bool:
        return self.status == StepStatus.PASS

    def failed_checks(self) -> list[PreflightCheckResult]:
        return [check for check in self.checks if check.status != StepStatus.PASS]

    def issue_messages(self) -> list[str]:
        messages: list[str] = []
        for check in self.failed_checks():
            message = f"Preflight {check.status.value}: {check.name}: {check.message}"
            errors = check.details.get("errors")
            if isinstance(errors, list) and errors:
                message = f"{message} {'; '.join(str(error) for error in errors)}"
            messages.append(message)
        return messages

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checks": [check.to_dict() for check in self.checks],
        }


class ScenarioPreflightChecker:
    """Runs deterministic checks before scenario steps are executed."""

    def run(self, scenario_definition: ScenarioDefinition, workspace_root: Path) -> PreflightResult:
        checks: list[PreflightCheckResult] = []
        checks.extend(self._check_scenario_shape(scenario_definition, workspace_root))
        checks.extend(self._check_environment_and_project(scenario_definition, workspace_root))
        checks.extend(self._check_required_dependencies(scenario_definition))
        checks.extend(self._check_tool_entrypoints(scenario_definition, workspace_root))
        checks.extend(self._check_output_directories(workspace_root))
        return PreflightResult(checks=checks)

    def _check_scenario_shape(
        self,
        scenario_definition: ScenarioDefinition,
        workspace_root: Path,
    ) -> list[PreflightCheckResult]:
        checks = [
            self._check_path_exists(
                name="scenario_file_exists",
                path=self._resolve_path(workspace_root, scenario_definition.scenario_path),
                failure_status=StepStatus.ERROR,
                missing_message="Scenario file does not exist.",
            ),
            self._check_required_text(
                name="scenario_name_present",
                value=scenario_definition.scenario_name,
                message="Scenario name is missing.",
            ),
            self._check_required_text(
                name="project_path_present",
                value=scenario_definition.project,
                message="Project path is missing.",
            ),
            self._check_required_text(
                name="environment_path_present",
                value=scenario_definition.environment,
                message="Environment path is missing.",
            ),
        ]
        checks.extend(self._check_variable_definitions(scenario_definition))

        if scenario_definition.steps:
            checks.append(self._pass("steps_present", f"Scenario contains {len(scenario_definition.steps)} step(s)."))
        else:
            checks.append(
                PreflightCheckResult(
                    name="steps_present",
                    status=StepStatus.BLOCKED,
                    message="Scenario must contain at least one step.",
                )
            )

        duplicate_step_numbers = self._find_duplicates([step.step_number for step in scenario_definition.steps])
        if duplicate_step_numbers:
            checks.append(
                PreflightCheckResult(
                    name="step_numbers_unique",
                    status=StepStatus.BLOCKED,
                    message=f"Duplicate step numbers: {', '.join(str(item) for item in duplicate_step_numbers)}.",
                )
            )
        else:
            checks.append(self._pass("step_numbers_unique", "Step numbers are unique."))

        return checks

    def _check_variable_definitions(self, scenario_definition: ScenarioDefinition) -> list[PreflightCheckResult]:
        errors = [
            str(item)
            for item in scenario_definition.metadata.get("variables_validation_errors", [])
            if str(item).strip()
        ]
        if not errors:
            return [
                self._pass(
                    "variables_section_valid",
                    "Scenario variable definitions are machine-readable.",
                )
            ]
        return [
            PreflightCheckResult(
                name="variables_section_valid",
                status=StepStatus.BLOCKED,
                message=(
                    "Variables section contains invalid definition(s); scenario execution was blocked "
                    "before API/DB runtime."
                ),
                details={"errors": errors},
            )
        ]

    def _check_environment_and_project(
        self,
        scenario_definition: ScenarioDefinition,
        workspace_root: Path,
    ) -> list[PreflightCheckResult]:
        checks: list[PreflightCheckResult] = []
        if scenario_definition.environment.strip():
            checks.append(
                self._check_path_exists(
                    name="environment_file_exists",
                    path=self._resolve_path(workspace_root, scenario_definition.environment),
                    failure_status=StepStatus.BLOCKED,
                    missing_message="Environment file does not exist.",
                )
            )
        if scenario_definition.project.strip():
            checks.append(
                self._check_path_exists(
                    name="target_project_path_exists",
                    path=self._resolve_path(workspace_root, scenario_definition.project),
                    failure_status=StepStatus.BLOCKED,
                    missing_message="Target project path does not exist.",
                )
            )
        return checks

    def _check_required_dependencies(self, scenario_definition: ScenarioDefinition) -> list[PreflightCheckResult]:
        checks: list[PreflightCheckResult] = []
        used_step_types = {step.step_type for step in scenario_definition.steps}
        if ScenarioStepType.API in used_step_types:
            checks.append(self._check_import_available("dependency_requests_available", "requests"))
        if ScenarioStepType.DB in used_step_types:
            checks.append(self._check_import_available("dependency_psycopg_available", "psycopg"))
        return checks

    def _check_tool_entrypoints(
        self,
        scenario_definition: ScenarioDefinition,
        workspace_root: Path,
    ) -> list[PreflightCheckResult]:
        checks: list[PreflightCheckResult] = []
        used_step_types = {step.step_type for step in scenario_definition.steps}
        if ScenarioStepType.API in used_step_types:
            checks.append(
                self._check_path_exists(
                    name="api_tool_entrypoint_exists",
                    path=workspace_root / "tools" / "api" / "run_request.py",
                    failure_status=StepStatus.ERROR,
                    missing_message="Required API tool entrypoint is missing.",
                )
            )
        if ScenarioStepType.DB in used_step_types:
            checks.append(
                self._check_path_exists(
                    name="db_tool_entrypoint_exists",
                    path=workspace_root / "tools" / "db" / "query_check.py",
                    failure_status=StepStatus.ERROR,
                    missing_message="Required DB tool entrypoint is missing.",
                )
            )
        return checks

    def _check_output_directories(self, workspace_root: Path) -> list[PreflightCheckResult]:
        checks: list[PreflightCheckResult] = []
        for directory in (PARSED_PLANS_DIRNAME, RUNS_DIRNAME, ARTIFACTS_DIRNAME):
            target = workspace_root / directory
            try:
                target.mkdir(parents=True, exist_ok=True)
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    PreflightCheckResult(
                        name=f"output_directory_available:{directory.as_posix()}",
                        status=StepStatus.ERROR,
                        message=f"Output directory cannot be created: {exc}",
                        details={"path": str(target)},
                    )
                )
            else:
                checks.append(
                    self._pass(
                        f"output_directory_available:{directory.as_posix()}",
                        "Output directory is available.",
                        path=target,
                    )
                )
        return checks

    @staticmethod
    def _check_required_text(name: str, value: str, message: str) -> PreflightCheckResult:
        if value.strip():
            return PreflightCheckResult(name=name, status=StepStatus.PASS, message="Value is present.")
        return PreflightCheckResult(name=name, status=StepStatus.BLOCKED, message=message)

    @classmethod
    def _check_path_exists(
        cls,
        name: str,
        path: Path,
        failure_status: StepStatus,
        missing_message: str,
    ) -> PreflightCheckResult:
        if path.exists():
            return cls._pass(name, "Path exists.", path=path)
        return PreflightCheckResult(
            name=name,
            status=failure_status,
            message=missing_message,
            details={"path": str(path)},
        )

    @staticmethod
    def _check_import_available(name: str, module_name: str) -> PreflightCheckResult:
        try:
            module_spec = importlib.util.find_spec(module_name)
        except Exception as exc:  # noqa: BLE001
            return PreflightCheckResult(
                name=name,
                status=StepStatus.ERROR,
                message=f"Could not check Python dependency '{module_name}': {exc}",
            )
        if module_spec is None:
            return PreflightCheckResult(
                name=name,
                status=StepStatus.ERROR,
                message=f"Required Python dependency '{module_name}' is not importable.",
            )
        return PreflightCheckResult(
            name=name,
            status=StepStatus.PASS,
            message=f"Python dependency '{module_name}' is importable.",
        )

    @staticmethod
    def _pass(name: str, message: str, path: Path | None = None) -> PreflightCheckResult:
        details = {} if path is None else {"path": str(path)}
        return PreflightCheckResult(name=name, status=StepStatus.PASS, message=message, details=details)

    @staticmethod
    def _resolve_path(workspace_root: Path, path_value: str | Path) -> Path:
        candidate = Path(path_value)
        if candidate.is_absolute():
            return candidate
        return workspace_root / candidate

    @staticmethod
    def _find_duplicates(values: list[int]) -> list[int]:
        seen: set[int] = set()
        duplicates: set[int] = set()
        for value in values:
            if value in seen:
                duplicates.add(value)
            seen.add(value)
        return sorted(duplicates)
