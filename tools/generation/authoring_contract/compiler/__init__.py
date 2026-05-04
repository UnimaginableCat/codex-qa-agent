"""Deterministic compiler from compact authoring-plan into AgentTestPlanInput."""

from __future__ import annotations

from pathlib import Path

from tools.generation.authoring import validate_agent_plan_input
from tools.generation.domain.models import AgentPlannedTestCaseInput

from ..diagnostics import build_authoring_message, derive_authoring_status
from ..inventory_diagnostics import (
    _required_stage_inventory_diagnostics,
    _stage_inventory_contract_diagnostics,
    suppress_inventory_backed_same_state_warnings,
)
from ..loaders import AuthoringPlanLoader
from ..models import AuthoringPlan, AuthoringPlanCompileResult, AuthoringPlanLoadResult
from .case import compile_case
from .plan import build_agent_plan
from .top_level import validate_top_level


class AuthoringPlanCompiler:
    """Compile compact authoring DSL into the current internal IR."""

    def __init__(self, loader: AuthoringPlanLoader | None = None) -> None:
        self.loader = loader or AuthoringPlanLoader()

    def load(self, file_path: Path) -> AuthoringPlanLoadResult:
        return self.loader.load(file_path)

    def validate(self, authoring_plan: AuthoringPlan, *, file_path: Path | None = None) -> AuthoringPlanCompileResult:
        return self._compile(authoring_plan, file_path=file_path, validation_only=True)

    def validate_file(self, file_path: Path) -> AuthoringPlanCompileResult:
        return self._compile_file(file_path, validation_only=True)

    def compile(self, authoring_plan: AuthoringPlan, *, file_path: Path | None = None) -> AuthoringPlanCompileResult:
        return self._compile(authoring_plan, file_path=file_path, validation_only=False)

    def compile_file(self, file_path: Path) -> AuthoringPlanCompileResult:
        return self._compile_file(file_path, validation_only=False)

    def _compile_file(
        self,
        file_path: Path,
        *,
        validation_only: bool,
    ) -> AuthoringPlanCompileResult:
        load_result = self.load(file_path)
        inventory_diagnostics = _required_stage_inventory_diagnostics(file_path)
        load_result.diagnostics = [*load_result.diagnostics, *inventory_diagnostics]
        if load_result.authoring_plan is None:
            status = derive_authoring_status(load_result.diagnostics)
            return AuthoringPlanCompileResult(
                status=status,
                message=build_authoring_message(status, load_result.diagnostics, compiled=not validation_only),
                file_path=file_path,
                diagnostics=load_result.diagnostics,
            )
        load_result.diagnostics.extend(
            _stage_inventory_contract_diagnostics(file_path=file_path, authoring_plan=load_result.authoring_plan)
        )
        result = self._compile(load_result.authoring_plan, file_path=file_path, validation_only=validation_only)
        result.diagnostics = [*load_result.diagnostics, *result.diagnostics]
        result.diagnostics = suppress_inventory_backed_same_state_warnings(
            file_path=file_path,
            diagnostics=result.diagnostics,
        )
        result.status = derive_authoring_status(result.diagnostics)
        result.message = build_authoring_message(result.status, result.diagnostics, compiled=not validation_only)
        return result

    def _compile(
        self,
        authoring_plan: AuthoringPlan,
        *,
        file_path: Path | None,
        validation_only: bool,
    ) -> AuthoringPlanCompileResult:
        source_ref = str(file_path) if file_path is not None else authoring_plan.source_id
        diagnostics = validate_top_level(authoring_plan, source_ref)
        compiled_cases: list[AgentPlannedTestCaseInput] = []
        for index, case in enumerate(authoring_plan.cases, start=1):
            compiled_case, case_diagnostics = compile_case(authoring_plan, case, index=index)
            diagnostics.extend(case_diagnostics)
            if compiled_case is not None:
                compiled_cases.append(compiled_case)
        status = derive_authoring_status(diagnostics)
        compiled_plan = None
        if status == derive_authoring_status([]):
            compiled_plan = build_agent_plan(authoring_plan, compiled_cases)
            diagnostics.extend(validate_agent_plan_input(compiled_plan, source_ref))
            status = derive_authoring_status(diagnostics)
        message = build_authoring_message(status, diagnostics, compiled=not validation_only)
        return AuthoringPlanCompileResult(
            status=status,
            message=message,
            file_path=file_path,
            authoring_plan=authoring_plan,
            compiled_plan=compiled_plan,
            diagnostics=diagnostics,
            case_count=len(authoring_plan.cases),
        )
