"""Gap summaries, readiness categories, and promotion advice."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tools.generation.domain.models import GenerationDiagnostic
from tools.generation.rendering.models import ScenarioDraft, ScenarioDraftValidationResult
from tools.generation.review.models import (
    DraftChecklistResult,
    DraftGapSummary,
    DraftPromotionAdvisory,
    DraftReadinessCategory,
    ScenarioDraftParseStatus,
    ScenarioRequirementStatus,
)
from tools.scenario_runner.domain.models import ApiStepDefinition, ScenarioDefinition, ScenarioStep, ScenarioStepType
from tools.scenario_runner.parser import MarkdownScenarioParser
from tools.scenario_runner.runtime.validators import ScenarioStepValidator

from ..common import _dedupe_preserve_order
from .scenario_introspection import (
    _case_gaps_from_draft_metadata,
    _draft_has_auth_strategy,
    _draft_has_capture_rules,
    _draft_has_db_step,
    _draft_has_expected_assertions,
    _draft_has_request_body,
    _draft_request_body_requirement_known,
    _draft_requires_auth_strategy,
    _draft_requires_capture_rules,
    _draft_requires_db_verification,
    _draft_requires_request_body,
    _first_api_step,
    _gap_projection,
    _scenario_has_auth_strategy,
    _scenario_has_db_step,
    _scenario_request_body_requirement_known,
    _scenario_requires_auth_strategy,
    _scenario_requires_db_verification,
    _scenario_requires_request_body,
)


def _merge_gap_summaries(primary: DraftGapSummary, secondary: DraftGapSummary) -> DraftGapSummary:
    return DraftGapSummary(
        gap_codes=_dedupe_preserve_order([*primary.gap_codes, *secondary.gap_codes]),
        gap_messages=_dedupe_preserve_order([*primary.gap_messages, *secondary.gap_messages]),
    )

def _draft_gap_summary(
    draft: ScenarioDraft,
    validation: ScenarioDraftValidationResult | None,
    *,
    route_binding: dict[str, object],
    render_diagnostics: list[GenerationDiagnostic],
    has_unsupported_items: bool,
    has_deferred_items: bool,
) -> DraftGapSummary:
    gap_codes: list[str] = []
    gap_messages: list[str] = []
    parse_valid = validation is not None and validation.parse_valid
    if not parse_valid:
        gap_codes.append("parser_invalid")
        gap_messages.append("Draft is not parser-valid.")

    method = str(route_binding.get("http_method") or "").upper()
    if _draft_requires_request_body(draft):
        if not _draft_has_request_body(draft):
            gap_codes.append("request_body_not_inferred")
            gap_messages.append("Request body is required for this case but not present in the draft.")
    elif not _draft_request_body_requirement_known(draft) and method in {"POST", "PUT", "PATCH"}:
        gap_codes.append("request_body_not_inferred")
        gap_messages.append("Request body not inferred.")
    if not _draft_has_expected_assertions(draft):
        gap_codes.append("assertions_not_generated")
        gap_messages.append("Assertions were not generated.")
    if _draft_requires_capture_rules(draft) and not _draft_has_capture_rules(draft):
        gap_codes.append("captures_not_generated")
        gap_messages.append("Captures were not generated.")
    if _draft_requires_auth_strategy(draft) and not _draft_has_auth_strategy(draft):
        gap_codes.append("auth_headers_unresolved")
        gap_messages.append("Auth strategy is required for this case but not present in the draft.")
    if _draft_requires_db_verification(draft) and not _draft_has_db_step(draft):
        gap_codes.append("db_verification_absent")
        gap_messages.append("DB verification is required for this case but no DB step is present in the draft.")

    readiness = str(route_binding.get("readiness") or "")
    if readiness == "route_resolved" and gap_codes:
        gap_codes.append("non_route_requirements_remaining")
        gap_messages.append("Route is resolved, but non-route execution details still remain.")

    for gap in _case_gaps_from_draft_metadata(draft):
        code, message = _gap_projection(gap)
        if code:
            gap_codes.append(code)
        if message:
            gap_messages.append(message)

    for diagnostic in render_diagnostics:
        if diagnostic.code == "rendered_with_partial_information":
            continue
        if diagnostic.code not in gap_codes:
            gap_codes.append(diagnostic.code)
            gap_messages.append(diagnostic.message)
    if has_unsupported_items:
        gap_codes.append("unsupported_items_present")
        gap_messages.append("Unsupported review items are associated with this draft.")
    if has_deferred_items:
        gap_codes.append("deferred_items_present")
        gap_messages.append("Deferred review items are associated with this draft.")
    return DraftGapSummary(
        gap_codes=_dedupe_preserve_order(gap_codes),
        gap_messages=_dedupe_preserve_order(gap_messages),
    )

def _revalidation_gap_summary(
    draft: ScenarioDraft,
    validation: ScenarioDraftValidationResult,
    *,
    route_binding: dict[str, object],
    scenario: ScenarioDefinition | None,
) -> DraftGapSummary:
    gap_codes: list[str] = []
    gap_messages: list[str] = []
    if not validation.parse_valid:
        gap_codes.append("parser_invalid")
        gap_messages.append("Scenario file is not parser-valid.")

    api_step = _first_api_step(scenario)
    method = str(route_binding.get("http_method") or "").upper()
    if _scenario_requires_request_body(scenario, draft):
        if api_step is None or api_step.api is None or api_step.api.body is None:
            gap_codes.append("request_body_not_inferred")
            gap_messages.append("Request body is required for this scenario but not present.")
    elif (
        api_step is not None
        and method in {"POST", "PUT", "PATCH"}
        and not _scenario_request_body_requirement_known(scenario, draft)
        and api_step.api is not None
        and api_step.api.body is None
    ):
        gap_codes.append("request_body_not_inferred")
        gap_messages.append("Request body or minimal request structure is missing.")

    has_step_expectation = any(
        step.api is not None and step.api.expected
        for step in (scenario.steps if scenario is not None else [])
        if step.step_type == ScenarioStepType.API
    )
    has_db_expectation = any(
        step.db is not None and step.db.expected
        for step in (scenario.steps if scenario is not None else [])
        if step.step_type == ScenarioStepType.DB
    )
    has_final_expectation = bool(scenario is not None and scenario.final_expectations)
    has_executable_final_expectation = False
    if scenario is not None and scenario.final_expectations:
        validator = ScenarioStepValidator()
        for expectation in scenario.final_expectations:
            probe = ScenarioStep(
                step_id="final-expectation-probe",
                step_number=0,
                title="Final expectations",
                step_type=ScenarioStepType.API,
                api=ApiStepDefinition(expected=[expectation]),
            )
            if any(diagnostic.supported for diagnostic in validator.inspect_contract(probe)):
                has_executable_final_expectation = True
                break
    if not (has_step_expectation or has_db_expectation or has_executable_final_expectation):
        gap_codes.append("assertions_not_generated")
        gap_messages.append("No concrete expected result or assertion was found.")
    elif has_final_expectation and not has_executable_final_expectation and not (has_step_expectation or has_db_expectation):
        gap_codes.append("assertions_not_generated")
        gap_messages.append("Final expectations are present, but they are prose notes rather than executable assertions.")

    if _scenario_requires_auth_strategy(scenario, draft) and not _scenario_has_auth_strategy(scenario, draft):
        gap_codes.append("auth_headers_unresolved")
        gap_messages.append("Auth strategy is required for this scenario but not present.")

    if _scenario_requires_db_verification(scenario, draft) and not _scenario_has_db_step(scenario):
        gap_codes.append("db_verification_absent")
        gap_messages.append("DB verification is required for this scenario but no DB step is present.")

    return DraftGapSummary(
        gap_codes=_dedupe_preserve_order(gap_codes),
        gap_messages=_dedupe_preserve_order(gap_messages),
    )

def _deferred_gap_summary(unsupported_checks: list[object]) -> DraftGapSummary:
    gap_codes: list[str] = []
    gap_messages: list[str] = []
    for check in unsupported_checks:
        gap_codes.append(str(check.reason_code))
        gap_messages.append(str(check.message))
    if not gap_codes:
        gap_codes.append("unsupported_for_preview")
        gap_messages.append("Draft preview is unsupported for this case.")
    return DraftGapSummary(
        gap_codes=_dedupe_preserve_order(gap_codes),
        gap_messages=_dedupe_preserve_order(gap_messages),
    )

def _draft_readiness_category(
    parse_status: ScenarioDraftParseStatus,
    route_binding: dict[str, object],
    gap_summary: DraftGapSummary,
) -> DraftReadinessCategory:
    if parse_status == ScenarioDraftParseStatus.INVALID:
        return DraftReadinessCategory.PARSER_INVALID
    if _has_execution_blocking_gaps(gap_summary):
        return DraftReadinessCategory.PARSER_VALID_PARTIAL
    readiness = str(route_binding.get("readiness") or "")
    if readiness in {"evidence_supported", "route_resolved", "planned_route_defined", "workflow_authored", "manual_revalidated"}:
        return DraftReadinessCategory.PARSER_VALID_STRONGLY_SUPPORTED
    return DraftReadinessCategory.PARSER_VALID_PARTIAL

def _promotion_advisory(
    *,
    parse_status: ScenarioDraftParseStatus,
    readiness_category: DraftReadinessCategory,
    has_unsupported_items: bool,
    has_deferred_items: bool,
    checklist: DraftChecklistResult,
    gap_summary: DraftGapSummary,
) -> DraftPromotionAdvisory:
    if parse_status == ScenarioDraftParseStatus.INVALID:
        return DraftPromotionAdvisory.INVALID_DRAFT
    if has_unsupported_items or has_deferred_items:
        return DraftPromotionAdvisory.NOT_RECOMMENDED_FOR_PROMOTION
    if _has_execution_blocking_gaps(gap_summary):
        return DraftPromotionAdvisory.NOT_RECOMMENDED_FOR_PROMOTION
    core_missing = {
        check.requirement.requirement_id
        for check in checklist.checks
        if check.requirement.required and check.status == ScenarioRequirementStatus.MISSING
    }
    if core_missing & {"parser_valid", "endpoint_path", "http_method"}:
        return DraftPromotionAdvisory.SAFE_PREVIEW_ONLY
    if not core_missing:
        return DraftPromotionAdvisory.PROMOTABLE_WITH_KNOWN_GAPS
    if readiness_category == DraftReadinessCategory.PARSER_VALID_STRONGLY_SUPPORTED:
        if not core_missing or core_missing <= {"request_structure", "assertions"}:
            return DraftPromotionAdvisory.PROMOTABLE_WITH_KNOWN_GAPS
    if readiness_category == DraftReadinessCategory.PARSER_VALID_STRONGLY_SUPPORTED:
        return DraftPromotionAdvisory.PROMOTABLE_WITH_KNOWN_GAPS
    return DraftPromotionAdvisory.SAFE_PREVIEW_ONLY

def _has_execution_blocking_gaps(gap_summary: DraftGapSummary) -> bool:
    blocking_codes = {
        "auth_strategy_unresolved",
        "environment_unresolved",
        "data_setup_unresolved",
        "stateful_intercase_precondition",
        "assertion_detail_unresolved",
        "compile_unsupported_expectation",
        "executable_detail_unresolved",
    }
    return any(code in blocking_codes for code in gap_summary.gap_codes)

def _expectation_contract_gap_summary_from_file(
    file_path: Path,
    draft_metadata: dict[str, Any] | None = None,
) -> DraftGapSummary:
    parse_result = MarkdownScenarioParser().parse_result(file_path)
    if parse_result.has_errors or parse_result.scenario is None:
        return DraftGapSummary(gap_codes=[], gap_messages=[])
    return _expectation_contract_gap_summary_from_scenario(parse_result.scenario, draft_metadata or {})

def _expectation_contract_gap_summary_from_scenario(
    scenario: ScenarioDefinition,
    draft_metadata: dict[str, Any] | None = None,
) -> DraftGapSummary:
    validator = ScenarioStepValidator()
    unsupported_messages: list[str] = []
    stateful_precondition_messages: list[str] = []
    data_setup_messages: list[str] = []

    for step in scenario.steps:
        for diagnostic in validator.inspect_contract(step):
            if not diagnostic.supported:
                unsupported_messages.append(diagnostic.detail)
        data_setup_messages.extend(_indexed_collection_data_setup_messages(scenario, step, draft_metadata or {}))
    for precondition in scenario.preconditions:
        normalized = str(precondition).strip()
        if _looks_like_intercase_precondition(normalized):
            stateful_precondition_messages.append(
                f"Precondition appears to depend on another scenario or external ordering: {normalized}"
            )

    gap_codes: list[str] = []
    gap_messages: list[str] = []
    if unsupported_messages:
        gap_codes.append("compile_unsupported_expectation")
        gap_messages.extend(unsupported_messages)
    if stateful_precondition_messages:
        gap_codes.append("stateful_intercase_precondition")
        gap_messages.extend(stateful_precondition_messages)
    if data_setup_messages:
        gap_codes.append("data_setup_unresolved")
        gap_messages.extend(data_setup_messages)
    if not gap_codes:
        return DraftGapSummary(gap_codes=[], gap_messages=[])
    return DraftGapSummary(
        gap_codes=gap_codes,
        gap_messages=_dedupe_preserve_order(gap_messages),
    )

def _indexed_collection_data_setup_messages(
    scenario: ScenarioDefinition,
    step: ScenarioStep,
    draft_metadata: dict[str, Any],
) -> list[str]:
    if step.step_type != ScenarioStepType.API or step.api is None:
        return []
    indexed_paths = _indexed_collection_paths(step.api.expected)
    if not indexed_paths:
        return []
    if _has_prior_indexed_collection_setup_evidence(scenario, step, indexed_paths):
        return []
    if _has_collection_presence_assertion(step.api.expected, indexed_paths):
        return []
    if _has_structured_fixture_contract(draft_metadata, indexed_paths):
        return []
    indexed_path_summary = ", ".join(indexed_paths[:3])
    return [
        (
            "Scenario asserts a specific indexed response collection item "
            f"({indexed_path_summary}), but no prior setup step, collection-size assertion, "
            "or explicit fixture contract guarantees that the response contains that item."
        )
    ]

def _has_prior_indexed_collection_setup_evidence(
    scenario: ScenarioDefinition,
    current_step: ScenarioStep,
    indexed_paths: list[str],
) -> bool:
    return any(
        _step_proves_indexed_collection(prior_step, current_step, indexed_paths)
        for prior_step in scenario.steps
        if prior_step.step_number < current_step.step_number
    )

def _step_proves_indexed_collection(
    prior_step: ScenarioStep,
    current_step: ScenarioStep,
    indexed_paths: list[str],
) -> bool:
    if prior_step.step_type != ScenarioStepType.API or prior_step.api is None:
        return False
    if _api_paths_match(prior_step.api.path, current_step.api.path if current_step.api is not None else ""):
        if _has_collection_presence_assertion(prior_step.api.expected, indexed_paths):
            return True
    return _captures_indexed_collection_path(prior_step.api.capture, indexed_paths)

def _api_paths_match(left: str, right: str) -> bool:
    return _normalize_api_path(left) == _normalize_api_path(right)

def _normalize_api_path(path: str) -> str:
    return str(path or "").split("?", 1)[0].strip().rstrip("/").lower()

def _captures_indexed_collection_path(capture_rules: list[str], indexed_paths: list[str]) -> bool:
    if not capture_rules:
        return False
    required_roots = _collection_roots_for_indexed_paths(indexed_paths)
    for rule in capture_rules:
        source = str(rule).split("->", 1)[0].strip().lower()
        source = source.replace("response.json.", "").replace("response.body.", "").replace("response.", "")
        for indexed_path in indexed_paths:
            normalized_path = indexed_path.replace("[", ".").replace("]", "").lower()
            if normalized_path and normalized_path in source:
                return True
        source_roots = _collection_roots_for_indexed_path(source)
        if required_roots and required_roots <= set(source_roots):
            return True
    return False

def _indexed_collection_paths(expectations: list[str]) -> list[str]:
    paths: list[str] = []
    for expectation in expectations:
        normalized = str(expectation).replace("`", "")
        match = re.search(r"\bresponse\s+([A-Za-z_][A-Za-z0-9_.\[\]]*(?:\.|\[)0(?:\.|\])[A-Za-z0-9_.\[\]]*)", normalized)
        if match:
            paths.append(match.group(1))
    return _dedupe_preserve_order(paths)

def _has_collection_presence_assertion(expectations: list[str], indexed_paths: list[str]) -> bool:
    collection_roots = _collection_roots_for_indexed_paths(indexed_paths)
    covered_roots: set[str] = set()
    for expectation in expectations:
        normalized = str(expectation).replace("`", "").strip().lower()
        for root in collection_roots:
            if re.search(rf"response\s+{re.escape(root)}\s+length\s*(?:>|>=)\s*[1-9]\d*", normalized):
                covered_roots.add(root)
            if re.search(rf"response\s+{re.escape(root)}\s+is\s+not\s+empty", normalized):
                covered_roots.add(root)
    return collection_roots <= covered_roots

def _has_structured_fixture_contract(draft_metadata: dict[str, Any], indexed_paths: list[str]) -> bool:
    collection_roots = _collection_roots_for_indexed_paths(indexed_paths)
    non_empty_paths = _structured_non_empty_paths(draft_metadata)
    return bool(collection_roots) and any(
        collection_roots <= set(_collection_roots_for_indexed_path(path)) for path in non_empty_paths
    )

def _structured_non_empty_paths(draft_metadata: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for value in _walk_metadata_values(draft_metadata):
        if isinstance(value, dict):
            for key in ("non_empty_paths", "non_empty_response_paths", "required_non_empty_paths"):
                raw_paths = value.get(key)
                if isinstance(raw_paths, str):
                    paths.append(raw_paths)
                elif isinstance(raw_paths, (list, tuple, set)):
                    paths.extend(str(item) for item in raw_paths)
    return _dedupe_preserve_order([path for path in paths if path.strip()])

def _walk_metadata_values(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for nested in value.values():
            values.extend(_walk_metadata_values(nested))
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            values.extend(_walk_metadata_values(nested))
    return values

def _collection_roots_for_indexed_paths(indexed_paths: list[str]) -> set[str]:
    roots: set[str] = set()
    for path in indexed_paths:
        roots.update(_collection_roots_for_indexed_path(path))
    return roots

def _collection_roots_for_indexed_path(path: str) -> list[str]:
    normalized = path.replace("[", ".").replace("]", "")
    parts = [part for part in normalized.split(".") if part]
    roots: list[str] = []
    for index, part in enumerate(parts):
        if part == "0" and index > 0:
            roots.append(".".join(parts[:index]).lower())
    return _dedupe_preserve_order(roots)

def _looks_like_intercase_precondition(value: str) -> bool:
    normalized = value.lower()
    patterns = (
        r"\bbefore this case runs\b",
        r"\bmust (?:already )?(?:exist|be present|be set|be granted)\b",
        r"\brequires? .*\bto be present\b",
        r"\bhas .*=.* before\b",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)

def _route_status(route_binding: dict[str, object]) -> str:
    if not route_binding:
        return "unresolved"
    source = str(route_binding.get("route_source") or "")
    confidence = str(route_binding.get("confidence") or "")
    if confidence == "weak_inference":
        return "low_confidence"
    if source == "planned_route":
        return "resolved_from_planned_route"
    if source == "route_hints":
        return "resolved_from_route_hints"
    if source == "evidence_hints":
        return "resolved_from_legacy_metadata"
    return "resolved"
