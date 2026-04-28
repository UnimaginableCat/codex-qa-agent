"""Template helpers for scaffolded authoring-plan YAML files."""

from __future__ import annotations

from .models import (
    AuthoringCase,
    AuthoringDefaults,
    AuthoringEntityOperation,
    AuthoringEntitySpec,
    AuthoringExecute,
    AuthoringOracle,
    AuthoringPersistedStateRef,
    AuthoringPlan,
    AuthoringRoute,
    AuthoringScope,
)

AUTHORING_PLAN_TEMPLATE_VERSION = "authoring-plan-template-v1"
AUTHORING_ENTITY_INVENTORY_TEMPLATE_VERSION = "authoring-entity-inventory-template-v1"
AUTHORING_OPERATION_INVENTORY_TEMPLATE_VERSION = "authoring-operation-inventory-template-v1"


class AuthoringPlanTemplateService:
    """Create compact scaffolded authoring DSL files."""

    def build_entity_inventory_template(
        self,
        *,
        source_id: str = "",
        project: str = "",
        surface: str = "",
    ) -> dict[str, object]:
        resolved_source_id = source_id.strip() or "replace-with-source-id"
        resolved_project = project.strip() or "code/replace-project"
        resolved_surface = surface.strip() or "replace-surface"
        return {
            "version": 1,
            "source_id": resolved_source_id,
            "project": resolved_project,
            "surface": resolved_surface,
            "purpose": "Inventory entities, lifecycle states, normalized fields, and auth/header contracts before authoring cases.",
            "entities": [
                {
                    "name": "primary_entity",
                    "id_field": "entity_id",
                    "key_fields": ["email", "status"],
                    "normalized_fields": ["email"],
                    "states": ["ACTIVE", "SUSPENDED", "ARCHIVED"],
                    "allowed_transitions": [
                        "ACTIVE -> SUSPENDED",
                        "SUSPENDED -> ACTIVE",
                        "ACTIVE -> ARCHIVED",
                        "SUSPENDED -> ARCHIVED",
                    ],
                }
            ],
            "auth_contract": {
                "actor": "api-client",
                "shared_headers": ["X-Internal-Token"],
            },
            "notes": [
                "List only entities and lifecycle facts grounded in code.",
                "Mark normalized fields like email here so later cases separate submitted vs expected values.",
            ],
            "metadata": {
                "template_version": AUTHORING_ENTITY_INVENTORY_TEMPLATE_VERSION,
                "stage": "entity_inventory",
            },
        }

    def build_operation_inventory_template(
        self,
        *,
        source_id: str = "",
        project: str = "",
        surface: str = "",
    ) -> dict[str, object]:
        resolved_source_id = source_id.strip() or "replace-with-source-id"
        resolved_project = project.strip() or "code/replace-project"
        resolved_surface = surface.strip() or "replace-surface"
        return {
            "version": 1,
            "source_id": resolved_source_id,
            "project": resolved_project,
            "surface": resolved_surface,
            "purpose": "Inventory reusable setup operations, controller routes, and expected status contracts before authoring cases.",
            "entity_operations": [
                {
                    "entity": "primary_entity",
                    "operation": "create_active",
                    "effect_state": "ACTIVE",
                    "captures": ["entity_id"],
                },
                {
                    "entity": "primary_entity",
                    "operation": "suspend",
                    "requires_state": "ACTIVE",
                    "effect_state": "SUSPENDED",
                },
            ],
            "routes": [
                {
                    "method": "POST",
                    "path": "/replace/path",
                    "success_status": 201,
                    "failure_statuses": [400, 401, 404],
                    "precondition_state": None,
                    "normalized_response_fields": ["email"],
                }
            ],
            "db_verifications": [
                {
                    "entity": "primary_entity",
                    "operation": "verify_exists",
                    "scoped_by": "entity_id",
                }
            ],
            "notes": [
                "Record the expected success HTTP code per route here instead of inferring it later from memory.",
                "For lifecycle routes, record both precondition_state and effect_state before writing workflow cases.",
            ],
            "metadata": {
                "template_version": AUTHORING_OPERATION_INVENTORY_TEMPLATE_VERSION,
                "stage": "operation_inventory",
            },
        }

    def build_template(
        self,
        *,
        source_id: str = "",
        project: str = "",
        title: str = "",
        goal: str = "",
    ) -> AuthoringPlan:
        resolved_source_id = source_id.strip() or "replace-with-source-id"
        resolved_project = project.strip() or "code/replace-project"
        resolved_title = title.strip() or "Replace with test plan title"
        resolved_goal = goal.strip() or "Replace with the feature/test goal."
        return AuthoringPlan(
            version=1,
            source_id=resolved_source_id,
            project=resolved_project,
            title=resolved_title,
            goal=resolved_goal,
            scope=AuthoringScope(
                surface="replace-surface",
                style="api-first",
                include=["replace primary flow"],
            ),
            defaults=AuthoringDefaults(
                environment="env/replace.env",
                auth="bearer",
                actor="api-client",
                headers={"X-Internal-Token": "{{internal_api_token}}"},
                scenario_variables=[
                    "run_suffix = generated:run_suffix",
                    "email_suffix = derived:run_suffix|lower",
                ],
            ),
            entities={
                "primary_entity": AuthoringEntitySpec(
                    operations={
                        "verify_exists": AuthoringEntityOperation(
                            sql="SELECT id FROM replace_table WHERE id = :entity_id",
                            params={"entity_id": "{{entity_id}}"},
                            expected_outcomes=["one row exists"],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="create-primary-entity",
                    kind="api",
                    title="Create primary entity",
                    objective="Replace with case objective.",
                    state_change="create",
                    scenario_variables=[
                        "submitted_email = template:AUTOTEST.{{email_suffix}}@Example.COM",
                        "expected_email = derived:submitted_email|lower",
                    ],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/replace/path"),
                        body={"field": "value", "email": "{{submitted_email}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        business_checks=[
                            "response JSON exists",
                            "response contains field `id`",
                            "response `email` = `{{expected_email}}`",
                        ],
                        captures=["response.json.id -> entity_id"],
                        persisted_state=AuthoringPersistedStateRef(
                            entity="primary_entity",
                            operation="verify_exists",
                        ),
                    ),
                )
            ],
            assumptions=["Replace with plan-wide assumptions if needed."],
            open_questions=["Replace with unresolved authoring questions if needed."],
            metadata={
                "template_version": AUTHORING_PLAN_TEMPLATE_VERSION,
                "authoring_workflow": "staged-v1",
                "recommended_prerequisites": [
                    "entity-inventory.yaml",
                    "operation-inventory.yaml",
                ],
            },
        )
