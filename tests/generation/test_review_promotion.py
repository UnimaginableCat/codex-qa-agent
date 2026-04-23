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
        self.assertFalse(review_set.items[0].has_unsupported_items)
        self.assertFalse(review_set.items[0].has_deferred_items)

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
            self.assertEqual(review_payload["review_set"]["items"][0]["parse_status"], "valid")
            self.assertEqual(promote_code, 0)
            self.assertTrue(Path(promote_payload["target_path"]).exists())
            self.assertTrue(str(promote_payload["target_path"]).endswith("users-draft-tc-001.md"))


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


if __name__ == "__main__":
    unittest.main()
