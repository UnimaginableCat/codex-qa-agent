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
    blocking_questions = [
        question
        for question in authoring_plan.open_questions
        if _PROMOTION_BLOCKING_OPEN_QUESTION_RE.search(str(question))
    ]
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


def _is_code_project_path(value: str) -> bool:
    normalized = value.strip().replace("\\", "/").strip("/")
    return normalized.startswith("code/") and len(normalized.split("/", 1)[1].strip()) > 0


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
