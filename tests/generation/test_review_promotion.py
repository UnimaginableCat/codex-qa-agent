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
        self.assertTrue(any(target.target_type.value == "add_expected_assertion" for target in review_set.items[0].edit_targets.targets))

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

    def test_promotion_promotes_one_draft(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            result = ScenarioDraftPromotionService().promote(
                ScenarioPromotionRequest(run_id=payload["run_id"], draft_id="draft-tc-001", workspace_root=root)
            )
            self.assertEqual(result.status.value, "PASS")
            self.assertTrue(result.target_path.exists())
            self.assertTrue(result.promotion_result_path.exists())

    def test_batch_promotion_promotes_all_drafts_in_one_run(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _generate_draft_run(root)
            _duplicate_first_draft(payload, draft_id="draft-tc-002", file_name="tc-002-create-user-2.md")
            result = ScenarioDraftBatchPromotionService().promote(
                ScenarioPromotionBatchRequest(run_id=payload["run_id"], workspace_root=root)
            )
            self.assertEqual(result.status.value, "PASS")
            self.assertEqual(result.promoted_count, 2)
            self.assertEqual(result.error_count, 0)

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
                    ]
                )
            promote_payload = json.loads(promote_stdout.getvalue())
            self.assertEqual(review_code, 0)
            self.assertEqual(review_payload["draft_count"], 1)
            self.assertEqual(promote_code, 0)
            self.assertTrue(Path(promote_payload["target_path"]).exists())

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


def _mark_draft_invalid(render_result_path: Path) -> None:
    payload = json.loads(render_result_path.read_text(encoding="utf-8"))
    payload["validation_results"][0]["parse_valid"] = False
    payload["validation_results"][0]["diagnostics"] = [{"code": "test.invalid", "message": "invalid for test"}]
    render_result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
