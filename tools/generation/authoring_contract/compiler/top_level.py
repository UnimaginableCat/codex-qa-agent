"""Top-level authoring-plan validation."""

from __future__ import annotations

import re

from tools.generation.domain.models import GenerationDiagnostic

from ..case_diagnostics.identity import _env_backed_identity_guid_diagnostics
from ..diagnostics import authoring_diagnostic
from ..helpers import _VARIABLE_NAME_PATTERN
from ..models import AuthoringPlan


def validate_top_level(
    authoring_plan: AuthoringPlan,
    source_ref: str,
) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    if authoring_plan.version != 1:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_unsupported_version",
                "Only authoring contract version=1 is supported.",
                source_ref=source_ref,
                details={"version": authoring_plan.version},
            )
        )
    if not authoring_plan.source_id.strip():
        diagnostics.append(
            authoring_diagnostic(
                "authoring_missing_source_id",
                "Authoring plan must include source_id.",
                source_ref=source_ref,
            )
        )
    if not authoring_plan.project.strip():
        diagnostics.append(
            authoring_diagnostic(
                "authoring_missing_project",
                "Authoring plan must include project.",
                source_ref=source_ref,
            )
        )
    elif not _is_code_project_path(authoring_plan.project):
        diagnostics.append(
            authoring_diagnostic(
                "authoring_project_must_target_code_subdir",
                "Authoring plan project must point at a workspace project under code/<project>.",
                source_ref=source_ref,
                details={"project": authoring_plan.project},
            )
        )
    if not authoring_plan.title.strip():
        diagnostics.append(
            authoring_diagnostic(
                "authoring_missing_title",
                "Authoring plan must include title.",
                source_ref=source_ref,
            )
        )
    if not authoring_plan.goal.strip():
        diagnostics.append(
            authoring_diagnostic(
                "authoring_missing_goal",
                "Authoring plan must include goal.",
                source_ref=source_ref,
            )
        )
    if not authoring_plan.scope.surface.strip():
        diagnostics.append(
            authoring_diagnostic(
                "authoring_missing_scope",
                "Authoring plan must include scope.surface.",
                source_ref=source_ref,
            )
        )
    if not authoring_plan.cases:
        diagnostics.append(
            authoring_diagnostic(
                "authoring_missing_cases",
                "Authoring plan must include at least one case.",
                source_ref=source_ref,
            )
        )
    diagnostics.extend(_env_backed_identity_guid_diagnostics(authoring_plan, source_ref))
    diagnostics.extend(_promotion_blocking_open_question_diagnostics(authoring_plan, source_ref))
    diagnostics.extend(_promotion_blocking_non_blocking_note_diagnostics(authoring_plan, source_ref))
    diagnostics.extend(_scope_role_coverage_diagnostics(authoring_plan, source_ref))
    diagnostics.extend(_entity_identity_diagnostics(authoring_plan))
    diagnostics.extend(_duplicate_case_id_diagnostics(authoring_plan))
    return diagnostics


_PROMOTION_BLOCKING_OPEN_QUESTION_RE = re.compile(
    r"\b(?:before|prior to)\s+(?:promot(?:e|ing|ion)|render(?:ing)?|run(?:ning)?|execut(?:e|ion))\b",
    re.IGNORECASE,
)


def _promotion_blocking_open_question_diagnostics(
    authoring_plan: AuthoringPlan,
    source_ref: str,
) -> list[GenerationDiagnostic]:
    blocking_questions: list[dict[str, object]] = [
        {"scope": "plan", "question": question}
        for question in authoring_plan.open_questions
        if _PROMOTION_BLOCKING_OPEN_QUESTION_RE.search(str(question))
    ]
    for index, case in enumerate(authoring_plan.cases, start=1):
        blocking_questions.extend(
            {
                "scope": "case",
                "case_id": case.id,
                "case_index": index,
                "question": question,
            }
            for question in case.open_questions
            if _PROMOTION_BLOCKING_OPEN_QUESTION_RE.search(str(question))
        )
    if not blocking_questions:
        return []
    return [
        authoring_diagnostic(
            "authoring_open_question_blocks_promotion",
            (
                "Open questions declare work that must be resolved before promotion or execution. "
                "Resolve these questions, mark the affected cases deferred, or move non-blocking notes "
                "out of open_questions before downstream promotion."
            ),
            source_ref=source_ref,
            details={"open_questions": blocking_questions},
        )
    ]


def _promotion_blocking_non_blocking_note_diagnostics(
    authoring_plan: AuthoringPlan,
    source_ref: str,
) -> list[GenerationDiagnostic]:
    blocking_notes = [
        {"scope": "plan", "metadata_key": "non_blocking_notes", "note": note}
        for note in _metadata_note_strings(authoring_plan.metadata.get("non_blocking_notes"))
        if _PROMOTION_BLOCKING_OPEN_QUESTION_RE.search(note)
    ]
    for index, case in enumerate(authoring_plan.cases, start=1):
        blocking_notes.extend(
            {
                "scope": "case",
                "case_id": case.id,
                "case_index": index,
                "metadata_key": "non_blocking_notes",
                "note": note,
            }
            for note in _metadata_note_strings(case.metadata.get("non_blocking_notes"))
            if _PROMOTION_BLOCKING_OPEN_QUESTION_RE.search(note)
        )
    if not blocking_notes:
        return []
    return [
        authoring_diagnostic(
            "authoring_non_blocking_note_blocks_promotion",
            (
                "metadata.non_blocking_notes contains wording that says work must be reviewed or resolved "
                "before promotion or execution. Keep true blockers in open_questions/deferred cases instead "
                "of moving them to non-blocking notes."
            ),
            source_ref=source_ref,
            details={"non_blocking_notes": blocking_notes},
        )
    ]


def _metadata_note_strings(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        notes: list[str] = []
        for item in value:
            notes.extend(_metadata_note_strings(item))
        return notes
    if isinstance(value, dict):
        notes: list[str] = []
        for item in value.values():
            notes.extend(_metadata_note_strings(item))
        return notes
    return []


def _is_code_project_path(value: str) -> bool:
    normalized = value.strip().replace("\\", "/").strip("/")
    return normalized.startswith("code/") and len(normalized.split("/", 1)[1].strip()) > 0


def _scope_role_coverage_diagnostics(
    authoring_plan: AuthoringPlan,
    source_ref: str,
) -> list[GenerationDiagnostic]:
    required_roles = _declared_scope_roles(authoring_plan)
    if not required_roles:
        return []
    covered_roles = _covered_case_roles(authoring_plan)
    waived_roles = _coverage_waived_roles(authoring_plan)
    missing_roles = sorted(required_roles - covered_roles - waived_roles)
    if not missing_roles:
        return []
    return [
        authoring_diagnostic(
            "authoring_scope_role_coverage_missing",
            (
                "Authoring scope declares role/actor coverage, but no case covers every declared role. "
                "Add explicit cases for the missing roles or document an explicit coverage waiver."
            ),
            source_ref=source_ref,
            details={
                "missing_roles": missing_roles,
                "declared_roles": sorted(required_roles),
                "covered_roles": sorted(covered_roles),
                "waived_roles": sorted(waived_roles),
                "suggestion": (
                    "Add a case with metadata.default_actor/execute.actor/coverage_claims.permissions.actor "
                    "for each missing role, or add metadata.coverage.role_waivers with a reason."
                ),
            },
        )
    ]


def _declared_scope_roles(authoring_plan: AuthoringPlan) -> set[str]:
    roles: set[str] = set()
    roles.update(_metadata_role_list(authoring_plan.metadata.get("required_actors")))
    roles.update(_metadata_role_list(authoring_plan.metadata.get("required_roles")))
    coverage = authoring_plan.metadata.get("coverage")
    if isinstance(coverage, dict):
        roles.update(_metadata_role_list(coverage.get("required_actors")))
        roles.update(_metadata_role_list(coverage.get("required_roles")))
    contracts = authoring_plan.metadata.get("contracts")
    if isinstance(contracts, dict):
        coverage_contract = contracts.get("coverage")
        if isinstance(coverage_contract, dict):
            roles.update(_metadata_role_list(coverage_contract.get("required_actors")))
            roles.update(_metadata_role_list(coverage_contract.get("required_roles")))

    for include_item in authoring_plan.scope.include:
        normalized = str(include_item or "").lower()
        if not any(token in normalized for token in ("role", "roles", "actor", "actors", "persona", "personas")):
            continue
        roles.update(_role_tokens_from_text(normalized))
    return roles - _ROLE_COVERAGE_STOPWORDS


def _covered_case_roles(authoring_plan: AuthoringPlan) -> set[str]:
    covered: set[str] = set()
    for case in authoring_plan.cases:
        if case.execute is not None and case.execute.actor:
            covered.add(_normalize_role_token(case.execute.actor))
        default_actor = case.metadata.get("default_actor")
        if default_actor:
            covered.add(_normalize_role_token(str(default_actor)))
        for key in ("actor", "role", "persona"):
            value = case.metadata.get(key)
            if value:
                covered.update(_metadata_role_list(value))
        coverage_claims = case.metadata.get("coverage_claims")
        if isinstance(coverage_claims, dict):
            for claim in coverage_claims.values():
                if isinstance(claim, dict):
                    covered.update(_metadata_role_list(claim.get("actor")))
                    covered.update(_metadata_role_list(claim.get("role")))
        covered.update(_case_text_role_mentions(case))
    return covered - _ROLE_COVERAGE_STOPWORDS


def _case_text_role_mentions(case: object) -> set[str]:
    text = " ".join(
        str(part or "")
        for part in (
            getattr(case, "id", ""),
            getattr(case, "title", ""),
            getattr(case, "objective", ""),
            " ".join(getattr(case, "tags", []) or []),
        )
    ).lower()
    return _role_tokens_from_text(text)


def _coverage_waived_roles(authoring_plan: AuthoringPlan) -> set[str]:
    waived: set[str] = set()
    for key in ("role_waivers", "actor_waivers", "coverage_waivers"):
        waived.update(_waived_roles_from_value(authoring_plan.metadata.get(key)))
    coverage = authoring_plan.metadata.get("coverage")
    if isinstance(coverage, dict):
        for key in ("role_waivers", "actor_waivers", "coverage_waivers"):
            waived.update(_waived_roles_from_value(coverage.get(key)))
    return waived


def _waived_roles_from_value(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {_normalize_role_token(value)}
    if isinstance(value, list):
        waived: set[str] = set()
        for item in value:
            waived.update(_waived_roles_from_value(item))
        return waived
    if isinstance(value, dict):
        role = value.get("role") or value.get("actor") or value.get("name")
        return set() if role is None else _metadata_role_list(role)
    return set()


def _metadata_role_list(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        if re.search(r"[,/;&\s]", value):
            return _role_tokens_from_text(value)
        return {_normalize_role_token(value)}
    if isinstance(value, list):
        roles: set[str] = set()
        for item in value:
            roles.update(_metadata_role_list(item))
        return roles
    return {_normalize_role_token(str(value))}


def _role_tokens_from_text(text: str) -> set[str]:
    return {
        _normalize_role_token(match.group(0))
        for match in re.finditer(r"\b[a-z][a-z0-9_-]{2,}\b", text.lower())
    }


def _normalize_role_token(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


_ROLE_COVERAGE_STOPWORDS = {
    "",
    "access",
    "api",
    "case",
    "cases",
    "coverage",
    "default",
    "domain",
    "effective",
    "flow",
    "flows",
    "list",
    "matrix",
    "manage",
    "permission",
    "permissions",
    "price",
    "read",
    "reads",
    "right",
    "rights",
    "role",
    "roles",
    "surface",
    "test",
    "tests",
    "verify",
}


def _entity_identity_diagnostics(authoring_plan: AuthoringPlan) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    for entity_name, entity_spec in authoring_plan.entities.items():
        normalized_id_field = entity_spec.id_field.strip()
        if normalized_id_field and not _VARIABLE_NAME_PATTERN.fullmatch(normalized_id_field):
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_invalid_entity_id_field",
                    "Entity id_field must be a machine-readable variable name such as user_id.",
                    source_ref=entity_name,
                    details={"entity": entity_name, "id_field": entity_spec.id_field},
                )
            )
        invalid_key_fields = [
            key_field
            for key_field in entity_spec.key_fields
            if not key_field.strip() or not _VARIABLE_NAME_PATTERN.fullmatch(key_field.strip())
        ]
        if invalid_key_fields:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_invalid_entity_key_field",
                    "Entity key_fields must be machine-readable variable names such as user_id.",
                    source_ref=entity_name,
                    details={"entity": entity_name, "key_fields": invalid_key_fields},
                )
            )
    return diagnostics


def _duplicate_case_id_diagnostics(authoring_plan: AuthoringPlan) -> list[GenerationDiagnostic]:
    diagnostics: list[GenerationDiagnostic] = []
    seen_case_ids: dict[str, int] = {}
    for index, case in enumerate(authoring_plan.cases, start=1):
        normalized_case_id = case.id.strip()
        if not normalized_case_id:
            continue
        first_index = seen_case_ids.get(normalized_case_id)
        if first_index is not None:
            diagnostics.append(
                authoring_diagnostic(
                    "authoring_duplicate_case_id",
                    "Authoring plan case ids must be unique.",
                    source_ref=normalized_case_id,
                    details={
                        "case_id": normalized_case_id,
                        "first_case_index": first_index,
                        "duplicate_case_index": index,
                    },
                )
            )
            continue
        seen_case_ids[normalized_case_id] = index
    return diagnostics
