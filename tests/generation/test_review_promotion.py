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
    ScenarioDraftPromotionService,
    ScenarioDraftReviewService,
    ScenarioPromotionRequest,
)


class ScenarioDraftReviewPromotionTests(unittest.TestCase):
    def test_review_service_loads_drafts_and_parse_status(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)

            review_set = ScenarioDraftReviewService().review(payload["run_id"], workspace_root=root)

        self.assertEqual(len(review_set.items), 1)
        self.assertEqual(review_set.items[0].draft_id, "draft-tc-001")
        self.assertEqual(review_set.items[0].parse_status.value, "valid")
        self.assertEqual(review_set.items[0].readiness_category.value, "parser_valid_strongly_supported")
        self.assertEqual(review_set.items[0].promotion_advisory.value, "promotable_with_known_gaps")
        self.assertEqual(review_set.items[0].route_status, "resolved_from_route_hints")
        self.assertIn("request_body_not_inferred", review_set.items[0].gap_summary.gap_codes)
        self.assertIn("auth_headers_unresolved", review_set.items[0].gap_summary.gap_codes)
        self.assertEqual(review_set.items[0].checklist.total_requirements, 8)
        self.assertTrue(
            any(
                check.requirement.requirement_id == "endpoint_path" and check.status.value == "satisfied"
                for check in review_set.items[0].checklist.checks
            )
        )
        self.assertTrue(
            any(
                check.requirement.requirement_id == "request_structure" and check.status.value == "missing"
                for check in review_set.items[0].checklist.checks
            )
        )
        self.assertEqual(review_set.items[0].edit_target_count, 5)
        self.assertTrue(
            any(
                target.target_type.value == "add_request_body" and target.section_name == "Steps"
                for target in review_set.items[0].edit_targets.targets
            )
        )
        request_target = next(
            target
            for target in review_set.items[0].edit_targets.targets
            if target.target_type.value == "add_request_body"
        )
        self.assertEqual(request_target.patch_suggestion.template_id, "steps.add_request_body.v1")
        self.assertIn("Body:", request_target.patch_suggestion.template_preview)
        self.assertIn('  "<field>": "<value>"', request_target.patch_suggestion.template_preview)
        self.assertTrue(
            any(
                target.target_type.value == "add_expected_assertion"
                and target.section_name == "Final expectations"
                for target in review_set.items[0].edit_targets.targets
            )
        )
        self.assertTrue(
            any(
                target.target_type.value == "add_auth_headers"
                and target.section_name == "Preconditions"
                for target in review_set.items[0].edit_targets.targets
            )
        )
        self.assertTrue(
            any(
                target.target_type.value == "add_db_verification" and target.section_name == "Notes"
                for target in review_set.items[0].edit_targets.targets
            )
        )
        self.assertTrue(
            any(
                target.target_type.value == "add_capture" and target.section_name == "Steps"
                for target in review_set.items[0].edit_targets.targets
            )
        )
        self.assertFalse(review_set.items[0].has_unsupported_items)
        self.assertFalse(review_set.items[0].has_deferred_items)

    def test_review_service_marks_route_resolved_draft_as_partial_preview(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _set_route_binding_readiness(Path(payload["artifact_paths"]["scenario_render_result"]), "route_resolved")

            review_set = ScenarioDraftReviewService().review(payload["run_id"], workspace_root=root)

        self.assertEqual(review_set.items[0].readiness_category.value, "parser_valid_partial")
        self.assertEqual(review_set.items[0].promotion_advisory.value, "safe_preview_only")
        self.assertIn("non_route_requirements_remaining", review_set.items[0].gap_summary.gap_codes)
        self.assertGreater(review_set.items[0].checklist.partial_count, 0)
        self.assertGreater(review_set.items[0].edit_target_count, 0)

    def test_review_service_reads_case_support_when_route_binding_projection_is_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _drop_route_binding_keep_case_support(Path(payload["artifact_paths"]["scenario_render_result"]))

            review_set = ScenarioDraftReviewService().review(payload["run_id"], workspace_root=root)

        self.assertEqual(review_set.items[0].route_status, "resolved_from_route_hints")
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
        self.assertIn("parser_invalid", review_set.items[0].gap_summary.gap_codes)
        self.assertTrue(
            any(
                check.requirement.requirement_id == "parser_valid" and check.status.value == "missing"
                for check in review_set.items[0].checklist.checks
            )
        )
        self.assertTrue(
            any(
                target.target_type.value == "fix_parser_errors"
                for target in review_set.items[0].edit_targets.targets
            )
        )

    def test_review_service_checklist_marks_get_route_as_request_complete(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _set_route_binding_method(Path(payload["artifact_paths"]["scenario_render_result"]), "GET")

            review_set = ScenarioDraftReviewService().review(payload["run_id"], workspace_root=root)

        request_check = next(
            check
            for check in review_set.items[0].checklist.checks
            if check.requirement.requirement_id == "request_structure"
        )
        self.assertEqual(request_check.status.value, "satisfied")

    def test_promotion_success_adds_metadata_header_and_preserves_draft_body(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            draft_path = Path(payload["artifact_paths"]["scenario_drafts_dir"]) / "tc-001-create-user.md"
            original = draft_path.read_text(encoding="utf-8")

            result = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(
                    run_id=payload["run_id"],
                    draft_id="draft-tc-001",
                    workspace_root=root,
                )
            )

            promoted = result.target_path.read_text(encoding="utf-8")

            self.assertEqual(result.status.value, "PASS")
            self.assertTrue(result.target_path.exists())
            self.assertTrue(result.promotion_result_path.exists())
            self.assertIn("generated_by: codex-qa-agent", promoted)
            self.assertIn(f"generation_run_id: {payload['run_id']}", promoted)
            self.assertTrue(promoted.endswith(original))

    def test_promotion_never_overwrites_existing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            request = ScenarioPromotionRequest(
                run_id=payload["run_id"],
                draft_id="draft-tc-001",
                workspace_root=root,
            )
            first = ScenarioDraftPromotionService().promote(request)
            first.target_path.write_text("do not overwrite", encoding="utf-8")

            second = ScenarioDraftPromotionService().promote(request)

            self.assertEqual(second.status.value, "ERROR")
            self.assertTrue(any(diagnostic.code == "scenario_promotion_target_exists" for diagnostic in second.diagnostics))
            self.assertEqual(first.target_path.read_text(encoding="utf-8"), "do not overwrite")

    def test_invalid_draft_rejected_unless_override_is_explicit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _mark_draft_invalid(Path(payload["artifact_paths"]["scenario_render_result"]))

            rejected = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(
                    run_id=payload["run_id"],
                    draft_id="draft-tc-001",
                    workspace_root=root,
                )
            )
            allowed = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(
                    run_id=payload["run_id"],
                    draft_id="draft-tc-001",
                    workspace_root=root,
                    allow_invalid=True,
                )
            )

        self.assertEqual(rejected.status.value, "ERROR")
        self.assertTrue(any(diagnostic.code == "scenario_promotion_invalid_draft" for diagnostic in rejected.diagnostics))
        self.assertEqual(allowed.status.value, "PASS")
        self.assertTrue(any(diagnostic.code == "scenario_promotion_invalid_override" for diagnostic in allowed.diagnostics))

    def test_cli_review_and_promote_commands(self) -> None:
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
                    ]
                )
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
                    ]
                )
            promote_payload = json.loads(promote_stdout.getvalue())

            self.assertEqual(review_code, 0)
            self.assertEqual(review_payload["draft_count"], 1)
            self.assertEqual(review_payload["strongly_supported_draft_count"], 1)
            self.assertEqual(review_payload["drafts_with_edit_targets"], 1)
            self.assertEqual(review_payload["total_edit_targets"], 5)
            self.assertGreater(review_payload["average_completeness_ratio"], 0.0)
            self.assertEqual(review_payload["close_to_runnable_count"], 1)
            self.assertEqual(review_payload["review_set"]["items"][0]["parse_status"], "valid")
            self.assertEqual(
                review_payload["review_set"]["items"][0]["promotion_advisory"],
                "promotable_with_known_gaps",
            )
            self.assertEqual(
                review_payload["review_set"]["items"][0]["edit_targets"]["targets"][0]["section_name"],
                "Steps",
            )
            self.assertEqual(promote_code, 0)
            self.assertTrue(Path(promote_payload["target_path"]).exists())
            self.assertTrue(str(promote_payload["target_path"]).endswith("users-draft-tc-001.md"))

    def test_cli_review_output_surfaces_partial_draft_gaps(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _set_route_binding_readiness(Path(payload["artifact_paths"]["scenario_render_result"]), "route_resolved")

            review_stdout = io.StringIO()
            with redirect_stdout(review_stdout):
                review_code = cli.main(
                    [
                        "--review-drafts",
                        "--run-id",
                        payload["run_id"],
                        "--workspace-root",
                        str(root),
                    ]
                )
            review_payload = json.loads(review_stdout.getvalue())

        self.assertEqual(review_code, 0)
        self.assertEqual(review_payload["partial_draft_count"], 1)
        self.assertEqual(
            review_payload["review_set"]["items"][0]["readiness_category"],
            "parser_valid_partial",
        )
        self.assertEqual(
            review_payload["review_set"]["items"][0]["promotion_advisory"],
            "safe_preview_only",
        )
        self.assertIn(
            "non_route_requirements_remaining",
            review_payload["review_set"]["items"][0]["gap_summary"]["gap_codes"],
        )
        self.assertGreater(review_payload["review_set"]["items"][0]["edit_target_count"], 0)

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
        self.assertIn("OK Endpoint path is defined.", review_text)
        self.assertIn("MISSING Request structure is defined.", review_text)
        self.assertIn("Remaining gaps:", review_text)
        self.assertIn("Edit targets:", review_text)
        self.assertIn("[Steps] add_request_body:", review_text)
        self.assertIn("Template: steps.add_request_body.v1", review_text)
        self.assertIn('"<field>": "<value>"', review_text)
        self.assertIn("[Final expectations] add_expected_assertion:", review_text)

    def test_patch_template_catalog_maps_each_edit_target_type(self) -> None:
        service = PatchTemplateCatalogService()
        catalog = service.list_templates()

        target_types = {template.target_type for template in catalog.templates}

        self.assertEqual(catalog.catalog_version, "v1")
        self.assertEqual(target_types, set(DraftEditTargetType))
        request_template = service.get_template(DraftEditTargetType.ADD_REQUEST_BODY)
        self.assertIsNotNone(request_template)
        self.assertEqual(request_template.section_name, "Steps")
        self.assertEqual(request_template.template_id, "steps.add_request_body.v1")
        self.assertIn('  "<field>": "<value>"', request_template.template_lines)

    def test_cli_patch_template_commands(self) -> None:
        list_stdout = io.StringIO()
        with redirect_stdout(list_stdout):
            list_code = cli.main(["--list-patch-templates"])
        list_payload = json.loads(list_stdout.getvalue())

        show_stdout = io.StringIO()
        with redirect_stdout(show_stdout):
            show_code = cli.main(["--show-patch-template", "--target-type", "add_request_body"])
        show_payload = json.loads(show_stdout.getvalue())

        text_stdout = io.StringIO()
        with redirect_stdout(text_stdout):
            text_code = cli.main(
                [
                    "--show-patch-template",
                    "--target-type",
                    "add_expected_assertion",
                    "--output-format",
                    "text",
                ]
            )
        text_output = text_stdout.getvalue()

        self.assertEqual(list_code, 0)
        self.assertEqual(list_payload["status"], "PASS")
        self.assertEqual(list_payload["template_count"], len(DraftEditTargetType))
        self.assertIn(
            "steps.add_request_body.v1",
            {template["template_id"] for template in list_payload["templates"]},
        )
        self.assertEqual(show_code, 0)
        self.assertEqual(show_payload["template"]["template_id"], "steps.add_request_body.v1")
        self.assertEqual(show_payload["template"]["section_name"], "Steps")
        self.assertIn('  "<field>": "<value>"', show_payload["template"]["template_lines"])
        self.assertEqual(text_code, 0)
        self.assertIn("Template: final-expectations.add_expected_assertion.v1", text_output)
        self.assertIn("Section: Final expectations", text_output)

    def test_patch_template_commands_do_not_mutate_draft_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            draft_path = Path(payload["artifact_paths"]["scenario_drafts_dir"]) / "tc-001-create-user.md"
            before = draft_path.read_text(encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "--show-patch-template",
                        "--target-type",
                        "add_request_body",
                        "--workspace-root",
                        str(root),
                    ]
                )

            after = draft_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(before, after)


def _generate_draft_run(root: Path) -> dict[str, object]:
    project = root / "code" / "demo"
    project.mkdir(parents=True)
    (project / "api.py").write_text(
        "\n".join(
            [
                "from fastapi import APIRouter",
                "router = APIRouter()",
                "@router.post('/users')",
                "def create_user(payload: dict) -> dict:",
                "    return payload",
            ]
        ),
        encoding="utf-8",
    )
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = cli.main(
            [
                "--source-id",
                "users",
                "--project",
                "code/demo",
                "--prose",
                "Verify create user",
                "--workspace-root",
                str(root),
                "--project-path",
                str(project),
                "--collect-code-facts",
                "--enrich",
                "--render-drafts",
                "--evidence-scope-path",
                "api.py",
            ]
        )
    payload = json.loads(stdout.getvalue())
    if exit_code != 0:
        raise AssertionError(payload)
    return payload


def _mark_draft_invalid(render_result_path: Path) -> None:
    payload = json.loads(render_result_path.read_text(encoding="utf-8"))
    payload["validation_results"][0]["parse_valid"] = False
    payload["validation_results"][0]["diagnostics"] = [
        {"code": "test.invalid", "message": "invalid for test"}
    ]
    render_result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _set_route_binding_readiness(render_result_path: Path, readiness: str) -> None:
    payload = json.loads(render_result_path.read_text(encoding="utf-8"))
    payload["draft_set"]["drafts"][0]["metadata"]["route_binding"]["readiness"] = readiness
    case_support = payload["draft_set"]["drafts"][0]["metadata"].get("case_support")
    if isinstance(case_support, dict):
        case_support["readiness"] = readiness
    render_result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _set_route_binding_method(render_result_path: Path, method: str) -> None:
    payload = json.loads(render_result_path.read_text(encoding="utf-8"))
    payload["draft_set"]["drafts"][0]["metadata"]["route_binding"]["http_method"] = method
    case_support = payload["draft_set"]["drafts"][0]["metadata"].get("case_support")
    if isinstance(case_support, dict):
        route_hints = case_support.get("route_hints")
        if isinstance(route_hints, list) and route_hints:
            route_hints[0]["http_method"] = method
    render_result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _drop_route_binding_keep_case_support(render_result_path: Path) -> None:
    payload = json.loads(render_result_path.read_text(encoding="utf-8"))
    payload["draft_set"]["drafts"][0]["metadata"].pop("route_binding", None)
    render_result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
