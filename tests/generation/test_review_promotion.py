from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation import cli
from tools.generation.review import (
    DraftEditTargetType,
    PatchTemplateCatalogService,
    ScenarioDraftBatchPromotionService,
    ScenarioDraftPromotionService,
    ScenarioDraftReviewService,
    ScenarioPromotionBatchRequest,
    ScenarioPromotionRequest,
)


class ScenarioDraftReviewPromotionTests(unittest.TestCase):
    def test_review_service_loads_drafts_and_parse_status(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            review_set = ScenarioDraftReviewService().review(payload["run_id"], workspace_root=root)

        self.assertEqual(len(review_set.items), 1)
        self.assertEqual(review_set.items[0].parse_status.value, "valid")
        self.assertEqual(review_set.items[0].readiness_category.value, "parser_valid_strongly_supported")
        self.assertEqual(review_set.items[0].promotion_advisory.value, "promotable_with_known_gaps")
        self.assertEqual(review_set.items[0].route_status, "resolved_from_planned_route")
        self.assertFalse(any(target.target_type.value == "add_expected_assertion" for target in review_set.items[0].edit_targets.targets))
        self.assertNotIn("assertions_not_generated", review_set.items[0].gap_summary.gap_codes)

    def test_review_service_does_not_flag_authored_workflow_capture_or_expectations(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_workflow_draft_run(root)
            review_set = ScenarioDraftReviewService().review(payload["run_id"], workspace_root=root)
            draft_path = Path(payload["artifact_paths"]["scenario_drafts_dir"]) / (
                "tc-001-create-and-fetch-session.md"
            )
            draft_markdown = draft_path.read_text(encoding="utf-8")

        self.assertEqual(len(review_set.items), 1)
        item = review_set.items[0]
        self.assertEqual(item.parse_status.value, "valid")
        self.assertNotIn("assertions_not_generated", item.gap_summary.gap_codes)
        self.assertNotIn("captures_not_generated", item.gap_summary.gap_codes)
        self.assertFalse(any(target.target_type.value == "add_expected_assertion" for target in item.edit_targets.targets))
        self.assertFalse(any(target.target_type.value == "add_capture" for target in item.edit_targets.targets))
        self.assertIn("Type: db", draft_markdown)
        self.assertIn("Name: Verify session row remains readable", draft_markdown)

    def test_review_service_reads_case_support_when_route_binding_projection_is_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _drop_route_binding_keep_case_support(Path(payload["artifact_paths"]["scenario_render_result"]))
            review_set = ScenarioDraftReviewService().review(payload["run_id"], workspace_root=root)

        self.assertEqual(review_set.items[0].route_status, "resolved_from_planned_route")
        self.assertEqual(review_set.items[0].readiness_category.value, "parser_valid_strongly_supported")

    def test_review_service_marks_invalid_draft_as_invalid_review_item(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _mark_draft_invalid(Path(payload["artifact_paths"]["scenario_render_result"]))
            review_set = ScenarioDraftReviewService().review(payload["run_id"], workspace_root=root)

        self.assertEqual(review_set.items[0].parse_status.value, "invalid")
        self.assertEqual(review_set.items[0].readiness_category.value, "parser_invalid")
        self.assertEqual(review_set.items[0].promotion_advisory.value, "invalid_draft")

    def test_review_service_defers_case_with_seeded_id_gap(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_seeded_id_gap_run(root)
            review_set = ScenarioDraftReviewService().review(payload["run_id"], workspace_root=root)

        self.assertEqual(review_set.items, [])
        self.assertEqual(len(review_set.deferred_items), 1)
        self.assertIn("data_setup_unresolved", review_set.deferred_items[0].gap_summary.gap_codes)
        self.assertEqual(review_set.deferred_items[0].promotion_advisory.value, "not_recommended_for_promotion")

    def test_review_service_blocks_draft_with_ambiguous_assertion_dsl(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _make_first_draft_expectation_unsupported(payload)

            review_set = ScenarioDraftReviewService().review(payload["run_id"], workspace_root=root)

        self.assertEqual(len(review_set.items), 1)
        item = review_set.items[0]
        self.assertIn("compile_unsupported_expectation", item.gap_summary.gap_codes)
        self.assertEqual(item.readiness_category.value, "parser_valid_partial")
        self.assertEqual(item.promotion_advisory.value, "not_recommended_for_promotion")
        self.assertTrue(any(target.priority == "high" for target in item.edit_targets.targets))
        self.assertTrue(any("response length >= 1" in message for message in item.gap_summary.gap_messages))

    def test_review_service_blocks_intercase_precondition(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _add_first_draft_intercase_precondition(payload)

            review_set = ScenarioDraftReviewService().review(payload["run_id"], workspace_root=root)

        item = review_set.items[0]
        self.assertIn("stateful_intercase_precondition", item.gap_summary.gap_codes)
        self.assertEqual(item.promotion_advisory.value, "not_recommended_for_promotion")
        self.assertTrue(
            any(
                target.section_name == "Preconditions" and target.priority == "high"
                for target in item.edit_targets.targets
            )
        )

    def test_promotion_blocks_draft_with_high_priority_review_target(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _make_first_draft_expectation_unsupported(payload)

            result = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(run_id=payload["run_id"], draft_id="draft-tc-001", workspace_root=root)
            )

        self.assertEqual(result.status.value, "BLOCKED")
        self.assertIsNone(result.target_path)
        self.assertTrue(
            any(diagnostic.code == "scenario_promotion_review_gate_blocked" for diagnostic in result.diagnostics)
        )

    def test_promotion_blocks_low_priority_review_targets_without_override(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)

            result = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(run_id=payload["run_id"], draft_id="draft-tc-001", workspace_root=root)
            )

        self.assertEqual(result.status.value, "BLOCKED")
        self.assertIsNone(result.target_path)
        self.assertTrue(
            any(diagnostic.code == "scenario_promotion_review_gate_blocked" for diagnostic in result.diagnostics)
        )
        diagnostic = next(
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "scenario_promotion_review_gate_blocked"
        )
        self.assertGreater(diagnostic.details["edit_target_count"], 0)
        self.assertEqual(diagnostic.details["high_priority_edit_target_count"], 0)

    def test_promotion_blocks_placeholder_context_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _set_context_metadata(payload, source_id="replace-with-source-id", project="code/replace-project")

            result = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(
                    run_id=payload["run_id"],
                    draft_id="draft-tc-001",
                    workspace_root=root,
                    allow_known_gaps=True,
                    known_gaps_reviewed=True,
                )
            )

        self.assertEqual(result.status.value, "BLOCKED")
        self.assertTrue(
            any(
                diagnostic.code == "scenario_promotion_run_context_placeholder_metadata"
                for diagnostic in result.diagnostics
            )
        )

    def test_promotion_blocks_context_agent_plan_metadata_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _set_context_metadata(payload, source_id="stale-source", project="code/demo")

            result = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(
                    run_id=payload["run_id"],
                    draft_id="draft-tc-001",
                    workspace_root=root,
                    allow_known_gaps=True,
                    known_gaps_reviewed=True,
                )
            )

        self.assertEqual(result.status.value, "BLOCKED")
        self.assertTrue(
            any(
                diagnostic.code == "scenario_promotion_run_context_agent_plan_mismatch"
                for diagnostic in result.diagnostics
            )
        )

    def test_promotion_blocks_known_gaps_without_review_confirmation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _make_first_draft_expectation_unsupported(payload)

            result = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(
                    run_id=payload["run_id"],
                    draft_id="draft-tc-001",
                    workspace_root=root,
                    allow_known_gaps=True,
                )
            )

            self.assertEqual(result.status.value, "BLOCKED")
            self.assertIsNone(result.target_path)
            self.assertTrue(
                any(
                    diagnostic.code == "scenario_promotion_known_gaps_confirmation_missing"
                    for diagnostic in result.diagnostics
                )
            )

    def test_promotion_allows_known_gaps_with_explicit_review_confirmation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _make_first_draft_expectation_unsupported(payload)

            result = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(
                    run_id=payload["run_id"],
                    draft_id="draft-tc-001",
                    workspace_root=root,
                    allow_known_gaps=True,
                    known_gaps_reviewed=True,
                )
            )

            self.assertEqual(result.status.value, "PASS")
            self.assertTrue(result.target_path.exists())
            self.assertTrue(
                any(diagnostic.code == "scenario_promotion_known_gaps_override" for diagnostic in result.diagnostics)
            )

    def test_promotion_promotes_one_draft(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            result = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(
                    run_id=payload["run_id"],
                    draft_id="draft-tc-001",
                    workspace_root=root,
                    allow_known_gaps=True,
                    known_gaps_reviewed=True,
                )
            )
            self.assertEqual(result.status.value, "PASS")
            self.assertTrue(result.target_path.exists())
            self.assertTrue(result.promotion_result_path.exists())

    def test_promotion_shortens_long_target_filename(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_long_named_draft_run(root)
            result = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(
                    run_id=payload["run_id"],
                    draft_id="draft-tc-001",
                    workspace_root=root,
                    allow_known_gaps=True,
                    known_gaps_reviewed=True,
                )
            )

            self.assertEqual(result.status.value, "PASS")
            assert result.target_path is not None
            self.assertLessEqual(len(result.target_path.name), 123)
            self.assertTrue(result.target_path.exists())

    def test_batch_promotion_promotes_all_drafts_in_one_run(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _duplicate_first_draft(payload, draft_id="draft-tc-002", file_name="tc-002-create-user-2.md")
            result = ScenarioDraftBatchPromotionService().promote(
                ScenarioPromotionBatchRequest(
                    run_id=payload["run_id"],
                    workspace_root=root,
                    allow_known_gaps=True,
                    known_gaps_reviewed=True,
                )
            )
            self.assertEqual(result.status.value, "PASS")
            self.assertEqual(result.promoted_count, 2)
            self.assertEqual(result.error_count, 0)
            self.assertEqual(result.blocked_count, 0)

    def test_batch_promotion_reports_blocked_review_gate(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _make_first_draft_expectation_unsupported(payload)

            result = ScenarioDraftBatchPromotionService().promote(
                ScenarioPromotionBatchRequest(run_id=payload["run_id"], workspace_root=root)
            )

        self.assertEqual(result.status.value, "BLOCKED")
        self.assertEqual(result.promoted_count, 0)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(result.blocked_count, 1)

    def test_batch_promotion_can_purge_target_dir_before_rerun(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            first_result = ScenarioDraftBatchPromotionService().promote(
                ScenarioPromotionBatchRequest(
                    run_id=payload["run_id"],
                    workspace_root=root,
                    allow_known_gaps=True,
                    known_gaps_reviewed=True,
                )
            )
            second_result = ScenarioDraftBatchPromotionService().promote(
                ScenarioPromotionBatchRequest(
                    run_id=payload["run_id"],
                    workspace_root=root,
                    allow_known_gaps=True,
                    known_gaps_reviewed=True,
                    purge_target_dir=True,
                )
            )

            self.assertEqual(first_result.status.value, "PASS")
            self.assertEqual(second_result.status.value, "PASS")
            self.assertEqual(second_result.promoted_count, 1)
            self.assertEqual(second_result.error_count, 0)

    def test_cli_review_and_promote_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)

            review_stdout = io.StringIO()
            with redirect_stdout(review_stdout):
                review_code = cli.main(["--review-drafts", "--run-id", payload["run_id"], "--workspace-root", str(root)])
            review_payload = json.loads(review_stdout.getvalue())

            promote_stdout = io.StringIO()
            with redirect_stdout(promote_stdout):
                promote_code = cli.main(
                    [
                        "--promote-draft",
                        "--run-id",
                        payload["run_id"],
                        "--draft-id",
                        "draft-tc-001",
                        "--workspace-root",
                        str(root),
                        "--target-dir",
                        "scenarios/promoted",
                        "--allow-known-gaps",
                        "--known-gaps-reviewed",
                    ]
                )
            promote_payload = json.loads(promote_stdout.getvalue())
            self.assertEqual(review_code, 0)
            self.assertEqual(review_payload["draft_count"], 1)
            self.assertEqual(promote_code, 0)
            self.assertTrue(Path(promote_payload["target_path"]).exists())

    def test_cli_promote_all_can_purge_target_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)

            first_stdout = io.StringIO()
            with redirect_stdout(first_stdout):
                first_code = cli.main(
                    [
                        "--promote-all-drafts",
                        "--run-id",
                        payload["run_id"],
                        "--workspace-root",
                        str(root),
                        "--allow-known-gaps",
                        "--known-gaps-reviewed",
                    ]
                )
            second_stdout = io.StringIO()
            with redirect_stdout(second_stdout):
                second_code = cli.main(
                    [
                        "--promote-all-drafts",
                        "--run-id",
                        payload["run_id"],
                        "--workspace-root",
                        str(root),
                        "--purge-target-dir",
                        "--allow-known-gaps",
                        "--known-gaps-reviewed",
                    ]
                )
            first_payload = json.loads(first_stdout.getvalue())
            second_payload = json.loads(second_stdout.getvalue())

            self.assertEqual(first_code, 0)
            self.assertEqual(first_payload["status"], "PASS")
            self.assertEqual(second_code, 0)
            self.assertEqual(second_payload["status"], "PASS")
            self.assertEqual(second_payload["promoted_count"], 1)

    def test_cli_review_text_output_includes_checklist(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)

            review_stdout = io.StringIO()
            with redirect_stdout(review_stdout):
                review_code = cli.main(
                    [
                        "--review-drafts",
                        "--run-id",
                        payload["run_id"],
                        "--workspace-root",
                        str(root),
                        "--output-format",
                        "text",
                    ]
                )
            review_text = review_stdout.getvalue()
            self.assertEqual(review_code, 0)
            self.assertIn("Checklist:", review_text)
            self.assertIn("Remaining gaps:", review_text)
            self.assertIn("Edit targets:", review_text)

    def test_patch_template_catalog_maps_each_edit_target_type(self) -> None:
        service = PatchTemplateCatalogService()
        catalog = service.list_templates()

        self.assertEqual(catalog.catalog_version, "v1")
        self.assertEqual({template.target_type for template in catalog.templates}, set(DraftEditTargetType))


def _generate_draft_run(root: Path) -> dict[str, object]:
    agent_plan_path = root / "agent-plan.json"
    agent_plan_path.write_text(
        json.dumps(
            {
                "source_id": "users",
                "project": "code/demo",
                "title": "Users API",
                "planned_test_cases": [
                    {
                        "case_id": "tc-001",
                        "title": "Create user",
                        "objective": "Verify create user.",
                        "route": {"http_method": "POST", "endpoint_path": "/users"},
                        "expected_outcomes": ["HTTP 201"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = cli.main(
            [
                "--agent-plan-file",
                str(agent_plan_path),
                "--workspace-root",
                str(root),
                "--render-drafts",
            ]
        )
    payload = json.loads(stdout.getvalue())
    if exit_code != 0:
        raise AssertionError(payload)
    return payload


def _generate_workflow_draft_run(root: Path) -> dict[str, object]:
    agent_plan_path = root / "agent-plan.json"
    agent_plan_path.write_text(
        json.dumps(
            {
                "source_id": "sessions",
                "project": "code/demo",
                "title": "Sessions API",
                "planned_test_cases": [
                    {
                        "case_id": "tc-001",
                        "title": "Create and fetch session",
                        "objective": "Verify workflow draft keeps authored expectations and captures.",
                        "kind": "workflow",
                        "requires_db_verification": True,
                        "db_verification": {
                            "name": "Verify session row remains readable",
                            "sql": "SELECT COUNT(*) AS row_count FROM sessions WHERE id = :session_id",
                            "params": {"session_id": "{{session_id}}"},
                            "expected_outcomes": ["`row_count` = 1"],
                        },
                        "workflow_steps": [
                            {
                                "step_type": "api",
                                "title": "Create session",
                                "route": {"http_method": "POST", "endpoint_path": "/sessions"},
                                "request_body": {"name": "demo"},
                                "requires_request_body": True,
                                "capture": ["response.json.id -> session_id"],
                                "expected_outcomes": ["HTTP 201"],
                            },
                            {
                                "step_type": "api",
                                "title": "Fetch session",
                                "route": {"http_method": "GET", "endpoint_path": "/sessions/{{session_id}}"},
                                "expected_outcomes": ["HTTP 200"],
                            },
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = cli.main(
            [
                "--agent-plan-file",
                str(agent_plan_path),
                "--workspace-root",
                str(root),
                "--render-drafts",
            ]
        )
    payload = json.loads(stdout.getvalue())
    if exit_code != 0:
        raise AssertionError(payload)
    return payload


def _generate_seeded_id_gap_run(root: Path) -> dict[str, object]:
    agent_plan_path = root / "agent-plan.json"
    agent_plan_path.write_text(
        json.dumps(
            {
                "source_id": "users",
                "project": "code/demo",
                "title": "Users API",
                "planned_test_cases": [
                    {
                        "case_id": "tc-001",
                        "title": "Get existing user",
                        "objective": "Verify GET /users/{user_id} returns an existing user.",
                        "route": {"http_method": "GET", "endpoint_path": "/users/{{user_id}}"},
                        "expected_outcomes": ["HTTP 200", "response JSON exists"],
                        "unresolved_items": ["A seeded or previously created user_id must be supplied."],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = cli.main(
            [
                "--agent-plan-file",
                str(agent_plan_path),
                "--workspace-root",
                str(root),
                "--render-drafts",
            ]
        )
    payload = json.loads(stdout.getvalue())
    if exit_code != 0:
        raise AssertionError(payload)
    return payload


def _generate_long_named_draft_run(root: Path) -> dict[str, object]:
    agent_plan_path = root / "agent-plan.json"
    agent_plan_path.write_text(
        json.dumps(
            {
                "source_id": "leadflow-internal-user-controller-full-coverage",
                "project": "code/demo",
                "title": "LeadFlow InternalUserController full coverage",
                "planned_test_cases": [
                    {
                        "case_id": "tc-001",
                        "title": "Internal API client lists users using status, query, limit, and offset parameters and sees the created user in the result array " * 2,
                        "objective": "Verify long generated names are shortened safely.",
                        "route": {"http_method": "GET", "endpoint_path": "/users"},
                        "expected_outcomes": ["HTTP 200"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = cli.main(
            [
                "--agent-plan-file",
                str(agent_plan_path),
                "--workspace-root",
                str(root),
                "--render-drafts",
            ]
        )
    payload = json.loads(stdout.getvalue())
    if exit_code != 0:
        raise AssertionError(payload)
    return payload


def _mark_draft_invalid(render_result_path: Path) -> None:
    payload = json.loads(render_result_path.read_text(encoding="utf-8"))
    payload["validation_results"][0]["parse_valid"] = False
    payload["validation_results"][0]["diagnostics"] = [{"code": "test.invalid", "message": "invalid for test"}]
    render_result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_first_draft_expectation_unsupported(payload: dict[str, object]) -> None:
    draft_path = next(Path(payload["artifact_paths"]["scenario_drafts_dir"]).glob("*.md"))
    draft_text = draft_path.read_text(encoding="utf-8")
    draft_text = draft_text.replace("HTTP 201", "response length >= 1", 1)
    draft_path.write_text(draft_text, encoding="utf-8")


def _add_first_draft_intercase_precondition(payload: dict[str, object]) -> None:
    draft_path = next(Path(payload["artifact_paths"]["scenario_drafts_dir"]).glob("*.md"))
    draft_text = draft_path.read_text(encoding="utf-8")
    draft_text = draft_text.replace(
        "## Preconditions\n",
        "## Preconditions\n- partner_member_guid has can_create=true before this case runs.\n",
        1,
    )
    draft_path.write_text(draft_text, encoding="utf-8")


def _set_context_metadata(payload: dict[str, object], *, source_id: str, project: str) -> None:
    context_path = Path(payload["artifact_paths"]["context"])
    context_payload = json.loads(context_path.read_text(encoding="utf-8"))
    context_payload["source_id"] = source_id
    context_payload["project"] = project
    context_payload.setdefault("variables", {})["source_id"] = source_id
    context_payload.setdefault("variables", {})["project"] = project
    context_path.write_text(json.dumps(context_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _drop_route_binding_keep_case_support(render_result_path: Path) -> None:
    payload = json.loads(render_result_path.read_text(encoding="utf-8"))
    payload["draft_set"]["drafts"][0]["metadata"].pop("route_binding", None)
    render_result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _duplicate_first_draft(payload: dict[str, object], *, draft_id: str, file_name: str) -> None:
    render_result_path = Path(payload["artifact_paths"]["scenario_render_result"])
    draft_dir = Path(payload["artifact_paths"]["scenario_drafts_dir"])
    render_payload = json.loads(render_result_path.read_text(encoding="utf-8"))

    original_draft = dict(render_payload["draft_set"]["drafts"][0])
    original_validation = dict(render_payload["validation_results"][0])
    original_file = draft_dir / Path(original_draft["relative_path"]).name
    duplicated_file = draft_dir / file_name
    duplicated_file.write_text(original_file.read_text(encoding="utf-8"), encoding="utf-8")

    duplicated_draft = dict(original_draft)
    duplicated_draft["draft_id"] = draft_id
    duplicated_draft["case_id"] = draft_id.replace("draft-", "")
    duplicated_draft["title"] = f"{original_draft['title']} duplicate"
    duplicated_draft["relative_path"] = str(Path("scenario-drafts") / file_name).replace("\\", "/")

    duplicated_validation = dict(original_validation)
    duplicated_validation["draft_id"] = draft_id
    duplicated_validation["case_id"] = duplicated_draft["case_id"]
    duplicated_validation["path"] = str(duplicated_file)

    render_payload["draft_set"]["drafts"].append(duplicated_draft)
    render_payload["validation_results"].append(duplicated_validation)
    render_result_path.write_text(json.dumps(render_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
