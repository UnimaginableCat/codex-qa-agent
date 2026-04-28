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


class AuthoringPlanTemplateService:
    """Create compact scaffolded authoring DSL files."""

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
                scenario_variables=["run_suffix = generated:run_suffix"],
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
                    scenario_variables=["primary_email = template:autotest.{{run_suffix}}@example.com"],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/replace/path"),
                        body={"field": "value", "email": "{{primary_email}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        business_checks=["response JSON exists", "response contains field `id`"],
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
            metadata={"template_version": AUTHORING_PLAN_TEMPLATE_VERSION},
        )
