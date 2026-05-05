"""Enums for scenario draft review contracts."""

from __future__ import annotations

from enum import StrEnum


class ScenarioDraftParseStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"

class DraftReadinessCategory(StrEnum):
    PARSER_VALID_PARTIAL = "parser_valid_partial"
    PARSER_VALID_STRONGLY_SUPPORTED = "parser_valid_strongly_supported"
    PARSER_INVALID = "parser_invalid"
    UNSUPPORTED_DEFERRED = "unsupported_deferred"

class DraftPromotionAdvisory(StrEnum):
    SAFE_PREVIEW_ONLY = "safe_preview_only"
    PROMOTABLE_WITH_KNOWN_GAPS = "promotable_with_known_gaps"
    NOT_RECOMMENDED_FOR_PROMOTION = "not_recommended_for_promotion"
    INVALID_DRAFT = "invalid_draft"

class ScenarioRequirementStatus(StrEnum):
    SATISFIED = "satisfied"
    MISSING = "missing"
    PARTIALLY_SATISFIED = "partially_satisfied"

class DraftEditTargetType(StrEnum):
    ADD_REQUEST_BODY = "add_request_body"
    ADD_EXPECTED_ASSERTION = "add_expected_assertion"
    ADD_AUTH_HEADERS = "add_auth_headers"
    ADD_DB_VERIFICATION = "add_db_verification"
    ADD_CAPTURE = "add_capture"
    CLARIFY_NOTES_ONLY = "clarify_notes_only"
    FIX_PARSER_ERRORS = "fix_parser_errors"

class PatchTemplateType(StrEnum):
    SECTION_STUB = "section_stub"
    STRUCTURAL_HINT = "structural_hint"

class ScenarioCompileStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

class CompileIssueType(StrEnum):
    PARSE_ERROR = "parse_error"
    COMPILE_ERROR = "compile_error"
    COMPILE_WARNING = "compile_warning"
    VARIABLE_REQUIREMENT = "variable_requirement"
    EXPECTATION_DSL = "expectation_dsl"
    CAPTURE_REFERENCE = "capture_reference"
    STEP_REFERENCE = "step_reference"

class ExecutionReadinessCategory(StrEnum):
    PARSER_INVALID = "parser_invalid"
    COMPILE_BLOCKED = "compile_blocked"
    COMPILE_VALID_BUT_INCOMPLETE = "compile_valid_but_incomplete"
    COMPILE_VALID_RUNNER_READY = "compile_valid_runner_ready"

class ScenarioPreflightStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

class PreflightIssueType(StrEnum):
    PARSE_ERROR = "parse_error"
    COMPILE_ERROR = "compile_error"
    MISSING_ENVIRONMENT = "missing_environment"
    MISSING_PROJECT = "missing_project"
    MISSING_DEPENDENCY = "missing_dependency"
    EXTERNAL_VARIABLE = "external_variable"
    WORKSPACE_OUTPUT = "workspace_output"
    SCENARIO_SHAPE = "scenario_shape"
    UNKNOWN = "unknown"

class ExecutionEnvironmentReadinessCategory(StrEnum):
    PREFLIGHT_BLOCKED = "preflight_blocked"
    PREFLIGHT_READY_WITH_WARNINGS = "preflight_ready_with_warnings"
    PREFLIGHT_READY = "preflight_ready"
    SKIPPED_DUE_TO_PARSER_ERROR = "skipped_due_to_parser_error"
    SKIPPED_DUE_TO_COMPILE_ERROR = "skipped_due_to_compile_error"
