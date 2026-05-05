"""Draft review checklist construction."""

from __future__ import annotations

from tools.generation.rendering.models import ScenarioDraft
from tools.generation.review.models import (
    DraftChecklistResult,
    DraftGapSummary,
    DraftRequirementCheck,
    ScenarioDraftParseStatus,
    ScenarioRequirement,
    ScenarioRequirementStatus,
)

from .scenario_introspection import (
    _draft_auth_requirement_known,
    _draft_has_expected_assertions,
    _draft_request_body_requirement_known,
    _draft_requires_auth_strategy,
    _draft_requires_request_body,
)


def _build_draft_checklist(
    draft: ScenarioDraft,
    *,
    parse_status: ScenarioDraftParseStatus,
    route_binding: dict[str, object],
    gap_summary: DraftGapSummary,
) -> DraftChecklistResult:
    requirement_defs = [
        ScenarioRequirement("parser_valid", "Draft parses successfully as scenario markdown."),
        ScenarioRequirement("endpoint_path", "Endpoint path is defined."),
        ScenarioRequirement("http_method", "HTTP method is defined."),
        ScenarioRequirement("request_structure", "Request structure is defined."),
        ScenarioRequirement("assertions", "Expected result or assertion is defined."),
        ScenarioRequirement("auth_strategy", "Auth/header strategy is defined.", required=False),
        ScenarioRequirement("db_verification", "DB verification is defined when needed.", required=False),
        ScenarioRequirement("captures", "Captures are defined when later steps need them.", required=False),
    ]
    gap_codes = set(gap_summary.gap_codes)
    checks = [
        _check_parser_valid(parse_status),
        _check_endpoint_path(route_binding, draft),
        _check_http_method(route_binding, draft),
        _check_request_structure(route_binding, draft, gap_codes),
        _check_assertions(draft, gap_codes),
        _check_auth_strategy(draft, gap_codes),
        _check_db_verification(gap_codes),
        _check_captures(gap_codes),
    ]
    # keep requirement descriptions canonical even if helper changed fields
    checks_by_id = {check.requirement.requirement_id: check for check in checks}
    ordered_checks = []
    for requirement in requirement_defs:
        check = checks_by_id[requirement.requirement_id]
        check.requirement = requirement
        ordered_checks.append(check)

    satisfied = sum(1 for check in ordered_checks if check.status == ScenarioRequirementStatus.SATISFIED)
    missing = sum(1 for check in ordered_checks if check.status == ScenarioRequirementStatus.MISSING)
    partial = sum(
        1 for check in ordered_checks if check.status == ScenarioRequirementStatus.PARTIALLY_SATISFIED
    )
    total = len(ordered_checks)
    completeness_ratio = 0.0 if total == 0 else round((satisfied + 0.5 * partial) / total, 3)
    return DraftChecklistResult(
        checklist_version="v1",
        total_requirements=total,
        satisfied_count=satisfied,
        missing_count=missing,
        partial_count=partial,
        completeness_ratio=completeness_ratio,
        checks=ordered_checks,
        diff_lines=[_diff_line(check) for check in ordered_checks],
    )

def _build_deferred_checklist(gap_summary: DraftGapSummary) -> DraftChecklistResult:
    checks = [
        DraftRequirementCheck(
            requirement=ScenarioRequirement("parser_valid", "Draft parses successfully as scenario markdown."),
            status=ScenarioRequirementStatus.MISSING,
            source="unknown",
            notes=["No rendered draft is available for parser validation."],
        ),
        DraftRequirementCheck(
            requirement=ScenarioRequirement("endpoint_path", "Endpoint path is defined."),
            status=ScenarioRequirementStatus.MISSING,
            source="unknown",
            notes=list(gap_summary.gap_messages) or ["Endpoint route is not available for this case."],
        ),
        DraftRequirementCheck(
            requirement=ScenarioRequirement("http_method", "HTTP method is defined."),
            status=ScenarioRequirementStatus.MISSING,
            source="unknown",
            notes=list(gap_summary.gap_messages) or ["HTTP method is not available for this case."],
        ),
    ]
    total = len(checks)
    missing = total
    return DraftChecklistResult(
        checklist_version="v1",
        total_requirements=total,
        satisfied_count=0,
        missing_count=missing,
        partial_count=0,
        completeness_ratio=0.0,
        checks=checks,
        diff_lines=[_diff_line(check) for check in checks],
    )

def _check_parser_valid(parse_status: ScenarioDraftParseStatus) -> DraftRequirementCheck:
    status = (
        ScenarioRequirementStatus.SATISFIED
        if parse_status == ScenarioDraftParseStatus.VALID
        else ScenarioRequirementStatus.MISSING
    )
    notes = [] if status == ScenarioRequirementStatus.SATISFIED else ["Draft is not parser-valid."]
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("parser_valid", ""),
        status=status,
        source="parser",
        notes=notes,
    )

def _check_endpoint_path(route_binding: dict[str, object], draft: ScenarioDraft) -> DraftRequirementCheck:
    route_source = str(route_binding.get("route_source") or "")
    endpoint_path = str(route_binding.get("endpoint_path") or "")
    if route_source == "workflow_db_only":
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("endpoint_path", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source=route_source,
            notes=["DB-only workflow does not require an HTTP endpoint path."],
        )
    if endpoint_path:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("endpoint_path", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source=str(route_binding.get("route_source") or "route_binding"),
            notes=[f"Endpoint path resolved as {endpoint_path}."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("endpoint_path", ""),
        status=ScenarioRequirementStatus.MISSING,
        source="unknown",
        notes=["Endpoint path is missing from route binding and draft metadata."],
    )

def _check_http_method(route_binding: dict[str, object], draft: ScenarioDraft) -> DraftRequirementCheck:
    route_source = str(route_binding.get("route_source") or "")
    http_method = str(route_binding.get("http_method") or "").upper()
    if route_source == "workflow_db_only":
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("http_method", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source=route_source,
            notes=["DB-only workflow does not require an HTTP method."],
        )
    if http_method:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("http_method", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source=str(route_binding.get("route_source") or "route_binding"),
            notes=[f"HTTP method resolved as {http_method}."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("http_method", ""),
        status=ScenarioRequirementStatus.MISSING,
        source="unknown",
        notes=["HTTP method is missing from route binding and draft metadata."],
    )

def _check_request_structure(
    route_binding: dict[str, object],
    draft: ScenarioDraft,
    gap_codes: set[str],
) -> DraftRequirementCheck:
    route_source = str(route_binding.get("route_source") or "")
    http_method = str(route_binding.get("http_method") or "").upper()
    if route_source == "workflow_db_only":
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("request_structure", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source=route_source,
            notes=["DB-only workflow does not require an HTTP request structure."],
        )
    if _draft_requires_request_body(draft) and "request_body_not_inferred" not in gap_codes:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("request_structure", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source="draft",
            notes=["Required request body is present in the draft."],
        )
    if _draft_request_body_requirement_known(draft) and not _draft_requires_request_body(draft):
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("request_structure", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source="draft",
            notes=["This case explicitly does not require a request body."],
        )
    if http_method in {"GET", "DELETE"}:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("request_structure", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source=str(route_binding.get("route_source") or "route_binding"),
            notes=["Method and path are enough for a minimal request shape."],
        )
    if "request_body_not_inferred" in gap_codes:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("request_structure", ""),
            status=ScenarioRequirementStatus.MISSING,
            source="unknown",
            notes=["Request body or minimal request structure must be added manually."],
        )
    if any(marker in draft.markdown for marker in ("Body:", "Payload:", "Request body:")):
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("request_structure", ""),
            status=ScenarioRequirementStatus.SATISFIED,
            source="draft",
            notes=["Request structure is present in the draft body."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("request_structure", ""),
        status=ScenarioRequirementStatus.PARTIALLY_SATISFIED,
        source="draft",
        notes=["Request structure is only partially defined."],
    )

def _check_assertions(draft: ScenarioDraft, gap_codes: set[str]) -> DraftRequirementCheck:
    has_expected_section = _draft_has_expected_assertions(draft)
    if "assertions_not_generated" in gap_codes:
        status = (
            ScenarioRequirementStatus.PARTIALLY_SATISFIED
            if has_expected_section
            else ScenarioRequirementStatus.MISSING
        )
        notes = ["Expected section exists, but concrete assertions still need to be added."]
        if not has_expected_section:
            notes = ["Expected assertions are missing from the draft."]
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("assertions", ""),
            status=status,
            source="draft" if has_expected_section else "unknown",
            notes=notes,
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("assertions", ""),
        status=ScenarioRequirementStatus.SATISFIED if has_expected_section else ScenarioRequirementStatus.MISSING,
        source="draft" if has_expected_section else "unknown",
        notes=["Expected section is present."] if has_expected_section else ["Expected assertions are missing."],
    )

def _check_auth_strategy(draft: ScenarioDraft, gap_codes: set[str]) -> DraftRequirementCheck:
    if _draft_auth_requirement_known(draft) and not _draft_requires_auth_strategy(draft):
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("auth_strategy", "", required=False),
            status=ScenarioRequirementStatus.SATISFIED,
            source="draft",
            notes=["This case explicitly does not require auth strategy."],
        )
    if _draft_requires_auth_strategy(draft) and _draft_has_auth_strategy(draft):
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("auth_strategy", "", required=False),
            status=ScenarioRequirementStatus.SATISFIED,
            source="draft",
            notes=["Required auth strategy is present in the draft."],
        )
    if "auth_headers_unresolved" in gap_codes:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("auth_strategy", "", required=False),
            status=ScenarioRequirementStatus.PARTIALLY_SATISFIED,
            source="unknown",
            notes=["Auth or header requirements are not yet defined."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("auth_strategy", "", required=False),
        status=ScenarioRequirementStatus.SATISFIED,
        source="draft",
        notes=["Auth strategy is either not required for this case or is already present."],
    )

def _check_db_verification(gap_codes: set[str]) -> DraftRequirementCheck:
    if "db_verification_absent" in gap_codes:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("db_verification", "", required=False),
            status=ScenarioRequirementStatus.PARTIALLY_SATISFIED,
            source="unknown",
            notes=["DB verification is absent and may need manual addition if the case requires persisted-state checks."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("db_verification", "", required=False),
        status=ScenarioRequirementStatus.SATISFIED,
        source="unknown",
        notes=["DB verification is either not required for this case or is already present."],
    )

def _check_captures(gap_codes: set[str]) -> DraftRequirementCheck:
    if "captures_not_generated" in gap_codes:
        return DraftRequirementCheck(
            requirement=ScenarioRequirement("captures", "", required=False),
            status=ScenarioRequirementStatus.PARTIALLY_SATISFIED,
            source="unknown",
            notes=["Captures are not generated and should be added only if later steps need them."],
        )
    return DraftRequirementCheck(
        requirement=ScenarioRequirement("captures", "", required=False),
        status=ScenarioRequirementStatus.SATISFIED,
        source="unknown",
        notes=["No unresolved capture requirement was detected in current artifacts."],
    )

def _diff_line(check: DraftRequirementCheck) -> str:
    status_prefix = {
        ScenarioRequirementStatus.SATISFIED: "OK",
        ScenarioRequirementStatus.MISSING: "MISSING",
        ScenarioRequirementStatus.PARTIALLY_SATISFIED: "PARTIAL",
    }[check.status]
    return f"{status_prefix} {check.requirement.description}"
