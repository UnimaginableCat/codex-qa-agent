from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.generation.authoring_contract import AuthoringPlanCompiler
from tools.generation.domain.models import DiagnosticSeverity
from tools.generation.authoring_contract.models import (
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
    AuthoringStateChange,
    AuthoringSetupStep,
)


class AuthoringPlanCompilerTests(unittest.TestCase):
    def test_validate_blocks_project_outside_code_dir(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="LeadFlow",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users",
                    kind="api",
                    objective="List users.",
                    state_change="none",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/users")),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_project_must_target_code_subdir", codes)

    def test_compile_propagates_defaults_environment_actor_and_setup_auth(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(environment="env/custom.env", auth="bearer", actor="api-client"),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "create": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users"),
                            request_body={"email": "{{generated_email}}"},
                            captures=["response.json.id -> user_id"],
                        ),
                        "verify_exists": AuthoringEntityOperation(
                            sql="SELECT id FROM users WHERE id = :user_id",
                            params={"user_id": "{{user_id}}"},
                            expected_outcomes=["one row exists"],
                        ),
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="get-user-success",
                    kind="workflow",
                    objective="Get created user",
                    state_change="none",
                    setup=[AuthoringSetupStep(use_entity="user", operation="create")],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users/{{user_id}}"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                ),
                AuthoringCase(
                    id="create-user-success",
                    kind="api",
                    objective="Create user successfully",
                    state_change="create",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users"),
                        body={"email": "{{generated_email}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> user_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_exists"),
                    ),
                ),
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        self.assertEqual(result.compiled_plan.metadata["default_environment"], "env/custom.env")
        self.assertEqual(result.compiled_plan.metadata["default_actor"], "api-client")
        workflow_case = result.compiled_plan.planned_test_cases[0]
        self.assertEqual(workflow_case.metadata["default_environment"], "env/custom.env")
        self.assertEqual(workflow_case.metadata["default_actor"], "api-client")
        self.assertEqual(workflow_case.workflow_steps[0].auth_strategy, ["bearer"])
        self.assertEqual(workflow_case.workflow_steps[0].metadata["default_actor"], "api-client")

    def test_compile_propagates_setup_and_execute_step_actors(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover multi-actor grant then act workflow.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            entities={
                "permission": AuthoringEntitySpec(
                    operations={
                        "grant_partner_edit": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/price-lists/{{price_list_id}}/permissions"),
                            request_body={
                                "partners": [
                                    {
                                        "company_member_guid": "{{partner_company_member_guid}}",
                                        "can_edit": True,
                                    }
                                ]
                            },
                        ),
                        "verify_price_list": AuthoringEntityOperation(
                            sql="SELECT id FROM price_lists WHERE id = :price_list_id",
                            params={"price_list_id": "{{price_list_id}}"},
                            expected_outcomes=["one row exists"],
                        ),
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-updates-after-founder-grant",
                    kind="workflow",
                    objective="Founder grants edit and partner updates the price list.",
                    state_change="update",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="permission",
                            operation="grant_partner_edit",
                            actor="founder",
                        )
                    ],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="PUT", path="/price-lists/{{price_list_id}}"),
                        actor="partner",
                        body={"name": "{{price_list_name}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=200,
                        persisted_state=AuthoringPersistedStateRef(
                            entity="permission",
                            operation="verify_price_list",
                        ),
                    ),
                    scenario_variables=[
                        "price_list_id = env:PRICE_LIST_ID",
                        "partner_company_member_guid = env:PARTNER_COMPANY_MEMBER_GUID",
                        "price_list_name = literal:Updated",
                    ],
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        workflow_case = result.compiled_plan.planned_test_cases[0]
        self.assertEqual(workflow_case.workflow_steps[0].actor, "founder")
        self.assertEqual(workflow_case.workflow_steps[1].actor, "partner")

    def test_compile_allows_case_actor_to_override_default_actor_for_basic_auth(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            cases=[
                AuthoringCase(
                    id="partner-permissions",
                    kind="api",
                    objective="Read permissions as partner.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/{{price_list_id}}")),
                    oracle=AuthoringOracle(status_code=200),
                    metadata={"default_actor": "partner"},
                    scenario_variables=["price_list_id = env:PRICE_LIST_ID"],
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        compiled_case = result.compiled_plan.planned_test_cases[0]
        self.assertEqual(compiled_case.auth_strategy, ["basic"])
        self.assertEqual(compiled_case.metadata["default_actor"], "partner")
        self.assertNotIn("Authorization", compiled_case.request_headers)

    def test_compile_uses_execute_actor_as_api_case_default_actor(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover anonymous access.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            cases=[
                AuthoringCase(
                    id="anonymous-permissions-rejected",
                    kind="api",
                    objective="Verify unauthenticated permissions request is rejected.",
                    state_change="read_only",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/price-lists/{{price_list_id}}/permissions"),
                        actor="anonymous",
                        auth_strategy=["none"],
                    ),
                    oracle=AuthoringOracle(status_code=401),
                    scenario_variables=["price_list_id = env:PRICE_LIST_ID"],
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        compiled_case = result.compiled_plan.planned_test_cases[0]
        self.assertEqual(compiled_case.auth_strategy, ["none"])
        self.assertEqual(compiled_case.metadata["default_actor"], "anonymous")

    def test_validate_blocks_env_backed_id_equality_against_json_id(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list detail.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="basic",
                actor="member",
                scenario_variables=["price_list_id = env:PRICE_LIST_ID"],
            ),
            cases=[
                AuthoringCase(
                    id="member-reads-price-list",
                    kind="api",
                    objective="Verify member can read the target price list.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/{{price_list_id}}")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=["response `id` = `{{price_list_id}}`"],
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_env_id_equality_type_ambiguous"
                for diagnostic in result.diagnostics
            )
        )

    def test_validate_blocks_read_only_post_body_without_request_body_evidence(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover template calculation.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="contractor"),
            cases=[
                AuthoringCase(
                    id="contractor-template-calculate",
                    kind="api",
                    objective="Verify calculate masks totals.",
                    state_change="read_only",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/price-lists/{{price_list_id}}/templates/calculate"),
                        body={"template_id": "{{template_id}}"},
                    ),
                    oracle=AuthoringOracle(status_code=200),
                    scenario_variables=[
                        "price_list_id = env:PRICE_LIST_ID",
                        "template_id = literal:123",
                    ],
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_request_body_evidence_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_validate_allows_read_only_post_body_with_operation_schema_evidence(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover template calculation.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="contractor"),
            entities={
                "price_list_template": AuthoringEntitySpec(
                    operations={
                        "calculate": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/price-lists/{{price_list_id}}/templates/calculate"),
                            request_body_evidence={
                                "source_ref": "serializers/price_list_template_serializers.py",
                                "required": ["templates", "quantity"],
                            },
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="contractor-template-calculate",
                    kind="api",
                    objective="Verify calculate masks totals.",
                    state_change="read_only",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/price-lists/{{price_list_id}}/templates/calculate"),
                        body={"templates": ["{{template_id}}"], "quantity": "1.0000"},
                    ),
                    oracle=AuthoringOracle(status_code=200),
                    scenario_variables=[
                        "price_list_id = env:PRICE_LIST_ID",
                        "template_id = literal:123",
                    ],
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_request_body_evidence_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_required_permission_state_blocks_api_case_without_setup(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="document-permissions-plan",
            project="code/demo",
            title="Document permissions",
            goal="Cover document permissions.",
            scope=AuthoringScope(surface="document-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="admin"),
            cases=[
                AuthoringCase(
                    id="editor-with-publish-publishes-document",
                    kind="api",
                    objective="Actor with publish access publishes a document.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/api/documents/{{document_id}}/publish/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                    required_permission_state=[
                        {"key": "document.publish", "state": "allowed", "subject": "{{target_user_id}}"}
                    ],
                    metadata={
                        "default_actor": "editor",
                        "identity_resolution": {
                            "actor_binding": {
                                "actor": "editor",
                                "subject_variable": "target_user_id",
                                "evidence": (
                                    "actor_identity_binding: target_user_id is the current actor user_id "
                                    "for the editor actor profile."
                                ),
                            }
                        },
                    },
                    scenario_variables=[
                        "document_id = env:DOCUMENT_ID",
                        "target_user_id = literal:editor-1",
                    ],
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_state_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_required_permission_state_blocks_workflow_without_matching_effect(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="document-permissions-plan",
            project="code/demo",
            title="Document permissions",
            goal="Cover document permissions.",
            scope=AuthoringScope(surface="document-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="admin"),
            cases=[
                AuthoringCase(
                    id="editor-with-publish-publishes-document",
                    kind="api",
                    objective="Actor with publish access publishes a document.",
                    state_change="update",
                    setup=[AuthoringSetupStep(use_entity="document", operation="create_draft")],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/api/documents/{{document_id}}/publish/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                    required_permission_state=[
                        {"key": "document.publish", "state": "allowed", "subject": "{{target_user_id}}"}
                    ],
                    metadata={
                        "default_actor": "editor",
                        "identity_resolution": {
                            "actor_binding": {
                                "actor": "editor",
                                "subject_variable": "target_user_id",
                                "evidence": (
                                    "actor_identity_binding: target_user_id is the current actor user_id "
                                    "for the editor actor profile."
                                ),
                            }
                        },
                    },
                    scenario_variables=[
                        "document_id = env:DOCUMENT_ID",
                        "target_user_id = literal:editor-1",
                    ],
                )
            ],
            entities={
                "document": AuthoringEntitySpec(
                    id_field="document_id",
                    operations={
                        "create_draft": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/api/documents/"),
                            captures=["response.json.id -> document_id"],
                        )
                    },
                )
            },
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_state_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_grant_setup_satisfies_permissioned_actor_diagnostic(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="document-permissions-plan",
            project="code/demo",
            title="Document permissions",
            goal="Cover document permissions.",
            scope=AuthoringScope(surface="document-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="admin"),
            entities={
                "document_access": AuthoringEntitySpec(
                    id_field="document_access_id",
                    operations={
                        "reset_and_update_publish_access": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/api/documents/{{document_id}}/access/update/"),
                            request_body={
                                "user_id": "{{target_user_id}}",
                                "can_publish": True,
                            },
                            permission_state_effects=[
                                {
                                    "key": "document.publish",
                                    "state": "allowed",
                                    "subject": "{{target_user_id}}",
                                }
                            ],
                        )
                    },
                ),
                "document": AuthoringEntitySpec(
                    id_field="document_id",
                    operations={
                        "verify_published": AuthoringEntityOperation(
                            sql="SELECT status FROM documents WHERE id = :document_id",
                            params={"document_id": "{{document_id}}"},
                            expected_outcomes=["one row exists"],
                        )
                    },
                ),
            },
            cases=[
                AuthoringCase(
                    id="editor-with-publish-publishes-document",
                    kind="workflow",
                    objective="Actor with publish access publishes a document after access is reset and updated.",
                    state_change="update",
                    setup=[AuthoringSetupStep(use_entity="document_access", operation="reset_and_update_publish_access")],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/api/documents/{{document_id}}/publish/"),
                    ),
                    oracle=AuthoringOracle(
                        status_code=200,
                        persisted_state=AuthoringPersistedStateRef(entity="document", operation="verify_published"),
                    ),
                    required_permission_state=[
                        {"key": "document.publish", "state": "allowed", "subject": "{{target_user_id}}"}
                    ],
                    metadata={
                        "default_actor": "editor",
                        "identity_resolution": {
                            "actor_binding": {
                                "actor": "editor",
                                "subject_variable": "target_user_id",
                                "evidence": (
                                    "actor_identity_binding: target_user_id is the current actor user_id "
                                    "for the editor actor profile."
                                ),
                            }
                        },
                    },
                    scenario_variables=[
                        "document_id = env:DOCUMENT_ID",
                        "target_user_id = literal:editor-1",
                    ],
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code
                in {
                    "authoring_permission_state_setup_required",
                }
                for diagnostic in result.diagnostics
            )
        )

    def test_required_permission_state_specific_subject_or_resource_requires_specific_effect(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="document-permissions-plan",
            project="code/demo",
            title="Document permissions",
            goal="Cover document permissions.",
            scope=AuthoringScope(surface="document-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="admin"),
            entities={
                "document_access": AuthoringEntitySpec(
                    id_field="document_access_id",
                    operations={
                        "grant_publish_without_subject": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/api/documents/{{document_id}}/access/update/"),
                            request_body={"can_publish": True},
                            permission_state_effects=[
                                {
                                    "key": "document.publish",
                                    "state": "allowed",
                                    "resource": "{{document_id}}",
                                }
                            ],
                        ),
                        "grant_publish_without_resource": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/api/documents/{{document_id}}/access/update/"),
                            request_body={"user_id": "{{target_user_id}}", "can_publish": True},
                            permission_state_effects=[
                                {
                                    "key": "document.publish",
                                    "state": "allowed",
                                    "subject": "{{target_user_id}}",
                                }
                            ],
                        ),
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="specific-subject-requires-subject-effect",
                    kind="workflow",
                    objective="Actor with publish access publishes a document after access is updated for that actor.",
                    state_change="update",
                    setup=[AuthoringSetupStep(use_entity="document_access", operation="grant_publish_without_subject")],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/api/documents/{{document_id}}/publish/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                    required_permission_state=[
                        {
                            "key": "document.publish",
                            "state": "allowed",
                            "subject": "{{target_user_id}}",
                            "resource": "{{document_id}}",
                        }
                    ],
                    metadata={"default_actor": "editor"},
                    scenario_variables=[
                        "document_id = env:DOCUMENT_ID",
                        "target_user_id = literal:editor-1",
                    ],
                ),
                AuthoringCase(
                    id="specific-resource-requires-resource-effect",
                    kind="workflow",
                    objective="Actor with publish access publishes the intended document after access is updated.",
                    state_change="update",
                    setup=[AuthoringSetupStep(use_entity="document_access", operation="grant_publish_without_resource")],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/api/documents/{{document_id}}/publish/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                    required_permission_state=[
                        {
                            "key": "document.publish",
                            "state": "allowed",
                            "subject": "{{target_user_id}}",
                            "resource": "{{document_id}}",
                        }
                    ],
                    metadata={"default_actor": "editor"},
                    scenario_variables=[
                        "document_id = env:DOCUMENT_ID",
                        "target_user_id = literal:editor-1",
                    ],
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        setup_required_diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_permission_state_setup_required"
        ]
        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertEqual(len(setup_required_diagnostics), 2)

    def test_permission_setup_requires_actor_bound_identity_for_discovered_principal(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="documents-plan",
            project="code/demo",
            title="Document permissions",
            goal="Cover document permissions.",
            scope=AuthoringScope(surface="document-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="basic",
                actor="admin",
                scenario_variables=["document_id = env:DOCUMENT_ID"],
            ),
            entities={
                "document_permission": AuthoringEntitySpec(
                    operations={
                        "grant_editor_access": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/api/documents/{{document_id}}/permissions/"),
                            request_body={
                                "grants": [
                                    {
                                        "user_guid": "{{editor_user_guid}}",
                                        "can_edit": True,
                                    }
                                ]
                            },
                            permission_state_effects=[
                                {
                                    "key": "can_read",
                                    "subject": "editor",
                                    "resource": "document",
                                    "state": "true",
                                    "mode": "set",
                                }
                            ],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="editor-edit-after-grant",
                    kind="workflow",
                    objective="Editor with can_read can open a protected document.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="document_permission",
                            operation="grant_editor_access",
                            actor="admin",
                        )
                    ],
                    execute=AuthoringExecute(
                        actor="editor",
                        route=AuthoringRoute(method="GET", path="/api/documents/{{document_id}}/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_actor_identity_binding_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_setup_allows_structured_actor_identity_binding(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="documents-plan",
            project="code/demo",
            title="Document permissions",
            goal="Cover document permissions.",
            scope=AuthoringScope(surface="document-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="basic",
                actor="admin",
                scenario_variables=["document_id = env:DOCUMENT_ID"],
            ),
            entities={
                "document_permission": AuthoringEntitySpec(
                    operations={
                        "grant_editor_access": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/api/documents/{{document_id}}/permissions/"),
                            request_body={
                                "grants": [
                                    {
                                        "user_guid": "{{editor_user_guid}}",
                                        "can_edit": True,
                                    }
                                ]
                            },
                            permission_state_effects=[
                                {
                                    "key": "can_read",
                                    "subject": "editor",
                                    "resource": "document",
                                    "state": "true",
                                    "mode": "set",
                                }
                            ],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="editor-edit-after-grant",
                    kind="workflow",
                    objective="Editor with can_read can open a protected document.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="document_permission",
                            operation="grant_editor_access",
                            actor="admin",
                        )
                    ],
                    execute=AuthoringExecute(
                        actor="editor",
                        route=AuthoringRoute(method="GET", path="/api/documents/{{document_id}}/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                    metadata={
                        "identity_resolution": {
                            "actor_binding": {
                                "actor": "editor",
                                "subject_variable": "editor_user_guid",
                                "env_var": "EDITOR_USER_GUID",
                                "evidence": "actor-scoped env EDITOR_USER_GUID belongs to the editor actor profile.",
                            }
                        }
                    },
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_permission_actor_identity_binding_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_setup_rejects_weak_actor_identity_binding_prose(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="documents-plan",
            project="code/demo",
            title="Document permissions",
            goal="Cover document permissions.",
            scope=AuthoringScope(surface="document-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="basic",
                actor="admin",
                scenario_variables=["document_id = env:DOCUMENT_ID"],
            ),
            entities={
                "document_permission": AuthoringEntitySpec(
                    operations={
                        "grant_editor_access": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/api/documents/{{document_id}}/permissions/"),
                            request_body={
                                "grants": [
                                    {
                                        "user_guid": "{{editor_user_guid}}",
                                        "can_edit": True,
                                    }
                                ]
                            },
                            permission_state_effects=[
                                {
                                    "key": "can_read",
                                    "subject": "{{editor_user_guid}}",
                                    "resource": "document",
                                    "state": "true",
                                    "mode": "set",
                                }
                            ],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="editor-edit-after-grant",
                    kind="workflow",
                    objective="Editor with can_read can open a protected document.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="document_permission",
                            operation="grant_editor_access",
                            actor="admin",
                        )
                    ],
                    execute=AuthoringExecute(
                        actor="editor",
                        route=AuthoringRoute(method="GET", path="/api/documents/{{document_id}}/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                    metadata={
                        "identity_resolution": {
                            "actor_binding": "editor_user_guid is the user_guid for the editor actor profile."
                        }
                    },
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_actor_identity_binding_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_setup_rejects_effect_actor_with_unbound_discovered_identity(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="bearer",
                actor="founder",
                scenario_variables=["price_list_id = env:PRICE_LIST_ID"],
            ),
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    operations={
                        "grant_partner_edit": AuthoringEntityOperation(
                            route=AuthoringRoute(
                                method="POST",
                                path="/api/price-lists/{{price_list_id}}/permissions/update/",
                            ),
                            request_body={
                                "partners": [
                                    {
                                        "company_member_guid": "{{partner_company_member_guid}}",
                                        "can_edit": True,
                                    }
                                ]
                            },
                            permission_state_effects=[
                                {
                                    "permission": "can_edit",
                                    "actor": "partner",
                                    "state": "true",
                                    "scope": "price_list",
                                }
                            ],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-updates-after-grant",
                    kind="workflow",
                    objective="Partner updates after founder grants edit.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="price_list_permission",
                            operation="grant_partner_edit",
                            actor="founder",
                        )
                    ],
                    execute=AuthoringExecute(
                        actor="partner",
                        route=AuthoringRoute(method="PUT", path="/api/price-lists/{{price_list_id}}/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_actor_identity_binding_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_setup_rejects_weak_structured_actor_identity_binding(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="bearer",
                actor="founder",
                scenario_variables=["price_list_id = env:PRICE_LIST_ID"],
            ),
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    operations={
                        "grant_partner_edit": AuthoringEntityOperation(
                            route=AuthoringRoute(
                                method="POST",
                                path="/api/price-lists/{{price_list_id}}/permissions/update/",
                            ),
                            request_body={
                                "partners": [
                                    {
                                        "company_member_guid": "{{partner_company_member_guid}}",
                                        "can_edit": True,
                                    }
                                ]
                            },
                            permission_state_effects=[
                                {
                                    "permission": "can_edit",
                                    "actor": "partner",
                                    "state": "true",
                                }
                            ],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-updates-after-grant",
                    kind="workflow",
                    objective="Partner updates after founder grants edit.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="price_list_permission",
                            operation="grant_partner_edit",
                            actor="founder",
                        )
                    ],
                    execute=AuthoringExecute(
                        actor="partner",
                        route=AuthoringRoute(method="PUT", path="/api/price-lists/{{price_list_id}}/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                    metadata={
                        "identity_resolution": {
                            "actor_binding": {
                                "actor": "partner",
                                "subject_variable": "partner_company_member_guid",
                                "evidence": "Captured from the same company partner permissions row.",
                            }
                        }
                    },
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_actor_identity_binding_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_setup_allows_effect_actor_with_actor_owned_env_binding(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="bearer",
                actor="founder",
                scenario_variables=["price_list_id = env:PRICE_LIST_ID"],
            ),
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    operations={
                        "grant_partner_edit": AuthoringEntityOperation(
                            route=AuthoringRoute(
                                method="POST",
                                path="/api/price-lists/{{price_list_id}}/permissions/update/",
                            ),
                            request_body={
                                "partners": [
                                    {
                                        "company_member_guid": "{{partner_company_member_guid}}",
                                        "can_edit": True,
                                    }
                                ]
                            },
                            permission_state_effects=[
                                {
                                    "permission": "can_edit",
                                    "actor": "partner",
                                    "state": "true",
                                }
                            ],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-updates-after-grant",
                    kind="workflow",
                    objective="Partner updates after founder grants edit.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="price_list_permission",
                            operation="grant_partner_edit",
                            actor="founder",
                        )
                    ],
                    execute=AuthoringExecute(
                        actor="partner",
                        route=AuthoringRoute(method="PUT", path="/api/price-lists/{{price_list_id}}/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                    metadata={
                        "identity_resolution": {
                            "actor_binding": {
                                "actor": "partner",
                                "subject_variable": "partner_company_member_guid",
                                "env_var": "PARTNER_COMPANY_MEMBER_GUID",
                                "evidence": (
                                    "actor-scoped env PARTNER_COMPANY_MEMBER_GUID is the company_member_guid "
                                    "for the partner actor profile."
                                ),
                            }
                        }
                    },
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_permission_actor_identity_binding_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_setup_rejects_subject_variable_with_weak_plan_actor_binding(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="bearer",
                actor="founder",
                scenario_variables=[
                    "price_list_id = env:PRICE_LIST_ID",
                    "partner_company_member_guid = env:PRICE_LIST_PARTNER_MEMBER_GUID",
                ],
            ),
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    operations={
                        "grant_partner_edit": AuthoringEntityOperation(
                            route=AuthoringRoute(
                                method="POST",
                                path="/api/price-lists/{{price_list_id}}/permissions/update/",
                            ),
                            request_body={
                                "partners": [
                                    {
                                        "company_member_guid": "{{partner_company_member_guid}}",
                                        "can_edit": True,
                                    }
                                ]
                            },
                            permission_state_effects=[
                                {
                                    "permission": "can_edit",
                                    "subject_variable": "partner_company_member_guid",
                                    "value": True,
                                }
                            ],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-updates-after-grant",
                    kind="workflow",
                    objective="Partner updates after founder grants edit.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="price_list_permission",
                            operation="grant_partner_edit",
                            actor="founder",
                        )
                    ],
                    execute=AuthoringExecute(
                        actor="partner",
                        route=AuthoringRoute(method="PUT", path="/api/price-lists/{{price_list_id}}/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
            metadata={
                "identity_resolution": {
                    "actor_binding": {
                        "actor": "partner",
                        "subject_variable": "partner_company_member_guid",
                        "evidence": "PRICE_LIST_PARTNER_MEMBER_GUID must belong to the partner credentials.",
                    }
                }
            },
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_actor_identity_binding_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_setup_allows_subject_variable_with_strong_plan_actor_binding(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="bearer",
                actor="founder",
                scenario_variables=[
                    "price_list_id = env:PRICE_LIST_ID",
                    "partner_company_member_guid = env:PARTNER_COMPANY_MEMBER_GUID",
                ],
            ),
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    operations={
                        "grant_partner_edit": AuthoringEntityOperation(
                            route=AuthoringRoute(
                                method="POST",
                                path="/api/price-lists/{{price_list_id}}/permissions/update/",
                            ),
                            request_body={
                                "partners": [
                                    {
                                        "company_member_guid": "{{partner_company_member_guid}}",
                                        "can_edit": True,
                                    }
                                ]
                            },
                            permission_state_effects=[
                                {
                                    "permission": "can_edit",
                                    "subject_variable": "partner_company_member_guid",
                                    "value": True,
                                }
                            ],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-updates-after-grant",
                    kind="workflow",
                    objective="Partner updates after founder grants edit.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="price_list_permission",
                            operation="grant_partner_edit",
                            actor="founder",
                        )
                    ],
                    execute=AuthoringExecute(
                        actor="partner",
                        route=AuthoringRoute(method="PUT", path="/api/price-lists/{{price_list_id}}/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
            metadata={
                "identity_resolution": {
                    "actor_binding": {
                        "actor": "partner",
                        "subject_variable": "partner_company_member_guid",
                        "env_var": "PARTNER_COMPANY_MEMBER_GUID",
                        "evidence": (
                            "actor-scoped env PARTNER_COMPANY_MEMBER_GUID is the company_member_guid "
                            "for the partner actor profile."
                        ),
                    }
                }
            },
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_permission_actor_identity_binding_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_setup_rejects_strong_binding_for_different_granted_subject(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="bearer",
                actor="founder",
                scenario_variables=[
                    "price_list_id = env:PRICE_LIST_ID",
                    "partner_company_member_guid = env:PARTNER_COMPANY_MEMBER_GUID",
                    "alternate_company_member_guid = env:ALTERNATE_COMPANY_MEMBER_GUID",
                ],
            ),
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    operations={
                        "grant_alternate_edit": AuthoringEntityOperation(
                            route=AuthoringRoute(
                                method="POST",
                                path="/api/price-lists/{{price_list_id}}/permissions/update/",
                            ),
                            request_body={
                                "partners": [
                                    {
                                        "company_member_guid": "{{alternate_company_member_guid}}",
                                        "can_edit": True,
                                    }
                                ]
                            },
                            permission_state_effects=[
                                {
                                    "permission": "can_edit",
                                    "subject_variable": "alternate_company_member_guid",
                                    "value": True,
                                }
                            ],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-updates-after-alternate-grant",
                    kind="workflow",
                    objective="Partner update must not rely on a grant to a different principal.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="price_list_permission",
                            operation="grant_alternate_edit",
                            actor="founder",
                        )
                    ],
                    execute=AuthoringExecute(
                        actor="partner",
                        route=AuthoringRoute(method="PUT", path="/api/price-lists/{{price_list_id}}/"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
            metadata={
                "identity_resolution": {
                    "actor_binding": {
                        "actor": "partner",
                        "subject_variable": "partner_company_member_guid",
                        "env_var": "PARTNER_COMPANY_MEMBER_GUID",
                        "evidence": (
                            "actor-scoped env PARTNER_COMPANY_MEMBER_GUID is the company_member_guid "
                            "for the partner actor profile."
                        ),
                    }
                }
            },
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostic = next(
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_permission_actor_identity_binding_required"
        )
        self.assertEqual(diagnostic.details["subject_fields"], ["alternate_company_member_guid"])

    def test_required_permission_state_matches_boolean_false_permission_effect_value(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    operations={
                        "revoke_partner_edit": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/api/price-lists/1/permissions/update/"),
                            permission_state_effects=[
                                {
                                    "permission": "can_edit",
                                    "subject": "partner",
                                    "value": False,
                                }
                            ],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-edit-denied-after-revoke",
                    kind="workflow",
                    objective="Partner edit is denied after can_edit is revoked.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="price_list_permission",
                            operation="revoke_partner_edit",
                            actor="founder",
                        )
                    ],
                    execute=AuthoringExecute(
                        actor="partner",
                        route=AuthoringRoute(method="PUT", path="/api/price-lists/1/"),
                    ),
                    oracle=AuthoringOracle(status_code=403),
                    required_permission_state=[
                        {
                            "permission": "can_edit",
                            "subject": "partner",
                            "value": False,
                        }
                    ],
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_permission_state_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_compile_file_blocks_invalid_required_permission_state_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            authoring_plan_path = Path(tmp) / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: document-permissions-plan
project: code/demo
title: Document permissions
goal: Cover document permissions.
scope:
  surface: document-permissions
cases:
  - id: publish-document
    kind: workflow
    objective: Publish a document with declared permission state.
    state_change: update
    required_permission_state:
      - state: allowed
    execute:
      route:
        method: POST
        path: /api/documents/{{document_id}}/publish/
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_state_contract_invalid"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_prerequisite_metadata_requires_typed_required_permission_state(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-permissions-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            cases=[
                AuthoringCase(
                    id="partner-with-create-creates-price-list",
                    kind="api",
                    objective="Partner with can_create creates a price list.",
                    state_change="create",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/api/price_list/create/")),
                    oracle=AuthoringOracle(status_code=201),
                    metadata={
                        "default_actor": "partner",
                        "prerequisite_permission": "partner can_create=true must be granted before this case.",
                    },
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_prerequisite_requires_required_state"
                for diagnostic in result.diagnostics
            )
        )

    def test_evidence_supported_readiness_requires_concrete_evidence(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-permissions-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            cases=[
                AuthoringCase(
                    id="read-permissions",
                    kind="api",
                    objective="Read permissions.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/price_list/1/permissions/")),
                    oracle=AuthoringOracle(status_code=200),
                    metadata={"default_actor": "founder", "readiness": "evidence_supported"},
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_case_readiness_evidence_missing"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_setup_requires_binding_for_placeholder_grant_subject(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="basic",
                actor="founder",
                scenario_variables=["price_list_id = env:PRICE_LIST_ID"],
            ),
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    operations={
                        "grant_captured_partner_edit": AuthoringEntityOperation(
                            route=AuthoringRoute(
                                method="POST",
                                path="/api/price-list/{{price_list_id}}/permissions/update/",
                            ),
                            request_body={
                                "partners": [
                                    {
                                        "company_member_guid": "{{partner_company_member_guid}}",
                                        "can_edit": True,
                                    }
                                ]
                            },
                            permission_state_effects=[
                                {
                                    "key": "can_edit",
                                    "subject": "{{partner_company_member_guid}}",
                                    "resource": "price_list",
                                    "state": "true",
                                    "mode": "set",
                                }
                            ],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-edit-after-placeholder-grant",
                    kind="workflow",
                    objective="Partner can edit after granting the captured partner principal.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="price_list_permission",
                            operation="grant_captured_partner_edit",
                            actor="founder",
                        )
                    ],
                    execute=AuthoringExecute(
                        actor="partner",
                        route=AuthoringRoute(method="PUT", path="/api/price-list/{{price_list_id}}/update/"),
                        body={"name": "Updated"},
                    ),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_actor_identity_binding_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_scope_role_matrix_requires_cases_for_each_declared_role(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(
                surface="price-list-permissions",
                include=["partner/customer/contractor/member/outsider role matrix"],
            ),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            cases=[
                AuthoringCase(
                    id="partner-permissions",
                    kind="api",
                    objective="Partner reads permissions.",
                    state_change="read_only",
                    metadata={"default_actor": "partner"},
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/permissions/")),
                    oracle=AuthoringOracle(status_code=200),
                ),
                AuthoringCase(
                    id="customer-permissions",
                    kind="api",
                    objective="Customer reads permissions.",
                    state_change="read_only",
                    metadata={"default_actor": "customer"},
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/permissions/")),
                    oracle=AuthoringOracle(status_code=200),
                ),
                AuthoringCase(
                    id="contractor-permissions",
                    kind="api",
                    objective="Contractor reads permissions.",
                    state_change="read_only",
                    metadata={"default_actor": "contractor"},
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/permissions/")),
                    oracle=AuthoringOracle(status_code=200),
                ),
                AuthoringCase(
                    id="outsider-permissions",
                    kind="api",
                    objective="Outsider denied.",
                    state_change="read_only",
                    metadata={"default_actor": "outsider"},
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/permissions/")),
                    oracle=AuthoringOracle(status_code=403),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_scope_role_coverage_missing"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["missing_roles"], ["member"])

    def test_scope_role_matrix_accepts_declared_role_case(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(
                surface="price-list-permissions",
                include=["partner/member role matrix"],
            ),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            cases=[
                AuthoringCase(
                    id="partner-permissions",
                    kind="api",
                    objective="Partner reads permissions.",
                    state_change="read_only",
                    metadata={"default_actor": "partner"},
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/permissions/")),
                    oracle=AuthoringOracle(status_code=200),
                ),
                AuthoringCase(
                    id="member-permissions",
                    kind="api",
                    objective="Member reads permissions.",
                    state_change="read_only",
                    metadata={"default_actor": "member"},
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/permissions/")),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(diagnostic.code == "authoring_scope_role_coverage_missing" for diagnostic in result.diagnostics)
        )

    def test_scope_role_matrix_does_not_count_role_mentions_as_coverage(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            metadata={"required_roles": ["partner", "customer"]},
            cases=[
                AuthoringCase(
                    id="customer-cannot-access-partner-resources",
                    kind="api",
                    title="Customer cannot access partner resources",
                    objective="Customer cannot access partner resources.",
                    state_change="read_only",
                    tags=["partner", "negative"],
                    metadata={"default_actor": "customer"},
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/permissions/")),
                    oracle=AuthoringOracle(status_code=403),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_scope_role_coverage_missing"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["missing_roles"], ["partner"])

    def test_scope_role_matrix_ignores_generic_scope_prose(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(
                surface="price-list-permissions",
                include=["role-based access control", "actor permission flow"],
            ),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            cases=[
                AuthoringCase(
                    id="founder-permissions",
                    kind="api",
                    objective="Founder reads permissions.",
                    state_change="read_only",
                    metadata={"default_actor": "founder"},
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/permissions/")),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(diagnostic.code == "authoring_scope_role_coverage_missing" for diagnostic in result.diagnostics)
        )

    def test_scope_role_matrix_can_use_metadata_required_roles_for_freeform_scope(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(
                surface="price-list-permissions",
                include=["role-based access control"],
            ),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            metadata={"required_roles": ["partner", "customer"]},
            cases=[
                AuthoringCase(
                    id="customer-permissions",
                    kind="api",
                    objective="Customer reads permissions.",
                    state_change="read_only",
                    metadata={"default_actor": "customer"},
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/permissions/")),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_scope_role_coverage_missing"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["missing_roles"], ["partner"])

    def test_scope_role_matrix_allows_explicit_coverage_waiver(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(
                surface="price-list-permissions",
                include=["partner/member role matrix"],
            ),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            metadata={
                "coverage": {
                    "role_waivers": [
                        {"role": "member", "reason": "member actor fixture is not available in this environment."}
                    ]
                }
            },
            cases=[
                AuthoringCase(
                    id="partner-permissions",
                    kind="api",
                    objective="Partner reads permissions.",
                    state_change="read_only",
                    metadata={"default_actor": "partner"},
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/permissions/")),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(diagnostic.code == "authoring_scope_role_coverage_missing" for diagnostic in result.diagnostics)
        )

    def test_evidence_supported_readiness_rejects_placeholder_evidence_values(self) -> None:
        for placeholder in ([None], [{}], ["TODO"], {"source_ref": None}, {"source_ref": {}}):
            with self.subTest(placeholder=placeholder):
                plan = AuthoringPlan(
                    version=1,
                    source_id="price-list-permissions-plan",
                    project="code/demo",
                    title="Price list permissions",
                    goal="Cover price-list permissions.",
                    scope=AuthoringScope(surface="price-list-permissions"),
                    defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
                    cases=[
                        AuthoringCase(
                            id="read-permissions",
                            kind="api",
                            objective="Read permissions.",
                            state_change="read_only",
                            execute=AuthoringExecute(
                                route=AuthoringRoute(method="GET", path="/api/price_list/1/permissions/")
                            ),
                            oracle=AuthoringOracle(status_code=200),
                            metadata={
                                "default_actor": "founder",
                                "readiness": "evidence_supported",
                                "readiness_evidence": placeholder,
                            },
                        )
                    ],
                )

                result = AuthoringPlanCompiler().validate(plan)

                self.assertEqual(result.status, StepStatus.BLOCKED)
                self.assertTrue(
                    any(
                        diagnostic.code == "authoring_case_readiness_evidence_missing"
                        for diagnostic in result.diagnostics
                    )
                )

    def test_evidence_supported_readiness_allows_concrete_evidence(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-permissions-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(environment="env/demo.env", auth="basic", actor="founder"),
            cases=[
                AuthoringCase(
                    id="read-permissions",
                    kind="api",
                    objective="Read permissions.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/price_list/1/permissions/")),
                    oracle=AuthoringOracle(status_code=200),
                    metadata={
                        "default_actor": "founder",
                        "readiness": "evidence_supported",
                        "readiness_evidence": [
                            "operation-inventory.yaml route and status contract validated against controller source."
                        ],
                    },
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)

    def test_open_question_blocks_authoring_when_it_must_be_resolved_before_promotion(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-permissions-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            open_questions=[
                "Confirm exact JSON paths for nested position price/cost_price fields before promoting visibility cases."
            ],
            cases=[
                AuthoringCase(
                    id="read-permissions",
                    kind="api",
                    objective="Read permissions.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/price_list/1/permissions/")),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_open_question_blocks_promotion"
                for diagnostic in result.diagnostics
            )
        )

    def test_case_open_question_blocks_authoring_when_it_must_be_resolved_before_promotion(self) -> None:
        plan = AuthoringPlan.from_dict(
            {
                "version": 1,
                "source_id": "price-list-permissions-plan",
                "project": "code/demo",
                "title": "Price list permissions",
                "goal": "Cover price-list permissions.",
                "scope": {"surface": "price-list-permissions"},
                "cases": [
                    {
                        "id": "customer-detail-visibility",
                        "kind": "api",
                        "objective": "Verify customer visibility.",
                        "state_change": "read_only",
                        "execute": {"route": {"method": "GET", "path": "/api/price_list/1/"}},
                        "oracle": {"status_code": 200},
                        "open_questions": [
                            "Confirm exact JSON path for cost_price before promoting this visibility case."
                        ],
                    }
                ],
            }
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        matching = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_open_question_blocks_promotion"
        ]
        self.assertTrue(matching)
        self.assertEqual(matching[0].details["open_questions"][0]["scope"], "case")
        self.assertEqual(matching[0].details["open_questions"][0]["case_id"], "customer-detail-visibility")

    def test_non_blocking_notes_cannot_hide_promotion_blockers(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-permissions-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={
                "non_blocking_notes": [
                    "Search response shape should be reviewed before promoting visibility cases."
                ]
            },
            cases=[
                AuthoringCase(
                    id="customer-search-visibility",
                    kind="api",
                    objective="Verify customer search visibility.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/price_list/1/search/")),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_non_blocking_note_blocks_promotion"
                for diagnostic in result.diagnostics
            )
        )

    def test_validate_warns_on_env_backed_role_identity_guid_variables(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                auth="basic",
                actor="founder",
                scenario_variables=[
                    "price_list_id = env:PRICE_LIST_ID",
                    "company_member_guid = env:PRICE_LIST_PARTNER_MEMBER_GUID",
                ],
            ),
            cases=[
                AuthoringCase(
                    id="grant-partner-edit",
                    kind="api",
                    objective="Grant partner edit permission.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/api/price_list/{{price_list_id}}/permissions/update/"),
                        body={
                            "partners": [
                                {"company_member_guid": "{{company_member_guid}}", "can_edit": True},
                            ]
                        },
                    ),
                    oracle=AuthoringOracle(status_code=403),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_env_backed_role_identity_guid"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["variable"], "company_member_guid")
        self.assertEqual(diagnostics[0].details["env_name"], "PRICE_LIST_PARTNER_MEMBER_GUID")
        self.assertEqual(diagnostics[0].severity.value, "WARNING")

    def test_contract_can_disallow_env_backed_role_identity_guid_variables(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "company_member_guid = env:PRICE_LIST_PARTNER_MEMBER_GUID",
                ],
            ),
            cases=[
                AuthoringCase(
                    id="read-permissions",
                    kind="api",
                    objective="Read permissions.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/permissions")),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
            metadata={"contracts": {"identity": {"env_backed_role_identity": "disallow"}}},
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_env_backed_role_identity_disallowed"
                for diagnostic in result.diagnostics
            )
        )

    def test_identity_resolution_policy_can_allow_env_backed_guid_variables(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "company_member_guid = env:PRICE_LIST_PARTNER_MEMBER_GUID",
                ],
            ),
            cases=[
                AuthoringCase(
                    id="read-permissions",
                    kind="api",
                    objective="Read permissions.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/permissions")),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
            metadata={
                "identity_resolution": {
                    "allow_env_identity_variables": ["company_member_guid"],
                    "justification": "Partner member GUID is owned by a stable seeded fixture for this project.",
                }
            },
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(diagnostic.code == "authoring_env_backed_role_identity_guid" for diagnostic in result.diagnostics)
        )

    def test_permission_negative_case_warns_without_state_setup(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            cases=[
                AuthoringCase(
                    id="partner-create-price-list-denied-without-grant",
                    kind="api",
                    objective="Partner cannot create a price list without company-level can_create override.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/price-lists")),
                    oracle=AuthoringOracle(status_code=403, business_checks=["response JSON exists"]),
                    metadata={
                        "default_actor": "partner",
                        "coverage_claims": {
                            "permissions": {
                                "actor": "partner",
                                "permission": "can_create",
                                "expected_state": "false",
                                "expected_result": "denied",
                            }
                        },
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_negative_case_state_setup_unresolved"
                for diagnostic in result.diagnostics
            )
        )

    def test_contract_can_require_permission_negative_case_state_setup(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={"contracts": {"permissions": {"negative_cases_require_state_setup": True}}},
            cases=[
                AuthoringCase(
                    id="partner-update-price-list-denied-without-edit",
                    kind="api",
                    objective="Partner cannot update an existing price list without can_edit override.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="PUT", path="/price-lists/1")),
                    oracle=AuthoringOracle(status_code=403, business_checks=["response JSON exists"]),
                    metadata={
                        "default_actor": "partner",
                        "coverage_claims": {
                            "permissions": {
                                "actor": "partner",
                                "permission": "can_edit",
                                "expected_state": "false",
                                "expected_result": "denied",
                            }
                        },
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_negative_case_state_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_payload_validation_400_does_not_require_negative_state_setup(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(actor="founder"),
            metadata={"contracts": {"permissions": {"negative_cases_require_state_setup": True}}},
            cases=[
                AuthoringCase(
                    id="duplicate-permission-payload-validation",
                    kind="workflow",
                    objective="Verify duplicate company_member_guid values return a serializer validation response.",
                    state_change="read_only",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/price-lists/1/permissions/update/"),
                        body={
                            "partners": [
                                {"company_member_guid": "{{partner_company_member_guid}}", "can_edit": True},
                                {"company_member_guid": "{{partner_company_member_guid}}", "can_edit": False},
                            ]
                        },
                    ),
                    oracle=AuthoringOracle(status_code=400, business_checks=["response JSON exists"]),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_permission_negative_case_state_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_negative_case_does_not_infer_from_default_actor_metadata(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="document-plan",
            project="code/demo",
            title="Document permissions",
            goal="Cover document permissions.",
            scope=AuthoringScope(surface="document-permissions"),
            metadata={"contracts": {"permissions": {"negative_cases_require_state_setup": True}}},
            cases=[
                AuthoringCase(
                    id="create-document-denied",
                    kind="api",
                    objective="Create document action is denied.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/documents")),
                    oracle=AuthoringOracle(status_code=403, business_checks=["response JSON exists"]),
                    metadata={"default_actor": "contributor"},
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_permission_negative_case_state_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_negative_case_does_not_infer_from_plan_default_actor(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="document-plan",
            project="code/demo",
            title="Document permissions",
            goal="Cover document permissions.",
            scope=AuthoringScope(surface="document-permissions"),
            defaults=AuthoringDefaults(actor="contributor"),
            metadata={"contracts": {"permissions": {"negative_cases_require_state_setup": True}}},
            cases=[
                AuthoringCase(
                    id="create-document-denied",
                    kind="api",
                    objective="Create document action is denied.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/documents")),
                    oracle=AuthoringOracle(status_code=403, business_checks=["response JSON exists"]),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_permission_negative_case_state_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_negative_case_uses_structured_permission_claim_for_detection(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="document-plan",
            project="code/demo",
            title="Document permissions",
            goal="Cover document permissions.",
            scope=AuthoringScope(surface="document-permissions"),
            metadata={"contracts": {"permissions": {"negative_cases_require_state_setup": True}}},
            cases=[
                AuthoringCase(
                    id="create-document-gate",
                    kind="api",
                    objective="Create document action follows the authored permission claim.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/documents")),
                    oracle=AuthoringOracle(status_code=403, business_checks=["response JSON exists"]),
                    metadata={
                        "coverage_claims": {
                            "permissions": {
                                "actor": "contributor",
                                "permission": "can_publish",
                                "expected_state": "false",
                                "expected_result": "denied",
                            }
                        }
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_negative_case_state_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_negative_case_warns_when_stable_fixture_lacks_baseline_check(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={"contracts": {"permissions": {"negative_cases_require_state_setup": True}}},
            cases=[
                AuthoringCase(
                    id="partner-update-price-list-denied-without-edit",
                    kind="api",
                    objective="Partner cannot update an existing price list without can_edit override.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="PUT", path="/price-lists/1")),
                    oracle=AuthoringOracle(status_code=403, business_checks=["response JSON exists"]),
                    metadata={
                        "default_actor": "partner",
                        "stable_permission_fixture": "PRICE_LIST_ID has no partner can_edit override.",
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_negative_case_baseline_check_unresolved"
                for diagnostic in result.diagnostics
            )
        )

    def test_contract_can_require_permission_negative_fixture_baseline_check(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={
                "contracts": {
                    "permissions": {
                        "negative_cases_require_state_setup": True,
                        "negative_cases_require_baseline_check": True,
                    }
                }
            },
            cases=[
                AuthoringCase(
                    id="partner-update-price-list-denied-without-edit",
                    kind="api",
                    objective="Partner cannot update an existing price list without can_edit override.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="PUT", path="/price-lists/1")),
                    oracle=AuthoringOracle(status_code=403, business_checks=["response JSON exists"]),
                    metadata={
                        "default_actor": "partner",
                        "stable_permission_fixture": "PRICE_LIST_ID has no partner can_edit override.",
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_negative_case_baseline_check_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_negative_case_allows_documented_baseline_check(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={
                "contracts": {
                    "permissions": {
                        "negative_cases_require_state_setup": True,
                        "negative_cases_require_baseline_check": True,
                    }
                }
            },
            cases=[
                AuthoringCase(
                    id="partner-update-price-list-denied-without-edit",
                    kind="api",
                    objective="Partner cannot update an existing price list without can_edit override.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="PUT", path="/price-lists/1")),
                    oracle=AuthoringOracle(status_code=403, business_checks=["response JSON exists"]),
                    metadata={
                        "default_actor": "partner",
                        "stable_permission_fixture": "PRICE_LIST_ID has no partner can_edit override.",
                        "permission_baseline_checked": {
                            "verified": True,
                            "setup_operation": "read_effective_permissions",
                            "expected_state": {"can_edit": False},
                            "assertions": ["can_edit = false before execution"],
                        },
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_permission_negative_case_baseline_check_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_permission_negative_case_rejects_baseline_covered_by_another_case(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={
                "contracts": {
                    "permissions": {
                        "negative_cases_require_state_setup": True,
                        "negative_cases_require_baseline_check": True,
                    }
                }
            },
            cases=[
                AuthoringCase(
                    id="role-baseline-case",
                    kind="api",
                    objective="Check partner baseline.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/1/permissions")),
                    oracle=AuthoringOracle(status_code=200, business_checks=["response JSON exists"]),
                    metadata={"default_actor": "partner"},
                ),
                AuthoringCase(
                    id="partner-manage-permissions-denied",
                    kind="api",
                    objective="Partner cannot manage price-list permissions.",
                    state_change="read_only",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/price-lists/1/permissions/update")
                    ),
                    oracle=AuthoringOracle(status_code=403, business_checks=["response JSON exists"]),
                    metadata={
                        "default_actor": "partner",
                        "stable_permission_fixture": "partner cannot manage permissions by role matrix.",
                        "permission_baseline_checked": (
                            "GET permissions under partner is covered by role-baseline-case and asserts "
                            "can_manage_permissions false."
                        ),
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_permission_negative_case_baseline_check_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_identity_resolution_allow_requires_justification(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "company_member_guid = env:PRICE_LIST_PARTNER_MEMBER_GUID",
                ],
            ),
            cases=[
                AuthoringCase(
                    id="read-permissions",
                    kind="api",
                    objective="Read permissions.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/permissions")),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
            metadata={
                "identity_resolution": {
                    "allow_env_identity_variables": ["company_member_guid"],
                }
            },
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_identity_resolution_allow_without_justification"
                for diagnostic in result.diagnostics
            )
        )

    def test_identity_resolution_policy_warns_on_custom_discouraged_patterns(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "target_guid = env:PRICE_LIST_TARGET_GUID",
                ],
            ),
            cases=[
                AuthoringCase(
                    id="read-permissions",
                    kind="api",
                    objective="Read permissions.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/permissions")),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
            metadata={
                "identity_resolution": {
                    "disable_default_env_identity_patterns": True,
                    "env_identity_name_patterns": [r"target_guid$"],
                }
            },
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_env_backed_role_identity_guid"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["policy_source"], "metadata.identity_resolution.env_identity_name_patterns")
        self.assertEqual(diagnostics[0].severity.value, "WARNING")

    def test_identity_resolution_policy_can_disable_default_guid_patterns(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "company_member_guid = env:PRICE_LIST_PARTNER_MEMBER_GUID",
                ],
            ),
            cases=[
                AuthoringCase(
                    id="read-permissions",
                    kind="api",
                    objective="Read permissions.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/permissions")),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
            metadata={"identity_resolution": {"disable_default_env_identity_patterns": True}},
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(diagnostic.code == "authoring_env_backed_role_identity_guid" for diagnostic in result.diagnostics)
        )

    def test_visibility_claim_without_field_level_assertion_is_warning(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            cases=[
                AuthoringCase(
                    id="customer-search-masks-cost-price",
                    kind="api",
                    objective="Customer search results apply cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/search")),
                    oracle=AuthoringOracle(status_code=200, business_checks=["response JSON exists"]),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_visibility_claim_without_field_assertion"
                for diagnostic in result.diagnostics
            )
        )

    def test_contract_can_require_visibility_claim_field_level_assertion(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            cases=[
                AuthoringCase(
                    id="customer-search-masks-cost-price",
                    kind="api",
                    objective="Customer search results apply cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/search")),
                    oracle=AuthoringOracle(status_code=200, business_checks=["response JSON exists"]),
                    metadata={
                        "coverage_claims": {
                            "visibility": {
                                "fields": ["cost_price"],
                                "response_paths": ["categories.0.positions.0.cost_price"],
                            }
                        }
                    },
                ),
            ],
            metadata={"contracts": {"coverage": {"visibility_claims_require_field_assertions": True}}},
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_visibility_claim_missing_required_assertion"
                for diagnostic in result.diagnostics
            )
        )

    def test_strict_visibility_contract_does_not_block_heuristic_only_claim(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            cases=[
                AuthoringCase(
                    id="customer-search-masks-cost-price",
                    kind="api",
                    objective="Customer search results apply cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/search")),
                    oracle=AuthoringOracle(status_code=200, business_checks=["response JSON exists"]),
                ),
            ],
            metadata={"contracts": {"coverage": {"visibility_claims_require_field_assertions": True}}},
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_visibility_claim_without_field_assertion"
                for diagnostic in result.diagnostics
            )
        )
        self.assertFalse(
            any(
                diagnostic.code == "authoring_visibility_claim_missing_required_assertion"
                for diagnostic in result.diagnostics
            )
        )

    def test_visibility_contract_does_not_treat_price_list_resource_name_as_masking_claim(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            cases=[
                AuthoringCase(
                    id="create-price-list",
                    kind="api",
                    objective="Create price list.",
                    state_change="create",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/price-lists")),
                    oracle=AuthoringOracle(
                        status_code=201,
                        business_checks=["response JSON exists"],
                        persisted_state=AuthoringPersistedStateRef(
                            entity="price_list",
                            operation="verify_created",
                        ),
                    ),
                ),
            ],
            entities={
                "price_list": AuthoringEntitySpec(
                    id_field="price_list_id",
                    operations={
                        "verify_created": AuthoringEntityOperation(
                            sql="SELECT id FROM price_lists WHERE id = :price_list_id",
                            params={"price_list_id": "{{price_list_id}}"},
                            expected_outcomes=["one row exists"],
                        )
                    },
                )
            },
            metadata={"contracts": {"coverage": {"visibility_claims_require_field_assertions": True}}},
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertFalse(
            any(
                diagnostic.code == "authoring_visibility_claim_missing_required_assertion"
                for diagnostic in result.diagnostics
            )
        )

    def test_visibility_contract_treats_quoted_false_as_disabled(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            cases=[
                AuthoringCase(
                    id="customer-search-masks-cost-price",
                    kind="api",
                    objective="Customer search results apply cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/search")),
                    oracle=AuthoringOracle(status_code=200, business_checks=["response JSON exists"]),
                ),
            ],
            metadata={"contracts": {"coverage": {"visibility_claims_require_field_assertions": "false"}}},
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_visibility_claim_without_field_assertion"
                for diagnostic in result.diagnostics
            )
        )
        self.assertFalse(
            any(
                diagnostic.code == "authoring_visibility_claim_missing_required_assertion"
                for diagnostic in result.diagnostics
            )
        )

    def test_visibility_claim_allows_price_field_assertion(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            cases=[
                AuthoringCase(
                    id="customer-detail-masks-cost-price",
                    kind="api",
                    objective="Customer detail masks cost_price.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/1/positions/1")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=[
                            "response JSON exists",
                            "response `categories.0.positions.0.cost_price` = `null`",
                        ],
                    ),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_visibility_claim_without_field_assertion"
                for diagnostic in result.diagnostics
            )
        )
        self.assertFalse(
            any(
                diagnostic.code == "authoring_visibility_root_field_assertion_without_path_evidence"
                for diagnostic in result.diagnostics
            )
        )

    def test_visibility_root_price_assertion_warns_without_response_shape_evidence(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            cases=[
                AuthoringCase(
                    id="contractor-detail-masks-price",
                    kind="api",
                    objective="Contractor detail read masks price.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/1")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=["response JSON exists", "response `price` = `null`"],
                    ),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_visibility_root_field_assertion_without_path_evidence"
                for diagnostic in result.diagnostics
            )
        )

    def test_contract_can_require_visibility_root_price_response_shape_evidence(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={"contracts": {"coverage": {"root_visibility_assertions_require_path_evidence": True}}},
            cases=[
                AuthoringCase(
                    id="contractor-detail-masks-price",
                    kind="api",
                    objective="Contractor detail read masks price.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/1")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=["response JSON exists", "response `price` = `null`"],
                    ),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_visibility_root_field_assertion_requires_path_evidence"
                for diagnostic in result.diagnostics
            )
        )

    def test_visibility_root_price_assertion_allows_response_shape_evidence(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={"contracts": {"coverage": {"root_visibility_assertions_require_path_evidence": True}}},
            cases=[
                AuthoringCase(
                    id="contractor-detail-masks-price",
                    kind="api",
                    objective="Contractor detail read masks price.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/1")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=["response JSON exists", "response `price` = `null`"],
                    ),
                    metadata={"response_shape_evidence": "Serializer exposes root price for this endpoint."},
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_visibility_root_field_assertion_requires_path_evidence"
                for diagnostic in result.diagnostics
            )
        )

    def test_search_visibility_assertion_warns_without_non_empty_data_setup(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            cases=[
                AuthoringCase(
                    id="customer-search-masks-cost-price",
                    kind="api",
                    objective="Customer search results apply cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/search")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=["response JSON exists", "response `cost_price` = `null`"],
                    ),
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_collection_visibility_data_setup_unresolved"
                for diagnostic in result.diagnostics
            )
        )

    def test_contract_can_require_search_visibility_data_setup(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={"contracts": {"coverage": {"collection_visibility_requires_data_setup": True}}},
            cases=[
                AuthoringCase(
                    id="customer-search-masks-cost-price",
                    kind="api",
                    objective="Customer search results apply cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/search")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=["response JSON exists", "response `cost_price` = `null`"],
                    ),
                    metadata={
                        "coverage_claims": {
                            "visibility": {
                                "fields": ["cost_price"],
                                "response_paths": ["categories.0.positions.0.cost_price"],
                                "requires_non_empty_result": True,
                            }
                        }
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_collection_visibility_data_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_strict_search_visibility_data_setup_ignores_permission_only_setup(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={"contracts": {"coverage": {"collection_visibility_requires_data_setup": True}}},
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    operations={
                        "grant_partner_edit": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/price-lists/1/permissions/update"),
                            captures=["response.json.0.company_member_guid -> partner_company_member_guid"],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="customer-search-masks-cost-price",
                    kind="workflow",
                    objective="Customer search results apply cost_price masking.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="price_list_permission",
                            operation="grant_partner_edit",
                        )
                    ],
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/search")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=["response JSON exists", "response `cost_price` = `null`"],
                    ),
                    metadata={
                        "coverage_claims": {
                            "visibility": {
                                "fields": ["cost_price"],
                                "response_paths": ["categories.0.positions.0.cost_price"],
                                "requires_non_empty_result": True,
                            }
                        }
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_collection_visibility_data_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_strict_search_visibility_data_setup_rejects_non_empty_oracle_without_fixture_contract(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={"contracts": {"coverage": {"collection_visibility_requires_data_setup": True}}},
            cases=[
                AuthoringCase(
                    id="customer-search-masks-cost-price",
                    kind="api",
                    objective="Customer search results apply cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/search")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=[
                            "response JSON exists",
                            "response categories length >= 1",
                            "response `cost_price` = `null`",
                        ],
                    ),
                    metadata={
                        "coverage_claims": {
                            "visibility": {
                                "fields": ["cost_price"],
                                "response_paths": ["categories.0.positions.0.cost_price"],
                                "requires_non_empty_result": True,
                            }
                        }
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_collection_visibility_data_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_strict_search_visibility_data_setup_rejects_indexed_result_oracle_without_fixture_contract(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={"contracts": {"coverage": {"collection_visibility_requires_data_setup": True}}},
            cases=[
                AuthoringCase(
                    id="customer-search-masks-cost-price",
                    kind="api",
                    objective="Customer search results apply cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/search")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=[
                            "response JSON exists",
                            "response contains field `categories.0.positions.0.id`",
                            "response `cost_price` = `null`",
                        ],
                    ),
                    metadata={
                        "coverage_claims": {
                            "visibility": {
                                "fields": ["cost_price"],
                                "response_paths": ["categories.0.positions.0.cost_price"],
                                "requires_non_empty_result": True,
                            }
                        }
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_collection_visibility_data_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_strict_search_visibility_data_setup_rejects_contract_without_provenance(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={"contracts": {"coverage": {"collection_visibility_requires_data_setup": True}}},
            cases=[
                AuthoringCase(
                    id="customer-search-masks-cost-price",
                    kind="api",
                    objective="Customer search results apply cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/search")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=[
                            "response JSON exists",
                            "response contains field `categories.0.positions.0.id`",
                            "response `categories.0.positions.0.cost_price` = `null`",
                        ],
                    ),
                    metadata={
                        "coverage_claims": {
                            "visibility": {
                                "fields": ["cost_price"],
                                "response_paths": ["categories.0.positions.0.cost_price"],
                                "requires_non_empty_result": True,
                            }
                        },
                        "fixture_contract": {
                            "non_empty_paths": ["categories.0.positions.0.id"],
                        },
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_collection_visibility_data_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_visibility_indexed_response_path_requires_shape_evidence_even_with_fixture_contract(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list visibility.",
            scope=AuthoringScope(surface="price-list-permissions"),
            cases=[
                AuthoringCase(
                    id="customer-detail-masks-cost-price",
                    kind="api",
                    objective="Customer detail response applies cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/{{id}}")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=[
                            "response JSON exists",
                            "response contains field `positions_flat.0.id`",
                            "response `positions_flat.0.cost_price` = `null`",
                        ],
                    ),
                    metadata={
                        "coverage_claims": {
                            "visibility": {
                                "fields": ["cost_price"],
                                "response_paths": ["positions_flat.0.cost_price"],
                                "requires_non_empty_result": True,
                            }
                        },
                        "fixture_contract": {
                            "non_empty_paths": ["positions_flat.0.id"],
                            "source": "seeded price list fixture has at least one position.",
                        },
                    },
                )
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_visibility_response_path_evidence_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_strict_indexed_detail_visibility_requires_data_setup_or_provenance(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={"contracts": {"coverage": {"collection_visibility_requires_data_setup": True}}},
            cases=[
                AuthoringCase(
                    id="customer-detail-masks-cost-price",
                    kind="api",
                    objective="Customer detail response applies cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/{{id}}")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=[
                            "response JSON exists",
                            "response contains field `positions_flat.0.id`",
                            "response `positions_flat.0.cost_price` = `null`",
                        ],
                    ),
                    metadata={
                        "coverage_claims": {
                            "visibility": {
                                "fields": ["cost_price"],
                                "response_paths": ["positions_flat.0.cost_price"],
                                "requires_non_empty_result": True,
                            }
                        },
                        "fixture_contract": {
                            "non_empty_paths": ["positions_flat.0.id"],
                        },
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_collection_visibility_data_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_strict_search_visibility_data_setup_accepts_structured_data_contract(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="catalog-plan",
            project="code/demo",
            title="Catalog visibility",
            goal="Cover catalog visibility.",
            scope=AuthoringScope(surface="catalog-search"),
            metadata={"contracts": {"coverage": {"collection_visibility_requires_data_setup": True}}},
            cases=[
                AuthoringCase(
                    id="buyer-search-masks-cost-price",
                    kind="api",
                    objective="Buyer search results apply cost_price masking.",
                    state_change="read_only",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/api/catalog/search")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=[
                            "response JSON exists",
                            "response items length >= 1",
                            "response `items.0.cost_price` = `null`",
                        ],
                    ),
                    metadata={
                        "coverage_claims": {
                            "visibility": {
                                "fields": ["cost_price"],
                                "response_paths": ["items.0.cost_price"],
                                "requires_non_empty_result": True,
                            }
                        },
                        "data_contract": {
                            "non_empty_paths": ["items"],
                            "source": "env fixture CATALOG_SEARCH_QUERY returns at least one indexed item.",
                        },
                        "response_shape_evidence": "CatalogSearchSerializer exposes items.0.cost_price.",
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_collection_visibility_data_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_strict_search_visibility_data_setup_accepts_data_creating_setup(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            metadata={"contracts": {"coverage": {"collection_visibility_requires_data_setup": True}}},
            entities={
                "price_list_position": AuthoringEntitySpec(
                    operations={
                        "create_position": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/price-lists/1/positions/create"),
                            captures=["response.json.id -> position_id"],
                            expected_outcomes=["HTTP 201", "response contains field `id`"],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="customer-search-masks-cost-price",
                    kind="workflow",
                    objective="Customer search results apply cost_price masking.",
                    state_change="read_only",
                    setup=[
                        AuthoringSetupStep(
                            use_entity="price_list_position",
                            operation="create_position",
                        )
                    ],
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/price-lists/search")),
                    oracle=AuthoringOracle(
                        status_code=200,
                        business_checks=["response JSON exists", "response `cost_price` = `null`"],
                    ),
                    metadata={
                        "coverage_claims": {
                            "visibility": {
                                "fields": ["cost_price"],
                                "response_paths": ["categories.0.positions.0.cost_price"],
                                "requires_non_empty_result": True,
                                "source_ref": "serializers/search_result.py",
                                "evidence": "Search response groups matching positions under categories.0.positions.",
                            }
                        }
                    },
                ),
            ],
        )

        result = AuthoringPlanCompiler().validate(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(
            any(
                diagnostic.code == "authoring_collection_visibility_data_setup_required"
                for diagnostic in result.diagnostics
            )
        )

    def test_compile_merges_default_headers_into_setup_and_case_requests(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "internal_api_token = env:INTERNAL_API_TOKEN",
                    "generated_email = template:autotest@example.com",
                ],
                headers={
                    "X-Leadflow-Internal-Token": "{{internal_api_token}}",
                    "Content-Type": "application/json",
                }
            ),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "create": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users"),
                            request_headers={"X-Request-Source": "setup"},
                            request_body={"email": "{{generated_email}}"},
                            captures=["response.json.id -> user_id"],
                        ),
                        "verify_exists": AuthoringEntityOperation(
                            sql="SELECT id FROM users WHERE id = :user_id",
                            params={"user_id": "{{user_id}}"},
                            expected_outcomes=["one row exists"],
                        ),
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="get-user-success",
                    kind="workflow",
                    objective="Get created user",
                    state_change="none",
                    setup=[AuthoringSetupStep(use_entity="user", operation="create")],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users/{{user_id}}"),
                        headers={"Content-Type": "application/custom+json"},
                    ),
                    oracle=AuthoringOracle(status_code=200),
                ),
                AuthoringCase(
                    id="create-user-success",
                    kind="api",
                    objective="Create user successfully",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users"),
                        headers={"X-Request-Source": "case"},
                        body={"email": "{{generated_email}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> user_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_exists"),
                    ),
                ),
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        workflow_case = result.compiled_plan.planned_test_cases[0]
        self.assertEqual(
            workflow_case.workflow_steps[0].request_headers,
            {
                "X-Leadflow-Internal-Token": "{{internal_api_token}}",
                "Content-Type": "application/json",
                "X-Request-Source": "setup",
            },
        )
        self.assertEqual(
            workflow_case.workflow_steps[1].request_headers,
            {
                "X-Leadflow-Internal-Token": "{{internal_api_token}}",
                "Content-Type": "application/custom+json",
            },
        )
        api_case = result.compiled_plan.planned_test_cases[1]
        self.assertEqual(
            api_case.request_headers,
            {
                "X-Leadflow-Internal-Token": "{{internal_api_token}}",
                "Content-Type": "application/json",
                "X-Request-Source": "case",
            },
        )

    def test_compile_valid_authoring_plan_to_agent_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
  style: api-first
  include:
    - create user
    - get user
defaults:
  auth: bearer
entities:
  user:
    operations:
      create:
        route:
          method: POST
          path: /users
        request_body:
          email: "{{generated_email}}"
        oracle:
          status_code: 201
        captures:
          - response.json.id -> user_id
      verify_exists:
        sql: SELECT id FROM users WHERE id = :user_id
        params:
          user_id: "{{user_id}}"
        expected_outcomes:
          - one row exists
cases:
  - id: create-user-success
    kind: api
    objective: Create user successfully
    state_change: create
    execute:
      route:
        method: POST
        path: /users
      body:
        email: "{{generated_email}}"
    oracle:
      status_code: 201
      captures:
        - response.json.id -> user_id
      persisted_state:
        entity: user
        operation: verify_exists
  - id: get-user-success
    kind: workflow
    objective: Get created user
    state_change: none
    setup:
      - use_entity: user
        operation: create
    execute:
      route:
        method: GET
        path: /users/{{user_id}}
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().compile_file(path)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertIsNotNone(result.compiled_plan)
        compiled_plan = result.compiled_plan
        assert compiled_plan is not None
        self.assertEqual(compiled_plan.metadata["input_mode"], "authoring_plan")
        self.assertEqual(compiled_plan.planned_test_cases[0].route.endpoint_path, "/users")
        self.assertEqual(compiled_plan.planned_test_cases[0].db_verification.sql, "SELECT id FROM users WHERE id = :user_id")
        self.assertEqual(compiled_plan.planned_test_cases[1].kind, "workflow")
        self.assertEqual(compiled_plan.planned_test_cases[1].workflow_steps[0].route.endpoint_path, "/users")
        self.assertEqual(compiled_plan.planned_test_cases[1].workflow_steps[1].route.endpoint_path, "/users/{{user_id}}")

    def test_compile_propagates_first_class_scenario_variables(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=["run_suffix = generated:run_suffix"],
            ),
            cases=[
                AuthoringCase(
                    id="create-user-success",
                    kind="api",
                    objective="Create user successfully",
                    state_change="none",
                    scenario_variables=["internal_api_token = env:INTERNAL_API_TOKEN"],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                    ),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        self.assertEqual(result.compiled_plan.scenario_variables, ["run_suffix = generated:run_suffix"])
        self.assertEqual(
            result.compiled_plan.planned_test_cases[0].scenario_variables,
            ["internal_api_token = env:INTERNAL_API_TOKEN"],
        )

    def test_validate_file_blocks_yaml_map_defaults_scenario_variable_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
defaults:
  scenario_variables:
    - setup_display_name = template: Invalid Update {{run_suffix}}
cases:
  - id: get-users
    kind: api
    objective: List users.
    state_change: none
    execute:
      route:
        method: GET
        path: /users
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertIn(
            "authoring_scenario_variable_entry_invalid",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        diagnostic = next(
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_scenario_variable_entry_invalid"
        )
        self.assertEqual(diagnostic.details["field"], "defaults.scenario_variables[1]")
        self.assertEqual(diagnostic.details["entry_type"], "dict")

    def test_validate_file_blocks_yaml_map_case_scenario_variable_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
cases:
  - id: update-user
    kind: api
    objective: Update user.
    state_change: none
    scenario_variables:
      - submitted_display_name = template: Invalid Update {{run_suffix}}
    execute:
      route:
        method: PATCH
        path: /users/{{user_id}}
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostic = next(
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_scenario_variable_entry_invalid"
        )
        self.assertEqual(diagnostic.details["field"], "cases[1].scenario_variables[1]")
        self.assertEqual(diagnostic.details["owner"], "update-user")

    def test_validate_file_accepts_quoted_template_scenario_variable_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
defaults:
  scenario_variables:
    - "setup_display_name = template:Invalid Update {{run_suffix}}"
cases:
  - id: get-users
    kind: api
    objective: List users.
    state_change: none
    execute:
      route:
        method: GET
        path: /users
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(path)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        self.assertEqual(
            result.compiled_plan.scenario_variables,
            ["setup_display_name = template:Invalid Update {{run_suffix}}"],
        )

    def test_compile_db_check_promotes_db_expected_outcomes_to_case_level(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-schema",
            project="code/demo",
            title="Users schema",
            goal="Verify persisted users schema.",
            scope=AuthoringScope(surface="users-table"),
            entities={
                "user_schema": AuthoringEntitySpec(
                    operations={
                        "verify_ready": AuthoringEntityOperation(
                            sql="SELECT COUNT(*) AS column_count FROM information_schema.columns WHERE table_name = 'users'",
                            expected_outcomes=["one row exists", "`column_count` = `5`"],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="users-schema-ready",
                    kind="db-check",
                    objective="Verify users schema is ready.",
                    state_change="none",
                    oracle=AuthoringOracle(
                        persisted_state=AuthoringPersistedStateRef(entity="user_schema", operation="verify_ready"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        compiled_case = result.compiled_plan.planned_test_cases[0]
        self.assertEqual(compiled_case.kind, "db")
        self.assertEqual(compiled_case.expected_outcomes, ["one row exists", "`column_count` = `5`"])
        self.assertIsNotNone(compiled_case.db_verification)
        assert compiled_case.db_verification is not None
        self.assertEqual(compiled_case.db_verification.expected_outcomes, compiled_case.expected_outcomes)

    def test_compile_reports_unknown_entity_operation(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities: {}
cases:
  - id: get-user-success
    kind: workflow
    objective: Get created user
    state_change: none
    setup:
      - use_entity: user
        operation: create
    execute:
      route:
        method: GET
        path: /users/{{user_id}}
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().compile_file(path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_unknown_entity", codes)
        self.assertIn("authoring_setup_reference_unresolved", codes)

    def test_compile_blocks_unknown_state_change(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="archive-user",
                    kind="api",
                    objective="Archive user",
                    state_change="archive",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/users/1/archive")),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_unknown_state_change", codes)

    def test_load_normalizes_known_state_change_to_enum(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """
version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
cases:
- id: create-user
  kind: api
  objective: Create user.
  state_change: CREATE
  execute:
    route:
      method: POST
      path: /users
  oracle:
    status_code: 201
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().load(path)

        self.assertFalse(result.diagnostics)
        self.assertIsNotNone(result.authoring_plan)
        assert result.authoring_plan is not None
        self.assertEqual(result.authoring_plan.cases[0].state_change, AuthoringStateChange.CREATE)

    def test_load_blocks_unknown_state_change_before_compile(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "authoring-plan.yaml"
            path.write_text(
                """
version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
cases:
- id: create-user
  kind: api
  objective: Create user.
  state_change: create active user
  execute:
    route:
      method: POST
      path: /users
  oracle:
    status_code: 201
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_unknown_state_change", codes)
        diagnostic = next(
            diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_unknown_state_change"
        )
        self.assertEqual(diagnostic.details["field"], "cases[1].state_change")
        self.assertIn("create", diagnostic.details["allowed_values"])

    def test_compile_blocks_duplicate_case_ids(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="duplicate-case",
                    kind="api",
                    objective="Create user",
                    state_change="none",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/users/1")),
                    oracle=AuthoringOracle(status_code=200),
                ),
                AuthoringCase(
                    id="duplicate-case",
                    kind="api",
                    objective="Read user again",
                    state_change="none",
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/users/2")),
                    oracle=AuthoringOracle(status_code=200),
                ),
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        duplicate_diagnostics = [
            diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_duplicate_case_id"
        ]
        self.assertEqual(len(duplicate_diagnostics), 1)
        self.assertEqual(duplicate_diagnostics[0].details["first_case_index"], 1)
        self.assertEqual(duplicate_diagnostics[0].details["duplicate_case_index"], 2)

    def test_compile_blocks_setup_operation_with_unresolved_entity_id_field(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            entities={
                "user": AuthoringEntitySpec(
                    id_field="user_id",
                    operations={
                        "suspend": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users/{{user_id}}/suspend"),
                            oracle=AuthoringOracle(status_code=200),
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="suspend-user",
                    kind="workflow",
                    objective="Suspend user",
                    state_change="none",
                    setup=[AuthoringSetupStep(use_entity="user", operation="suspend")],
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/users")),
                    oracle=AuthoringOracle(status_code=200),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_setup_entity_id_field_unresolved", codes)

    def test_compile_allows_setup_operation_with_entity_id_field_from_declared_variable(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=["missing_user_id = generated:uuid"],
            ),
            entities={
                "missing_user": AuthoringEntitySpec(
                    id_field="missing_user_id",
                    operations={
                        "bind_generated_id": AuthoringEntityOperation(
                            sql="SELECT :missing_user_id AS missing_user_id",
                            params={"missing_user_id": "{{missing_user_id}}"},
                            expected_outcomes=["one row exists"],
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="get-missing-user",
                    kind="workflow",
                    objective="Read missing user",
                    state_change="none",
                    setup=[AuthoringSetupStep(use_entity="missing_user", operation="bind_generated_id")],
                    execute=AuthoringExecute(route=AuthoringRoute(method="GET", path="/users/{{missing_user_id}}")),
                    oracle=AuthoringOracle(status_code=404),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        compiled_case = result.compiled_plan.planned_test_cases[0]
        self.assertEqual(compiled_case.workflow_steps[0].params["missing_user_id"], "{{missing_user_id}}")
        self.assertEqual(compiled_case.workflow_steps[1].route.endpoint_path, "/users/{{missing_user_id}}")

    def test_compile_blocks_persisted_state_template_missing_entity_id_field(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            entities={
                "user": AuthoringEntitySpec(
                    id_field="user_id",
                    operations={
                        "verify_active": AuthoringEntityOperation(
                            sql="SELECT COUNT(*) AS row_count FROM users WHERE status = 'ACTIVE'",
                            expected_outcomes=["one row exists"],
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="create-user",
                    kind="api",
                    objective="Create user",
                    state_change="create",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/users")),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> user_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_active"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_persisted_state_id_field_missing", codes)

    def test_compile_allows_persisted_state_template_scoped_by_composite_key_fields(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permission overrides.",
            scope=AuthoringScope(surface="price-list-permissions"),
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    id_field="price_list_permission_id",
                    key_fields=["price_list_id", "partner_member_guid"],
                    operations={
                        "verify_partner_can_edit": AuthoringEntityOperation(
                            sql=(
                                "SELECT can_edit FROM price_list_permission "
                                "WHERE price_list_id = :price_list_id "
                                "AND partner_member_guid = :partner_member_guid"
                            ),
                            params={
                                "price_list_id": "{{price_list_id}}",
                                "partner_member_guid": "{{partner_member_guid}}",
                            },
                            expected_outcomes=["one row exists", "`can_edit` = `true`"],
                        )
                    },
                )
            },
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "price_list_id = env:PRICE_LIST_ID",
                    "partner_member_guid = literal:partner-member-guid",
                ]
            ),
            cases=[
                AuthoringCase(
                    id="grant-partner-edit",
                    kind="api",
                    objective="Grant partner edit access.",
                    state_change="read_only",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/price-lists/{{price_list_id}}/permissions")
                    ),
                    oracle=AuthoringOracle(
                        status_code=200,
                        persisted_state=AuthoringPersistedStateRef(
                            entity="price_list_permission",
                            operation="verify_partner_can_edit",
                        ),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertNotIn("authoring_persisted_state_id_field_missing", codes)
        assert result.compiled_plan is not None
        self.assertIsNotNone(result.compiled_plan.planned_test_cases[0].db_verification)

    def test_compile_blocks_persisted_state_template_missing_part_of_composite_key_fields(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list permission overrides.",
            scope=AuthoringScope(surface="price-list-permissions"),
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    id_field="price_list_permission_id",
                    key_fields=["price_list_id", "partner_member_guid"],
                    operations={
                        "verify_partner_can_edit": AuthoringEntityOperation(
                            sql="SELECT can_edit FROM price_list_permission WHERE price_list_id = :price_list_id",
                            params={"price_list_id": "{{price_list_id}}"},
                            expected_outcomes=["one row exists", "`can_edit` = `true`"],
                        )
                    },
                )
            },
            defaults=AuthoringDefaults(scenario_variables=["price_list_id = env:PRICE_LIST_ID"]),
            cases=[
                AuthoringCase(
                    id="grant-partner-edit",
                    kind="api",
                    objective="Grant partner edit access.",
                    state_change="read_only",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/price-lists/{{price_list_id}}/permissions")
                    ),
                    oracle=AuthoringOracle(
                        status_code=200,
                        persisted_state=AuthoringPersistedStateRef(
                            entity="price_list_permission",
                            operation="verify_partner_can_edit",
                        ),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_persisted_state_id_field_missing"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["key_fields"], ["price_list_id", "partner_member_guid"])

    def test_compile_blocks_persisted_state_template_mixing_id_and_entity_id_field(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="tenants-plan",
            project="code/demo",
            title="Tenants API",
            goal="Cover tenant API.",
            scope=AuthoringScope(surface="tenants-controller"),
            entities={
                "tenant": AuthoringEntitySpec(
                    id_field="tenant_id",
                    operations={
                        "verify_created": AuthoringEntityOperation(
                            sql="SELECT id, tenant_id FROM tenants WHERE id = :tenant_id",
                            params={"tenant_id": "{{tenant_id}}"},
                            expected_outcomes=[
                                "one row exists",
                                "`tenant_id` = `{{tenant_id}}`",
                            ],
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="create-tenant",
                    kind="api",
                    objective="Create tenant",
                    state_change="create",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/tenants")),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> tenant_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="tenant", operation="verify_created"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_persisted_state_id_field_semantic_mismatch", codes)

    def test_compile_blocks_create_persistence_that_uses_fixture_id_instead_of_captured_created_id(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list create permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "price_list_id = env:PRICE_LIST_ID",
                    "company_member_guid = env:PRICE_LIST_PARTNER_MEMBER_GUID",
                ]
            ),
            entities={
                "price_list_permission": AuthoringEntitySpec(
                    id_field="price_list_permission_id",
                    key_fields=["price_list_id", "company_member_guid"],
                    operations={
                        "verify_auto_edit": AuthoringEntityOperation(
                            sql=(
                                "SELECT can_edit FROM price_list_permission "
                                "WHERE price_list_id = :price_list_id "
                                "AND company_member_guid = :company_member_guid"
                            ),
                            params={
                                "price_list_id": "{{price_list_id}}",
                                "company_member_guid": "{{company_member_guid}}",
                            },
                            expected_outcomes=["one row exists", "`can_edit` = `true`"],
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-create-price-list",
                    kind="api",
                    objective="Partner creates a price list and receives auto edit.",
                    state_change="create",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/price-lists")),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> created_price_list_id"],
                        persisted_state=AuthoringPersistedStateRef(
                            entity="price_list_permission",
                            operation="verify_auto_edit",
                        ),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_created_entity_persistence_uses_fixture_id"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(
            diagnostics[0].details["fixture_scopes"],
            [{"created_capture": "created_price_list_id", "fixture_placeholder": "price_list_id"}],
        )

    def test_compile_allows_created_entity_persistence_scoped_by_captured_created_id(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list create permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            entities={
                "created_price_list": AuthoringEntitySpec(
                    id_field="created_price_list_id",
                    operations={
                        "verify_created": AuthoringEntityOperation(
                            sql="SELECT id FROM price_lists WHERE id = :created_price_list_id",
                            params={"created_price_list_id": "{{created_price_list_id}}"},
                            expected_outcomes=["one row exists"],
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-create-price-list",
                    kind="api",
                    objective="Partner creates a price list.",
                    state_change="create",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/price-lists")),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> created_price_list_id"],
                        persisted_state=AuthoringPersistedStateRef(
                            entity="created_price_list",
                            operation="verify_created",
                        ),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertNotIn("authoring_created_entity_persistence_uses_fixture_id", codes)

    def test_compile_blocks_created_entity_capture_overwriting_env_fixture_id(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="price-list-plan",
            project="code/demo",
            title="Price list permissions",
            goal="Cover price-list create permissions.",
            scope=AuthoringScope(surface="price-list-permissions"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                scenario_variables=["price_list_id = env:PRICE_LIST_ID"],
            ),
            entities={
                "price_list": AuthoringEntitySpec(
                    id_field="price_list_id",
                    operations={
                        "verify_created": AuthoringEntityOperation(
                            sql="SELECT id FROM price_lists WHERE id = :price_list_id",
                            params={"price_list_id": "{{price_list_id}}"},
                            expected_outcomes=["one row exists"],
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="partner-create-price-list",
                    kind="api",
                    objective="Partner creates a price list.",
                    state_change="create",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/price-lists")),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> price_list_id"],
                        persisted_state=AuthoringPersistedStateRef(
                            entity="price_list",
                            operation="verify_created",
                        ),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_created_entity_capture_overwrites_fixture_variable"
                for diagnostic in result.diagnostics
            )
        )

    def test_compile_blocks_created_entity_capture_overwriting_literal_fixture_guid(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="orders-plan",
            project="code/demo",
            title="Orders",
            goal="Cover order create.",
            scope=AuthoringScope(surface="orders"),
            defaults=AuthoringDefaults(
                environment="env/demo.env",
                scenario_variables=["order_guid = literal:fixture-order-guid"],
            ),
            entities={
                "order": AuthoringEntitySpec(
                    id_field="order_guid",
                    operations={
                        "verify_created": AuthoringEntityOperation(
                            sql="SELECT guid FROM orders WHERE guid = :order_guid",
                            params={"order_guid": "{{order_guid}}"},
                            expected_outcomes=["one row exists"],
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="create-order",
                    kind="api",
                    objective="Create an order.",
                    state_change="create",
                    execute=AuthoringExecute(route=AuthoringRoute(method="POST", path="/orders")),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.guid -> order_guid"],
                        persisted_state=AuthoringPersistedStateRef(entity="order", operation="verify_created"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(
                diagnostic.code == "authoring_created_entity_capture_overwrites_fixture_variable"
                for diagnostic in result.diagnostics
            )
        )

    def test_compile_allows_db_check_persisted_state_placeholders_from_declared_variables(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "run_suffix = generated:run_suffix",
                    "email_suffix = derived:run_suffix|lower",
                ],
            ),
            entities={
                "invalid_user": AuthoringEntitySpec(
                    operations={
                        "verify_invalid_creates_absent": AuthoringEntityOperation(
                            sql=(
                                "SELECT COUNT(*) AS invalid_user_count "
                                "FROM users "
                                "WHERE display_name LIKE 'AUTOTEST Invalid User ' || :run_suffix || '%' "
                                "OR email = 'autotest.invalid.' || :email_suffix || '@example.com'"
                            ),
                            params={
                                "run_suffix": "{{run_suffix}}",
                                "email_suffix": "{{email_suffix}}",
                            },
                            expected_outcomes=["one row exists", "`invalid_user_count` = `0`"],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="invalid-create-requests-do-not-persist",
                    kind="db-check",
                    objective="Invalid create requests do not persist users.",
                    state_change="none",
                    oracle=AuthoringOracle(
                        persisted_state=AuthoringPersistedStateRef(
                            entity="invalid_user",
                            operation="verify_invalid_creates_absent",
                        ),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        assert result.compiled_plan is not None
        compiled_case = result.compiled_plan.planned_test_cases[0]
        assert compiled_case.db_verification is not None
        self.assertEqual(compiled_case.kind, "db")
        self.assertEqual(compiled_case.db_verification.params["run_suffix"], "{{run_suffix}}")
        self.assertEqual(compiled_case.db_verification.params["email_suffix"], "{{email_suffix}}")

    def test_compile_warns_string_too_long_case_when_body_does_not_exceed_stated_boundary(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="update-user-name-too-long",
                    kind="api",
                    objective="Reject tenant names longer than 255 characters.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="PATCH", path="/users/1"),
                        body={"name": "A" * 255},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        mismatch_diagnostics = [
            diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_case_boundary_mismatch"
        ]
        self.assertEqual(len(mismatch_diagnostics), 1)
        self.assertEqual(mismatch_diagnostics[0].severity, DiagnosticSeverity.WARNING)
        self.assertEqual(mismatch_diagnostics[0].details["threshold"], 255)
        self.assertEqual(mismatch_diagnostics[0].details["actual_max_length"], 255)

    def test_compile_blocks_boundary_mismatch_when_strict_contract_is_enabled(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            metadata={"contracts": {"boundary": {"require_literal_boundary_match": True}}},
            cases=[
                AuthoringCase(
                    id="update-user-name-too-long",
                    kind="api",
                    objective="Reject tenant names longer than 255 characters.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="PATCH", path="/users/1"),
                        body={"name": "A" * 255},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        mismatch = next(
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_case_boundary_contract_mismatch"
        )
        self.assertEqual(mismatch.severity, DiagnosticSeverity.ERROR)
        self.assertEqual(mismatch.details["threshold"], 255)

    def test_compile_treats_quoted_false_boundary_contract_as_disabled(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            metadata={"contracts": {"boundary": {"require_literal_boundary_match": "false"}}},
            cases=[
                AuthoringCase(
                    id="update-user-name-too-long",
                    kind="api",
                    objective="Reject tenant names longer than 255 characters.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="PATCH", path="/users/1"),
                        body={"name": "A" * 255},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertTrue(any(diagnostic.code == "authoring_case_boundary_mismatch" for diagnostic in result.diagnostics))
        self.assertFalse(
            any(diagnostic.code == "authoring_case_boundary_contract_mismatch" for diagnostic in result.diagnostics)
        )

    def test_compile_treats_quoted_true_boundary_contract_as_enabled(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            metadata={"contracts": {"boundary": {"require_literal_boundary_match": "true"}}},
            cases=[
                AuthoringCase(
                    id="update-user-name-too-long",
                    kind="api",
                    objective="Reject tenant names longer than 255 characters.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="PATCH", path="/users/1"),
                        body={"name": "A" * 255},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(diagnostic.code == "authoring_case_boundary_contract_mismatch" for diagnostic in result.diagnostics)
        )

    def test_compile_allows_string_too_long_case_when_body_exceeds_stated_boundary(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="update-user-name-too-long",
                    kind="api",
                    objective="Reject tenant names longer than 255 characters.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="PATCH", path="/users/1"),
                        body={"name": "A" * 256},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(any(diagnostic.code == "authoring_case_boundary_mismatch" for diagnostic in result.diagnostics))

    def test_compile_warns_numeric_greater_than_case_when_param_does_not_exceed_threshold(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-limit-over-max",
                    kind="api",
                    objective="Reject list requests with limit greater than 100.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 100, "offset": 0},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        mismatch = next(diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_case_boundary_mismatch")
        self.assertEqual(mismatch.severity, DiagnosticSeverity.WARNING)
        self.assertEqual(mismatch.details["rule"], "greater_than")
        self.assertEqual(mismatch.details["field"], "limit")
        self.assertEqual(mismatch.details["threshold"], 100)
        self.assertEqual(mismatch.details["actual_values"], [100])

    def test_compile_allows_numeric_greater_than_case_when_param_exceeds_threshold(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-limit-over-max",
                    kind="api",
                    objective="Reject list requests with limit greater than 100.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 101, "offset": 0},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(any(diagnostic.code == "authoring_case_boundary_mismatch" for diagnostic in result.diagnostics))

    def test_compile_warns_negative_offset_case_when_param_is_not_negative(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-negative-offset",
                    kind="api",
                    objective="Reject list request with negative offset.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 10, "offset": 0},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        mismatch = next(diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_case_boundary_mismatch")
        self.assertEqual(mismatch.severity, DiagnosticSeverity.WARNING)
        self.assertEqual(mismatch.details["rule"], "negative")
        self.assertEqual(mismatch.details["field"], "offset")
        self.assertEqual(mismatch.details["actual_values"], [0])

    def test_compile_allows_negative_offset_case_when_param_is_negative(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-negative-offset",
                    kind="api",
                    objective="Reject list request with negative offset.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 10, "offset": -1},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(any(diagnostic.code == "authoring_case_boundary_mismatch" for diagnostic in result.diagnostics))

    def test_compile_warns_zero_limit_case_when_param_is_not_zero(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-zero-limit",
                    kind="api",
                    objective="Reject list request with zero limit.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 1, "offset": 0},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        mismatch = next(diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_case_boundary_mismatch")
        self.assertEqual(mismatch.severity, DiagnosticSeverity.WARNING)
        self.assertEqual(mismatch.details["rule"], "zero")
        self.assertEqual(mismatch.details["field"], "limit")
        self.assertEqual(mismatch.details["actual_values"], [1])

    def test_compile_allows_zero_limit_case_when_param_is_zero(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            cases=[
                AuthoringCase(
                    id="list-users-zero-limit",
                    kind="api",
                    objective="Reject list request with zero limit.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="GET", path="/users"),
                        params={"limit": 0, "offset": 0},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(any(diagnostic.code == "authoring_case_boundary_mismatch" for diagnostic in result.diagnostics))

    def test_compile_warns_when_email_expectation_reuses_non_lowercase_request_placeholder(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "run_suffix = generated:run_suffix",
                    "submitted_email = template:AUTOTEST.User.{{run_suffix}}@Example.COM",
                ]
            ),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "verify_exists": AuthoringEntityOperation(
                            sql="SELECT email FROM users WHERE id = :user_id",
                            params={"user_id": "{{user_id}}"},
                            expected_outcomes=["one row exists", "`email` = `{{submitted_email}}`"],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="create-user-success",
                    kind="api",
                    objective="Create user successfully.",
                    state_change="create",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users"),
                        body={"email": "{{submitted_email}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        business_checks=["response `email` = `{{submitted_email}}`"],
                        captures=["response.json.id -> user_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_exists"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        warnings = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_expected_value_case_ambiguous"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(str(warnings[0].severity).lower(), "warning")
        self.assertEqual(warnings[0].details["variables"], ["submitted_email"])

    def test_compile_skips_email_case_warning_when_expected_variable_is_lowercased(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "run_suffix = generated:run_suffix",
                    "email_suffix = derived:run_suffix|lower",
                    "submitted_email = template:AUTOTEST.User.{{email_suffix}}@Example.COM",
                    "expected_email = derived:submitted_email|lower",
                ]
            ),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "verify_exists": AuthoringEntityOperation(
                            sql="SELECT email FROM users WHERE id = :user_id",
                            params={"user_id": "{{user_id}}"},
                            expected_outcomes=["one row exists", "`email` = `{{expected_email}}`"],
                        )
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="create-user-success",
                    kind="api",
                    objective="Create user successfully.",
                    state_change="create",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users"),
                        body={"email": "{{submitted_email}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        business_checks=["response `email` = `{{expected_email}}`"],
                        captures=["response.json.id -> user_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_exists"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(any(diagnostic.code == "authoring_expected_value_case_ambiguous" for diagnostic in result.diagnostics))

    def test_compile_blocks_telegram_subject_from_nonnumeric_generated_suffix(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="identity-plan",
            project="code/demo",
            title="Identity API",
            goal="Cover identity API.",
            scope=AuthoringScope(surface="identity-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "run_suffix = generated:run_suffix",
                    "telegram_subject = template:700{{run_suffix}}",
                ]
            ),
            entities={"user_identity": _identity_entity_with_numeric_subject_constraint()},
            cases=[
                AuthoringCase(
                    id="link-telegram",
                    kind="api",
                    objective="Link TELEGRAM identity.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users/u1/identities"),
                        body={"provider": "TELEGRAM", "subject": "{{telegram_subject}}"},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(any(diagnostic.code == "authoring_request_constraint_unsatisfied" for diagnostic in result.diagnostics))

    def test_compile_does_not_apply_numeric_request_rule_without_declarative_constraint(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="identity-plan",
            project="code/demo",
            title="Identity API",
            goal="Cover identity API.",
            scope=AuthoringScope(surface="identity-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "run_suffix = generated:run_suffix",
                    "telegram_subject = template:700{{run_suffix}}",
                ]
            ),
            cases=[
                AuthoringCase(
                    id="link-telegram",
                    kind="api",
                    objective="Link TELEGRAM identity.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users/u1/identities"),
                        body={"provider": "TELEGRAM", "subject": "{{telegram_subject}}"},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertFalse(any(diagnostic.code == "authoring_request_constraint_unsatisfied" for diagnostic in result.diagnostics))

    def test_compile_allows_telegram_subject_from_numeric_generated_suffix(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="identity-plan",
            project="code/demo",
            title="Identity API",
            goal="Cover identity API.",
            scope=AuthoringScope(surface="identity-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "numeric_suffix = generated:numeric_suffix",
                    "telegram_subject = template:700{{numeric_suffix}}",
                ]
            ),
            entities={"user_identity": _identity_entity_with_numeric_subject_constraint()},
            cases=[
                AuthoringCase(
                    id="link-telegram",
                    kind="api",
                    objective="Link TELEGRAM identity.",
                    state_change="none",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users/u1/identities"),
                        body={"provider": "TELEGRAM", "subject": "{{telegram_subject}}"},
                    ),
                    oracle=AuthoringOracle(status_code=201),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertFalse(any(diagnostic.code == "authoring_request_constraint_unsatisfied" for diagnostic in result.diagnostics))

    def test_compile_blocks_numeric_placeholder_for_string_like_db_expectation_without_quotes(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="identity-plan",
            project="code/demo",
            title="Identity API",
            goal="Cover identity API.",
            scope=AuthoringScope(surface="identity-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "numeric_suffix = generated:numeric_suffix",
                    "telegram_subject = template:700{{numeric_suffix}}",
                ]
            ),
            entities={
                "user_identity": AuthoringEntitySpec(
                    id_field="identity_id",
                    operations={
                        "verify_telegram": AuthoringEntityOperation(
                            sql="SELECT subject FROM user_identities WHERE id = :identity_id",
                            params={"identity_id": "{{identity_id}}"},
                            expected_outcomes=["one row exists", "`subject` = `{{telegram_subject}}`"],
                            column_types={"subject": "string"},
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="link-telegram",
                    kind="api",
                    objective="Link TELEGRAM identity.",
                    state_change="create",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users/u1/identities"),
                        body={"provider": "TELEGRAM", "subject": "{{telegram_subject}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> identity_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user_identity", operation="verify_telegram"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        self.assertTrue(
            any(diagnostic.code == "authoring_db_string_placeholder_requires_quotes" for diagnostic in result.diagnostics)
        )

    def test_compile_allows_numeric_placeholder_for_string_like_db_expectation_when_quoted(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="identity-plan",
            project="code/demo",
            title="Identity API",
            goal="Cover identity API.",
            scope=AuthoringScope(surface="identity-controller"),
            defaults=AuthoringDefaults(
                scenario_variables=[
                    "numeric_suffix = generated:numeric_suffix",
                    "telegram_subject = template:700{{numeric_suffix}}",
                ]
            ),
            entities={
                "user_identity": AuthoringEntitySpec(
                    id_field="identity_id",
                    operations={
                        "verify_telegram": AuthoringEntityOperation(
                            sql="SELECT subject FROM user_identities WHERE id = :identity_id",
                            params={"identity_id": "{{identity_id}}"},
                            expected_outcomes=["one row exists", '`subject` = `"{{telegram_subject}}"`'],
                            column_types={"subject": "string"},
                        )
                    },
                )
            },
            cases=[
                AuthoringCase(
                    id="link-telegram",
                    kind="api",
                    objective="Link TELEGRAM identity.",
                    state_change="create",
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users/u1/identities"),
                        body={"provider": "TELEGRAM", "subject": "{{telegram_subject}}"},
                    ),
                    oracle=AuthoringOracle(
                        status_code=201,
                        captures=["response.json.id -> identity_id"],
                        persisted_state=AuthoringPersistedStateRef(entity="user_identity", operation="verify_telegram"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertFalse(
            any(diagnostic.code == "authoring_db_string_placeholder_requires_quotes" for diagnostic in result.diagnostics)
        )

    def test_compile_warns_when_activate_success_setup_ends_archived(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            entities={
                "user": AuthoringEntitySpec(
                    id_field="user_id",
                    operations={
                        "create": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users"),
                            captures=["response.json.id -> user_id"],
                        ),
                        "archive": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users/{{user_id}}/archive"),
                        ),
                        "verify_active": AuthoringEntityOperation(
                            sql="SELECT status FROM users WHERE id = :user_id",
                            params={"user_id": "{{user_id}}"},
                            expected_outcomes=["one row exists", "`status` = `ACTIVE`"],
                        ),
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="activate-user-success",
                    kind="workflow",
                    title="Activate suspended user",
                    objective="Activate a suspended user successfully.",
                    state_change="none",
                    setup=[
                        AuthoringSetupStep(use_entity="user", operation="create"),
                        AuthoringSetupStep(use_entity="user", operation="archive"),
                    ],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users/{{user_id}}/activate"),
                    ),
                    oracle=AuthoringOracle(
                        status_code=200,
                        persisted_state=AuthoringPersistedStateRef(entity="user", operation="verify_active"),
                    ),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        warnings = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_workflow_setup_state_mismatch"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].details["expected_state"], "suspended")
        self.assertEqual(warnings[0].details["actual_state"], "archived")

    def test_compile_warns_when_archived_user_case_setup_is_only_suspended(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "create": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users"),
                            captures=["response.json.id -> user_id"],
                        ),
                        "suspend": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users/{{user_id}}/suspend"),
                        ),
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="update-archived-user-bad-request",
                    kind="workflow",
                    title="Reject archived user update",
                    objective="Reject profile update for archived user.",
                    state_change="none",
                    setup=[
                        AuthoringSetupStep(use_entity="user", operation="create"),
                        AuthoringSetupStep(use_entity="user", operation="suspend"),
                    ],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="PATCH", path="/users/{{user_id}}"),
                        body={"displayName": "Updated"},
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        warnings = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_workflow_setup_state_mismatch"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].details["expected_state"], "archived")
        self.assertEqual(warnings[0].details["actual_state"], "suspended")

    def test_compile_warns_when_same_state_lifecycle_behavior_is_only_inferred(self) -> None:
        plan = AuthoringPlan(
            version=1,
            source_id="users-plan",
            project="code/demo",
            title="Users API",
            goal="Cover users API.",
            scope=AuthoringScope(surface="users-controller"),
            entities={
                "user": AuthoringEntitySpec(
                    operations={
                        "create": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users"),
                            captures=["response.json.id -> user_id"],
                        ),
                        "archive": AuthoringEntityOperation(
                            route=AuthoringRoute(method="POST", path="/users/{{user_id}}/archive"),
                        ),
                    }
                )
            },
            cases=[
                AuthoringCase(
                    id="archive-archived-user",
                    kind="workflow",
                    title="Reject archiving archived user",
                    objective="Verify archive for archived user is handled correctly.",
                    state_change="none",
                    setup=[
                        AuthoringSetupStep(use_entity="user", operation="create"),
                        AuthoringSetupStep(use_entity="user", operation="archive"),
                    ],
                    execute=AuthoringExecute(
                        route=AuthoringRoute(method="POST", path="/users/{{user_id}}/archive"),
                    ),
                    oracle=AuthoringOracle(status_code=400),
                )
            ],
        )

        result = AuthoringPlanCompiler().compile(plan)

        self.assertEqual(result.status, StepStatus.PASS)
        warnings = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_same_state_lifecycle_contract_unconfirmed"
        ]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].details["actual_state"], "archived")
        self.assertEqual(warnings[0].details["target_state"], "archived")

    def test_compile_file_blocks_when_authored_entity_is_missing_from_entity_inventory(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0001"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: account
    id_field: user_id
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations: []
routes:
  - method: GET
    path: /users/{{user_id}}
    success_status: 200
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations: {}
cases:
  - id: get-user
    kind: api
    objective: Get user.
    state_change: none
    execute:
      route:
        method: GET
        path: /users/{{user_id}}
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().compile_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_stage_inventory_entity_mismatch", codes)

    def test_compile_file_blocks_when_route_status_disagrees_with_operation_inventory(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0002"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create
    effect_state: ACTIVE
routes:
  - method: POST
    path: /users
    success_status: 201
    failure_statuses: [400]
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations:
      create:
        route:
          method: POST
          path: /users
cases:
  - id: create-user
    kind: api
    objective: Create user.
    state_change: none
    execute:
      route:
        method: POST
        path: /users
    oracle:
      status_code: 200
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_stage_inventory_status_mismatch"]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["inventory_success_status"], 201)
        self.assertEqual(diagnostics[0].details["authored_status"], 200)

    def test_compile_file_matches_route_inventory_by_placeholder_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0008"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations: []
routes:
  - method: GET
    path: /users/{{user_id}}
    success_status: 200
    failure_statuses: [404]
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations: {}
cases:
  - id: get-missing-user
    kind: api
    objective: Return not found for a missing user.
    state_change: none
    scenario_variables:
      - "missing_user_id = literal:00000000-0000-0000-0000-000000000000"
    execute:
      route:
        method: GET
        path: /users/{{missing_user_id}}
    oracle:
      status_code: 404
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertNotIn(
            "authoring_stage_inventory_route_mismatch",
            {diagnostic.code for diagnostic in result.diagnostics},
        )

    def test_compile_file_blocks_when_workflow_setup_state_disagrees_with_inventory_precondition(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0003"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    states: [ACTIVE, SUSPENDED, ARCHIVED]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create
    effect_state: ACTIVE
    captures:
      - response.json.id -> user_id
  - entity: user
    operation: archive
    effect_state: ARCHIVED
routes:
  - method: POST
    path: /users/{{user_id}}/activate
    success_status: 200
    failure_statuses: [400, 404]
    precondition_state: SUSPENDED
db_verifications:
  - entity: user
    operation: verify_active
    scoped_by: user_id
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations:
      create:
        route:
          method: POST
          path: /users
        captures:
          - response.json.id -> user_id
      archive:
        route:
          method: POST
          path: /users/{{user_id}}/archive
      verify_active:
        sql: SELECT status FROM users WHERE id = :user_id
        params:
          user_id: "{{user_id}}"
        expected_outcomes:
          - one row exists
cases:
  - id: activate-user
    kind: workflow
    title: Activate suspended user
    objective: Activate a suspended user successfully.
    state_change: none
    setup:
      - use_entity: user
        operation: create
      - use_entity: user
        operation: archive
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/activate
    oracle:
      status_code: 200
      persisted_state:
        entity: user
        operation: verify_active
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().compile_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "authoring_stage_inventory_state_mismatch"]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["expected_state"], "suspended")
        self.assertEqual(diagnostics[0].details["actual_state"], "archived")

    def test_compile_file_allows_declared_failure_state_without_clearing_success_precondition(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0009"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    states: [ACTIVE, SUSPENDED, ARCHIVED]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create
    effect_state: ACTIVE
    captures:
      - response.json.id -> user_id
  - entity: user
    operation: archive
    effect_state: ARCHIVED
routes:
  - method: POST
    path: /users/{{user_id}}/activate
    success_status: 200
    failure_statuses: [400, 404]
    precondition_state: SUSPENDED
db_verifications:
  - entity: user
    operation: verify_archived
    scoped_by: user_id
    sql: SELECT status FROM users WHERE id = :user_id
    params:
      user_id: "{{user_id}}"
    expected_outcomes:
      - one row exists
      - "`status` = `ARCHIVED`"
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations:
      create:
        route:
          method: POST
          path: /users
        captures:
          - response.json.id -> user_id
      archive:
        route:
          method: POST
          path: /users/{{user_id}}/archive
      verify_archived:
        sql: SELECT status FROM users WHERE id = :user_id
        params:
          user_id: "{{user_id}}"
        expected_outcomes:
          - one row exists
          - "`status` = `ARCHIVED`"
cases:
  - id: activate-archived-user-rejected
    kind: workflow
    title: Reject activating archived user
    objective: Reject activation for an archived user.
    state_change: none
    setup:
      - use_entity: user
        operation: create
      - use_entity: user
        operation: archive
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/activate
    oracle:
      status_code: 400
      persisted_state:
        entity: user
        operation: verify_archived
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertNotIn(
            "authoring_stage_inventory_state_mismatch",
            {diagnostic.code for diagnostic in result.diagnostics},
        )

    def test_compile_file_warns_when_same_state_lifecycle_contract_is_missing_from_inventory(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0004"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    states: [ACTIVE, SUSPENDED, ARCHIVED]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create
    effect_state: ACTIVE
    captures:
      - response.json.id -> user_id
  - entity: user
    operation: archive
    effect_state: ARCHIVED
routes:
  - method: POST
    path: /users/{{user_id}}/archive
    success_status: 200
    failure_statuses: [400, 404]
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations:
      create:
        route:
          method: POST
          path: /users
        captures:
          - response.json.id -> user_id
      archive:
        route:
          method: POST
          path: /users/{{user_id}}/archive
cases:
  - id: archive-archived-user
    kind: workflow
    title: Reject archiving archived user
    objective: Reject archiving archived user.
    state_change: none
    setup:
      - use_entity: user
        operation: create
      - use_entity: user
        operation: archive
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/archive
    oracle:
      status_code: 400
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.PASS)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_stage_inventory_same_state_behavior_unconfirmed"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].severity, DiagnosticSeverity.WARNING)
        self.assertIn("same_state_behavior", diagnostics[0].details["missing_fields"])
        self.assertIn("same_state_status", diagnostics[0].details["missing_fields"])

    def test_compile_file_blocks_missing_same_state_lifecycle_contract_when_required(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0012"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    states: [ACTIVE, SUSPENDED, ARCHIVED]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create
    effect_state: ACTIVE
    captures:
      - response.json.id -> user_id
  - entity: user
    operation: archive
    effect_state: ARCHIVED
routes:
  - method: POST
    path: /users/{{user_id}}/archive
    success_status: 200
    failure_statuses: [400, 404]
    same_state_contract_required: true
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations:
      create:
        route:
          method: POST
          path: /users
        captures:
          - response.json.id -> user_id
      archive:
        route:
          method: POST
          path: /users/{{user_id}}/archive
cases:
  - id: archive-archived-user
    kind: workflow
    title: Reject archiving archived user
    objective: Reject archiving archived user.
    state_change: none
    setup:
      - use_entity: user
        operation: create
      - use_entity: user
        operation: archive
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/archive
    oracle:
      status_code: 400
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_stage_inventory_same_state_behavior_required"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].severity, DiagnosticSeverity.ERROR)
        self.assertIn("same_state_behavior", diagnostics[0].details["missing_fields"])
        self.assertIn("same_state_status", diagnostics[0].details["missing_fields"])

    def test_compile_file_treats_quoted_false_same_state_contract_required_as_disabled(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0013"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    states: [ACTIVE, SUSPENDED, ARCHIVED]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create
    effect_state: ACTIVE
    captures:
      - response.json.id -> user_id
  - entity: user
    operation: archive
    effect_state: ARCHIVED
routes:
  - method: POST
    path: /users/{{user_id}}/archive
    success_status: 200
    failure_statuses: [400, 404]
    same_state_contract_required: "false"
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations:
      create:
        route:
          method: POST
          path: /users
        captures:
          - response.json.id -> user_id
      archive:
        route:
          method: POST
          path: /users/{{user_id}}/archive
cases:
  - id: archive-archived-user
    kind: workflow
    title: Reject archiving archived user
    objective: Reject archiving archived user.
    state_change: none
    setup:
      - use_entity: user
        operation: create
      - use_entity: user
        operation: archive
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/archive
    oracle:
      status_code: 400
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.PASS)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertIn("authoring_stage_inventory_same_state_behavior_unconfirmed", codes)
        self.assertNotIn("authoring_stage_inventory_same_state_behavior_required", codes)

    def test_compile_file_blocks_when_same_state_lifecycle_status_conflicts_with_inventory(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0005"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    states: [ACTIVE, SUSPENDED, ARCHIVED]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create
    effect_state: ACTIVE
    captures:
      - response.json.id -> user_id
  - entity: user
    operation: archive
    effect_state: ARCHIVED
routes:
  - method: POST
    path: /users/{{user_id}}/archive
    success_status: 200
    failure_statuses: [400, 404]
    target_state: ARCHIVED
    same_state_behavior: idempotent_success
    same_state_status: 200
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations:
      create:
        route:
          method: POST
          path: /users
        captures:
          - response.json.id -> user_id
      archive:
        route:
          method: POST
          path: /users/{{user_id}}/archive
cases:
  - id: archive-archived-user
    kind: workflow
    title: Reject archiving archived user
    objective: Reject archiving archived user.
    state_change: none
    setup:
      - use_entity: user
        operation: create
      - use_entity: user
        operation: archive
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/archive
    oracle:
      status_code: 400
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_stage_inventory_same_state_mismatch"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["inventory_same_state_status"], 200)
        self.assertEqual(diagnostics[0].details["authored_status"], 400)

    def test_compile_file_blocks_idempotent_same_state_case_without_persisted_state(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0006"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    states: [ACTIVE, SUSPENDED, ARCHIVED]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create
    effect_state: ACTIVE
  - entity: user
    operation: archive
    effect_state: ARCHIVED
routes:
  - method: POST
    path: /users/{{user_id}}/archive
    success_status: 200
    failure_statuses: [400, 404]
    target_state: ARCHIVED
    same_state_behavior: idempotent_success
    same_state_status: 200
    same_state_evidence: domain User.archive no-ops when already archived
db_verifications:
  - entity: user
    operation: verify_archived
    scoped_by: user_id
    sql: SELECT status FROM users WHERE id = :user_id
    params:
      user_id: "{{user_id}}"
    expected_outcomes:
      - one row exists
      - "`status` = `ARCHIVED`"
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations:
      create:
        route:
          method: POST
          path: /users
      archive:
        route:
          method: POST
          path: /users/{{user_id}}/archive
cases:
  - id: archive-archived-user-idempotent
    kind: workflow
    title: Re-archive archived user idempotently
    objective: Verify archiving an already archived user is idempotent.
    state_change: none
    setup:
      - use_entity: user
        operation: create
      - use_entity: user
        operation: archive
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/archive
    oracle:
      status_code: 200
      business_checks:
        - response JSON exists
        - response `status` = `ARCHIVED`
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_stage_inventory_idempotency_persistence_missing"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["same_state_behavior"], "idempotent_success")
        self.assertEqual(diagnostics[0].details["same_state_status"], 200)

    def test_compile_file_allows_inventory_backed_same_state_reject_with_success_precondition(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0007"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    states: [ACTIVE, SUSPENDED]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create_active
    effect_state: ACTIVE
    captures:
      - response.json.id -> user_id
routes:
  - method: POST
    path: /users/{{user_id}}/activate
    success_status: 200
    failure_statuses: [400, 404]
    precondition_state: SUSPENDED
    target_state: ACTIVE
    same_state_behavior: reject
    same_state_status: 400
    same_state_evidence: ActivateUserHandler rejects users whose status is not SUSPENDED before calling User.activate.
db_verifications: []
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations:
      create_active:
        route:
          method: POST
          path: /users
        captures:
          - response.json.id -> user_id
cases:
  - id: activate-active-user-rejected
    kind: workflow
    title: Activate active user rejected
    objective: Reject activation when the user is already ACTIVE.
    state_change: none
    setup:
      - use_entity: user
        operation: create_active
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/activate
    oracle:
      status_code: 400
      business_checks:
        - HTTP 400
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertNotIn(
            "authoring_stage_inventory_state_mismatch",
            {diagnostic.code for diagnostic in result.diagnostics},
        )
        self.assertNotIn(
            "authoring_same_state_lifecycle_contract_unconfirmed",
            {diagnostic.code for diagnostic in result.diagnostics},
        )

    def test_compile_file_allows_multiple_success_precondition_states(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0010"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entities:
  - name: user
    id_field: user_id
    states: [ACTIVE, SUSPENDED, ARCHIVED]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: users-plan
project: code/demo
surface: users-controller
entity_operations:
  - entity: user
    operation: create_active
    effect_state: ACTIVE
    captures:
      - response.json.id -> user_id
  - entity: user
    operation: suspend
    effect_state: SUSPENDED
routes:
  - method: POST
    path: /users/{{user_id}}/archive
    success_status: 200
    failure_statuses: [400, 404]
    precondition_state: [ACTIVE, SUSPENDED]
    target_state: ARCHIVED
db_verifications:
  - entity: user
    operation: verify_archived
    scoped_by: user_id
    sql: SELECT status FROM users WHERE id = :user_id
    params:
      user_id: "{{user_id}}"
    expected_outcomes:
      - one row exists
      - "`status` = `ARCHIVED`"
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: users-plan
project: code/demo
title: Users API
goal: Cover users API.
scope:
  surface: users-controller
entities:
  user:
    id_field: user_id
    operations:
      create_active:
        route:
          method: POST
          path: /users
        captures:
          - response.json.id -> user_id
      suspend:
        route:
          method: POST
          path: /users/{{user_id}}/suspend
      verify_archived:
        sql: SELECT status FROM users WHERE id = :user_id
        params:
          user_id: "{{user_id}}"
        expected_outcomes:
          - one row exists
          - "`status` = `ARCHIVED`"
cases:
  - id: archive-suspended-user
    kind: workflow
    title: Archive suspended user
    objective: Archive succeeds when the user is suspended.
    state_change: mutate
    setup:
      - use_entity: user
        operation: create_active
      - use_entity: user
        operation: suspend
    execute:
      route:
        method: POST
        path: /users/{{user_id}}/archive
    oracle:
      status_code: 200
      persisted_state:
        entity: user
        operation: verify_archived
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertNotIn(
            "authoring_stage_inventory_state_mismatch",
            {diagnostic.code for diagnostic in result.diagnostics},
        )

    def test_compile_file_uses_route_entity_for_workflow_setup_state(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0011"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: price-list-plan
project: code/demo
surface: price-list-permissions
entities:
  - name: price_list
    id_field: price_list_id
    states: [visible, hidden]
  - name: price_list_permission
    id_field: price_list_permission_id
    key_fields: [price_list_id, partner_member_guid]
    states: [edit_allowed, edit_denied]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: price-list-plan
project: code/demo
surface: price-list-permissions
entity_operations:
  - entity: price_list
    operation: create_visible
    effect_state: visible
    captures:
      - response.json.id -> price_list_id
  - entity: price_list_permission
    operation: revoke_partner_edit
    effect_state: edit_denied
routes:
  - method: POST
    path: /api/price_list/{{price_list_id}}/update/
    success_status: 200
    failure_statuses: [400, 401, 403, 404]
    precondition_state: visible
db_verifications:
  - entity: price_list
    operation: verify_visible
    scoped_by: price_list_id
    sql: SELECT id FROM price_list WHERE id = :price_list_id
    params:
      price_list_id: "{{price_list_id}}"
    expected_outcomes:
      - one row exists
  - entity: price_list_permission
    operation: verify_partner_edit_denied
    scoped_by: [price_list_id, partner_member_guid]
    sql: SELECT can_edit FROM price_list_permission WHERE price_list_id = :price_list_id AND partner_member_guid = :partner_member_guid
    params:
      price_list_id: "{{price_list_id}}"
      partner_member_guid: "{{partner_member_guid}}"
    expected_outcomes:
      - one row exists
      - "`can_edit` = `false`"
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: price-list-plan
project: code/demo
title: Price list permissions
goal: Cover price list permissions.
scope:
  surface: price-list-permissions
entities:
  price_list:
    id_field: price_list_id
    operations:
      create_visible:
        route:
          method: POST
          path: /api/price_list/create/
        captures:
          - response.json.id -> price_list_id
      verify_visible:
        sql: SELECT id FROM price_list WHERE id = :price_list_id
        params:
          price_list_id: "{{price_list_id}}"
        expected_outcomes:
          - one row exists
  price_list_permission:
    id_field: price_list_permission_id
    operations:
      revoke_partner_edit:
        route:
          method: POST
          path: /api/price_list/{{price_list_id}}/permissions/update/
      verify_partner_edit_denied:
        sql: SELECT can_edit FROM price_list_permission WHERE price_list_id = :price_list_id AND partner_member_guid = :partner_member_guid
        params:
          price_list_id: "{{price_list_id}}"
          partner_member_guid: "{{partner_member_guid}}"
        expected_outcomes:
          - one row exists
          - "`can_edit` = `false`"
cases:
  - id: update-visible-price-list-with-denied-edit-setup
    kind: workflow
    title: Update visible price list
    objective: Route precondition should evaluate the price list state, not permission setup state.
    state_change: mutate
    setup:
      - use_entity: price_list
        operation: create_visible
      - use_entity: price_list_permission
        operation: revoke_partner_edit
    execute:
      route:
        method: POST
        path: /api/price_list/{{price_list_id}}/update/
    oracle:
      status_code: 200
      persisted_state:
        entity: price_list
        operation: verify_visible
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.PASS)
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        self.assertNotIn("authoring_stage_inventory_state_mismatch", codes)
        self.assertNotIn("authoring_stage_inventory_operation_mismatch", codes)

    def test_compile_file_blocks_composite_scoped_by_outside_entity_keys(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "artifacts" / "agent" / "generation" / "gen-20260428T000000Z-test0012"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "entity-inventory.yaml").write_text(
                """version: 1
source_id: price-list-plan
project: code/demo
surface: price-list-permissions
entities:
  - name: price_list_permission
    id_field: price_list_permission_id
    key_fields: [price_list_id, partner_member_guid]
""",
                encoding="utf-8",
            )
            (bundle_dir / "operation-inventory.yaml").write_text(
                """version: 1
source_id: price-list-plan
project: code/demo
surface: price-list-permissions
entity_operations: []
routes: []
db_verifications:
  - entity: price_list_permission
    operation: verify_partner_edit_denied
    scoped_by: [price_list_id, typo_member_guid]
    sql: SELECT can_edit FROM price_list_permission WHERE price_list_id = :price_list_id AND typo_member_guid = :typo_member_guid
    params:
      price_list_id: "{{price_list_id}}"
      typo_member_guid: "{{typo_member_guid}}"
    expected_outcomes:
      - one row exists
      - "`can_edit` = `false`"
""",
                encoding="utf-8",
            )
            authoring_plan_path = bundle_dir / "authoring-plan.yaml"
            authoring_plan_path.write_text(
                """version: 1
source_id: price-list-plan
project: code/demo
title: Price list permissions
goal: Cover price list permissions.
scope:
  surface: price-list-permissions
entities:
  price_list_permission:
    id_field: price_list_permission_id
    operations:
      verify_partner_edit_denied:
        sql: SELECT can_edit FROM price_list_permission WHERE price_list_id = :price_list_id AND typo_member_guid = :typo_member_guid
        params:
          price_list_id: "{{price_list_id}}"
          typo_member_guid: "{{typo_member_guid}}"
        expected_outcomes:
          - one row exists
          - "`can_edit` = `false`"
cases: []
""",
                encoding="utf-8",
            )

            result = AuthoringPlanCompiler().validate_file(authoring_plan_path)

        self.assertEqual(result.status, StepStatus.BLOCKED)
        diagnostics = [
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "authoring_stage_inventory_operation_mismatch"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].details["scoped_by"], ["price_list_id", "typo_member_guid"])
        self.assertEqual(
            diagnostics[0].details["inventory_key_fields"],
            ["price_list_id", "partner_member_guid"],
        )


def _identity_entity_with_numeric_subject_constraint() -> AuthoringEntitySpec:
    return AuthoringEntitySpec(
        operations={
            "link_telegram": AuthoringEntityOperation(
                route=AuthoringRoute(method="POST", path="/users/u1/identities"),
                request_constraints=[
                    {
                        "field": "subject",
                        "format": "numeric_string",
                        "when": {"provider": "TELEGRAM"},
                    }
                ],
            )
        }
    )


if __name__ == "__main__":
    unittest.main()
