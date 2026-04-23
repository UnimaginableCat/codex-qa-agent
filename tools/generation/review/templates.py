"""Deterministic patch template catalog for draft scenario editing."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    DraftEditTargetType,
    DraftPatchSuggestion,
    PatchTemplate,
    PatchTemplateCatalog,
    PatchTemplateType,
)


@dataclass(slots=True)
class PatchTemplateCatalogService:
    """Read-only catalog mapping edit target types to section-aware markdown stubs."""

    catalog: PatchTemplateCatalog = field(default_factory=lambda: _DEFAULT_CATALOG)

    def list_templates(self) -> PatchTemplateCatalog:
        return PatchTemplateCatalog.from_dict(self.catalog.to_dict())

    def get_template(self, target_type: DraftEditTargetType) -> PatchTemplate | None:
        for template in self.catalog.templates:
            if template.target_type == target_type:
                return PatchTemplate.from_dict(template.to_dict())
        return None

    def suggestion_for(self, target_type: DraftEditTargetType) -> DraftPatchSuggestion:
        template = self.get_template(target_type)
        if template is None:
            return DraftPatchSuggestion()
        return DraftPatchSuggestion(
            template_id=template.template_id,
            template_preview=list(template.template_lines),
            usage_notes=list(template.usage_notes),
        )


def _template(
    *,
    template_id: str,
    target_type: DraftEditTargetType,
    section_name: str,
    title: str,
    description: str,
    template_lines: list[str],
    usage_notes: list[str],
    template_type: PatchTemplateType = PatchTemplateType.SECTION_STUB,
) -> PatchTemplate:
    return PatchTemplate(
        template_id=template_id,
        target_type=target_type,
        section_name=section_name,
        title=title,
        description=description,
        template_lines=template_lines,
        usage_notes=usage_notes,
        template_type=template_type,
    )


_DEFAULT_CATALOG = PatchTemplateCatalog(
    catalog_version="v1",
    templates=[
        _template(
            template_id="steps.add_request_body.v1",
            target_type=DraftEditTargetType.ADD_REQUEST_BODY,
            section_name="Steps",
            title="Add minimal request body",
            description="Adds a placeholder body shape under the API step without inventing field values.",
            template_lines=[
                "Body:",
                "```json",
                "{",
                '  "<field>": "<value>"',
                "}",
                "```",
            ],
            usage_notes=[
                "Replace placeholder keys and values with operator-confirmed request data.",
                "Remove this block if the endpoint does not accept a body.",
            ],
        ),
        _template(
            template_id="final-expectations.add_expected_assertion.v1",
            target_type=DraftEditTargetType.ADD_EXPECTED_ASSERTION,
            section_name="Final expectations",
            title="Add deterministic assertion",
            description="Adds one placeholder assertion line for an operator-confirmed outcome.",
            template_lines=[
                "- Verify `<observable result>` equals `<expected value>`.",
            ],
            usage_notes=[
                "Use an observable HTTP response, field, status, or persisted-state expectation.",
                "Do not keep placeholder text before promotion.",
            ],
        ),
        _template(
            template_id="preconditions.add_auth_headers.v1",
            target_type=DraftEditTargetType.ADD_AUTH_HEADERS,
            section_name="Preconditions",
            title="Add auth/header strategy",
            description="Records the auth or header requirement without exposing secrets.",
            template_lines=[
                "- Required auth/header strategy is configured in the selected environment.",
                "- Do not inline secrets; reference env configuration only.",
            ],
            usage_notes=[
                "Keep tokens and credentials in environment files, not in scenario markdown.",
                "Move concrete request headers to the API step only when they are non-secret and required.",
            ],
        ),
        _template(
            template_id="notes.add_db_verification.v1",
            target_type=DraftEditTargetType.ADD_DB_VERIFICATION,
            section_name="Notes",
            title="Add DB verification target",
            description="Captures a read-only persisted-state verification target.",
            template_lines=[
                "- DB verification needed: confirm `<table/entity>` has `<expected state>` using a read-only query.",
            ],
            usage_notes=[
                "Do not add mutating SQL.",
                "Use this as a planning note until a concrete read-only verification step is reviewed.",
            ],
        ),
        _template(
            template_id="steps.add_capture.v1",
            target_type=DraftEditTargetType.ADD_CAPTURE,
            section_name="Steps",
            title="Add response capture",
            description="Adds a placeholder capture instruction when later steps need a response value.",
            template_lines=[
                "Capture:",
                "- `<variable_name>` from `<response.path>`",
            ],
            usage_notes=[
                "Add captures only when later steps or checks actually use the value.",
                "Replace placeholders with the runner-supported capture shape before execution.",
            ],
        ),
        _template(
            template_id="scenario-root.fix_parser_errors.v1",
            target_type=DraftEditTargetType.FIX_PARSER_ERRORS,
            section_name="Scenario root",
            title="Restore parser-required structure",
            description="Lists the minimum top-level sections expected for parser-valid scenario markdown.",
            template_lines=[
                "# Scenario: <name>",
                "",
                "## Project",
                "<project>",
                "",
                "## Environment",
                "env/<project>.env",
                "",
                "## Steps",
            ],
            usage_notes=[
                "Use only to repair structure; preserve reviewed draft content where possible.",
                "Run parser validation after structural edits.",
            ],
            template_type=PatchTemplateType.STRUCTURAL_HINT,
        ),
        _template(
            template_id="notes.clarify_notes_only.v1",
            target_type=DraftEditTargetType.CLARIFY_NOTES_ONLY,
            section_name="Notes",
            title="Clarify unresolved draft details",
            description="Adds a compact note for missing route, environment, auth, or business details.",
            template_lines=[
                "- Clarification needed: `<what is unresolved>`.",
                "- Required operator decision: `<decision or source of truth>`.",
            ],
            usage_notes=[
                "Use when the draft is not ready for executable detail.",
                "Do not convert clarification notes into assertions until behavior is confirmed.",
            ],
        ),
    ],
)
