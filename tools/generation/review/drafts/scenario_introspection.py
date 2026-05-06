"""Draft and parsed-scenario introspection helpers."""

from __future__ import annotations

import re

from tools.generation.domain.gaps import project_case_gap
from tools.generation.domain.models import PlannedCaseGap
from tools.generation.rendering.models import ScenarioDraft
from tools.scenario_runner.domain.models import ScenarioDefinition, ScenarioStepType


def _route_binding_from_scenario(scenario: ScenarioDefinition | None) -> dict[str, object]:
    api_step = _first_api_step(scenario)
    if api_step is not None and api_step.api is not None:
        if not api_step.api.method or not api_step.api.path:
            return {}
        return {
            "endpoint_path": api_step.api.path,
            "http_method": api_step.api.method,
            "handler_name": api_step.api.name,
            "route_source": "manual_scenario",
            "confidence": "explicit",
            "readiness": "manual_revalidated",
        }
    if scenario is not None and any(step.step_type == ScenarioStepType.DB and step.db is not None for step in scenario.steps):
        return {
            "route_source": "workflow_db_only",
            "readiness": "manual_revalidated",
            "path_shape": "db_only",
        }
    return {}

def _route_binding_from_draft_metadata(draft: ScenarioDraft) -> dict[str, object]:
    case_support = dict(draft.metadata.get("case_support") or {})
    route_hints = case_support.get("route_hints")
    if isinstance(route_hints, list):
        valid_hints = [
            dict(hint)
            for hint in route_hints
            if isinstance(hint, dict) and hint.get("endpoint_path") and hint.get("http_method")
        ]
        if len(valid_hints) == 1:
            return {
                **valid_hints[0],
                "readiness": str(case_support.get("readiness") or valid_hints[0].get("readiness") or ""),
            }
    return dict(draft.metadata.get("route_binding") or {})

def _draft_request_body_requirement_known(draft: ScenarioDraft) -> bool:
    return isinstance(draft.metadata.get("request_body_required"), bool) or (
        "Request body required: yes." in draft.markdown or "Request body required: no." in draft.markdown
    )

def _draft_auth_requirement_known(draft: ScenarioDraft) -> bool:
    return isinstance(draft.metadata.get("auth_strategy_required"), bool) or (
        "Auth strategy required: yes." in draft.markdown or "Auth strategy required: no." in draft.markdown
    )

def _draft_requires_auth_strategy(draft: ScenarioDraft) -> bool:
    raw_value = draft.metadata.get("auth_strategy_required")
    if isinstance(raw_value, bool):
        return raw_value
    return "Auth strategy required: yes." in draft.markdown

def _draft_has_auth_strategy(draft: ScenarioDraft) -> bool:
    if draft.metadata.get("auth_strategy_present") is True:
        return True
    if re.search(r"(?im)^Auth strategy:\s", draft.markdown):
        return True
    if re.search(r"(?im)^\s*\"?(authorization|cookie|x-[^\"]*token|x-api-key|api-key)\"?\s*:", draft.markdown):
        return True
    return False

def _draft_requires_request_body(draft: ScenarioDraft) -> bool:
    raw_value = draft.metadata.get("request_body_required")
    if isinstance(raw_value, bool):
        return raw_value
    return "Request body required: yes." in draft.markdown

def _draft_has_request_body(draft: ScenarioDraft) -> bool:
    if draft.metadata.get("request_body_present") is True:
        return True
    return any(marker in draft.markdown for marker in ("Body:", "Payload:", "Request body:"))

def _draft_requires_db_verification(draft: ScenarioDraft) -> bool:
    raw_value = draft.metadata.get("db_verification_required")
    if isinstance(raw_value, bool):
        return raw_value
    return "DB verification required: yes." in draft.markdown

def _draft_has_db_step(draft: ScenarioDraft) -> bool:
    if draft.metadata.get("db_verification_present") is True:
        return True
    return bool(re.search(r"(?im)^Type:\s*db\s*$", draft.markdown))

def _draft_has_expected_assertions(draft: ScenarioDraft) -> bool:
    raw_value = draft.metadata.get("expected_assertions_present")
    if isinstance(raw_value, bool):
        return raw_value
    return bool(re.search(r"(?im)^Expected:\s*$", draft.markdown))

def _draft_requires_capture_rules(draft: ScenarioDraft) -> bool:
    raw_value = draft.metadata.get("capture_rules_required")
    if isinstance(raw_value, bool):
        return raw_value
    return False

def _draft_has_capture_rules(draft: ScenarioDraft) -> bool:
    raw_value = draft.metadata.get("capture_rules_present")
    if isinstance(raw_value, bool):
        return raw_value
    return bool(re.search(r"(?im)^Capture:\s*$", draft.markdown))

def _case_gaps_from_draft_metadata(draft: ScenarioDraft) -> list[PlannedCaseGap]:
    raw_gaps = draft.metadata.get("case_gaps", [])
    if not isinstance(raw_gaps, list):
        return []
    gaps: list[PlannedCaseGap] = []
    for item in raw_gaps:
        if not isinstance(item, dict):
            continue
        gaps.append(PlannedCaseGap.from_dict(item))
    return gaps

def _gap_projection(gap: PlannedCaseGap) -> tuple[str, str]:
    return project_case_gap(gap)

def _first_api_step(scenario: ScenarioDefinition | None):
    if scenario is None:
        return None
    for step in scenario.steps:
        if step.step_type == ScenarioStepType.API and step.api is not None:
            return step
    return None

def _scenario_has_db_step(scenario: ScenarioDefinition | None) -> bool:
    if scenario is None:
        return False
    return any(step.step_type == ScenarioStepType.DB and step.db is not None for step in scenario.steps)

def _scenario_requires_db_verification(
    scenario: ScenarioDefinition | None,
    draft: ScenarioDraft,
) -> bool:
    if scenario is not None and "DB verification required: yes." in scenario.notes:
        return True
    if _draft_requires_db_verification(draft):
        return True
    if scenario is not None and _scenario_has_db_step(scenario):
        return True
    if _scenario_declares_no_persistence_expected(scenario, draft):
        return False
    if scenario is not None and _scenario_has_successful_mutating_api_step(scenario):
        return True
    return False

def _scenario_declares_no_persistence_expected(
    scenario: ScenarioDefinition | None,
    draft: ScenarioDraft,
) -> bool:
    if draft.metadata.get("no_persistence_expected") is True:
        return True
    if scenario is not None and "No persistence expected:" in scenario.notes:
        return True
    return False

def _scenario_has_auth_strategy(
    scenario: ScenarioDefinition | None,
    draft: ScenarioDraft,
) -> bool:
    if scenario is not None and "Auth strategy:" in scenario.notes:
        return True
    if scenario is not None and _scenario_headers_have_auth_signal(scenario):
        return True
    return _draft_has_auth_strategy(draft)

def _scenario_requires_auth_strategy(
    scenario: ScenarioDefinition | None,
    draft: ScenarioDraft,
) -> bool:
    if scenario is not None and "Auth strategy required: yes." in scenario.notes:
        return True
    return _draft_requires_auth_strategy(draft)

def _scenario_request_body_requirement_known(
    scenario: ScenarioDefinition | None,
    draft: ScenarioDraft,
) -> bool:
    if scenario is not None and (
        "Request body required: yes." in scenario.notes or "Request body required: no." in scenario.notes
    ):
        return True
    return _draft_request_body_requirement_known(draft)

def _scenario_requires_request_body(
    scenario: ScenarioDefinition | None,
    draft: ScenarioDraft,
) -> bool:
    if scenario is not None and "Request body required: yes." in scenario.notes:
        return True
    return _draft_requires_request_body(draft)

def _scenario_markdownish_notes(scenario: ScenarioDefinition) -> str:
    return scenario.notes or ""

def _scenario_headers_have_auth_signal(scenario: ScenarioDefinition) -> bool:
    for step in scenario.steps:
        if step.step_type != ScenarioStepType.API or step.api is None:
            continue
        for raw_name in step.api.headers:
            name = str(raw_name).strip().lower()
            if name == "authorization":
                return True
            if "token" in name or "api-key" in name or "apikey" in name or name == "cookie":
                return True
    return False

def _scenario_has_successful_mutating_api_step(scenario: ScenarioDefinition) -> bool:
    for step in scenario.steps:
        if step.step_type != ScenarioStepType.API or step.api is None:
            continue
        if step.api.method.strip().upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
            continue
        if _api_expectations_indicate_success(step.api.expected):
            return True
    return False

def _api_expectations_indicate_success(expectations: list[str]) -> bool:
    for expectation in expectations:
        normalized = expectation.strip().upper()
        if normalized.startswith("HTTP 2"):
            return True
    return False
