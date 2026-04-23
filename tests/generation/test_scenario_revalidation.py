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
from tools.generation.review import ScenarioRevalidationRequest, ScenarioRevalidationService


class ScenarioRevalidationTests(unittest.TestCase):
    def test_valid_scenario_file_returns_parser_valid_checklist_without_generation_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(Path(tmp), _complete_post_scenario())

            result = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(file_path=scenario_path)
            )

        self.assertEqual(result.parse_status.value, "valid")
        self.assertEqual(result.promotion_advisory.value, "promotable_with_known_gaps")
        self.assertEqual(result.completeness_ratio, 1.0)
        self.assertFalse(result.based_on_generated_draft)
        self.assertEqual(len(result.edit_targets.targets), 0)
        self.assertTrue(
            any(
                check.requirement.requirement_id == "endpoint_path"
                and check.status.value == "satisfied"
                for check in result.checklist.checks
            )
        )
        self.assertTrue(
            any(
                check.requirement.requirement_id == "assertions"
                and check.status.value == "satisfied"
                for check in result.checklist.checks
            )
        )

    def test_invalid_scenario_file_returns_parser_error_and_fix_target(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(Path(tmp), _invalid_json_body_scenario())

            result = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(file_path=scenario_path)
            )

        self.assertEqual(result.parse_status.value, "invalid")
        self.assertEqual(result.promotion_advisory.value, "invalid_draft")
        self.assertIn("parser_invalid", result.gap_summary.gap_codes)
        self.assertTrue(result.diagnostics)
        self.assertTrue(
            any(target.target_type.value == "fix_parser_errors" for target in result.edit_targets.targets)
        )

    def test_partially_fixed_scenario_improves_checklist_and_edit_targets(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(Path(tmp), _partial_post_scenario())
            before = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(file_path=scenario_path)
            )

            scenario_path.write_text(_complete_post_scenario(), encoding="utf-8")
            after = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(file_path=scenario_path)
            )

        self.assertEqual(before.parse_status.value, "valid")
        self.assertIn("request_body_not_inferred", before.gap_summary.gap_codes)
        self.assertIn("assertions_not_generated", before.gap_summary.gap_codes)
        self.assertGreater(len(before.edit_targets.targets), 0)
        self.assertGreater(after.completeness_ratio, before.completeness_ratio)
        self.assertEqual(after.completeness_ratio, 1.0)
        self.assertEqual(len(after.edit_targets.targets), 0)

    def test_promoted_metadata_is_detected_without_generation_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(
                Path(tmp),
                "\n".join(
                    [
                        "<!--",
                        "generated_by: codex-qa-agent",
                        "generation_run_id: run-123",
                        "draft_id: draft-tc-001",
                        "source: draft-rendering-preview",
                        "-->",
                        "",
                        _complete_post_scenario(),
                    ]
                ),
            )

            result = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(file_path=scenario_path)
            )

        self.assertTrue(result.based_on_generated_draft)
        self.assertEqual(result.generation_run_id, "run-123")
        self.assertEqual(result.draft_id, "draft-tc-001")

    def test_cli_validate_scenario_outputs_json_and_text(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(Path(tmp), _partial_post_scenario())

            json_stdout = io.StringIO()
            with redirect_stdout(json_stdout):
                json_code = cli.main(["--validate-scenario", "--path", str(scenario_path)])
            json_payload = json.loads(json_stdout.getvalue())

            text_stdout = io.StringIO()
            with redirect_stdout(text_stdout):
                text_code = cli.main(
                    [
                        "--validate-scenario",
                        "--path",
                        str(scenario_path),
                        "--output-format",
                        "text",
                    ]
                )
            text_output = text_stdout.getvalue()

        self.assertEqual(json_code, 0)
        self.assertEqual(json_payload["parse_status"], "valid")
        self.assertIn("request_body_not_inferred", json_payload["gap_summary"]["gap_codes"])
        self.assertTrue(
            any(
                target["target_type"] == "add_request_body"
                for target in json_payload["edit_targets"]["targets"]
            )
        )
        self.assertEqual(text_code, 0)
        self.assertIn("Parse: valid", text_output)
        self.assertIn("Checklist:", text_output)
        self.assertIn("[Steps] add_request_body:", text_output)
        self.assertIn("Template: steps.add_request_body.v1", text_output)


def _write_scenario(root: Path, content: str) -> Path:
    path = root / "scenario.md"
    path.write_text(content, encoding="utf-8")
    return path


def _partial_post_scenario() -> str:
    return """
# Scenario: Create User

## Project
code/demo

## Environment
env/demo.env

## Steps

### Step 1
Type: api
Name: create user
Method: POST
Path: /users
""".lstrip()


def _complete_post_scenario() -> str:
    return """
# Scenario: Create User

## Project
code/demo

## Environment
env/demo.env

## Steps

### Step 1
Type: api
Name: create user
Method: POST
Path: /users
Body:
```json
{
  "email": "operator-confirmed@example.com"
}
```
Expected:
- HTTP response indicates successful creation.

## Final expectations

- Created user response is returned.
""".lstrip()


def _invalid_json_body_scenario() -> str:
    return """
# Scenario: Invalid Draft

## Project
code/demo

## Environment
env/demo.env

## Steps

### Step 1
Type: api
Name: create user
Method: POST
Path: /users
Body:
```json
{
  "email": "broken"
```
""".lstrip()


if __name__ == "__main__":
    unittest.main()
