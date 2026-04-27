from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation import cli
from tools.generation.review import (
    ScenarioDirectoryRevalidationRequest,
    ScenarioDirectoryRevalidationService,
    ScenarioRevalidationRequest,
    ScenarioRevalidationService,
)


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

    def test_compile_mode_marks_complete_scenario_runner_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(Path(tmp), _runner_ready_post_scenario())

            result = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(file_path=scenario_path, validation_mode="compile")
            )

        self.assertEqual(result.parse_status.value, "valid")
        self.assertIsNotNone(result.compile_validation)
        self.assertEqual(result.compile_validation.compile_status.value, "success")
        self.assertEqual(result.execution_readiness_category.value, "compile_valid_but_incomplete")
        self.assertEqual(result.compile_validation.issues, [])
        self.assertEqual(result.compile_validation.warnings, [])

    def test_compile_mode_surfaces_unsupported_expectation_dsl(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(Path(tmp), _unsupported_expectation_scenario())

            result = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(file_path=scenario_path, validation_mode="compile")
            )

        self.assertEqual(result.parse_status.value, "valid")
        self.assertEqual(result.compile_validation.compile_status.value, "failed")
        self.assertEqual(result.execution_readiness_category.value, "compile_blocked")
        self.assertTrue(
            any(issue.issue_type.value == "expectation_dsl" for issue in result.compile_validation.issues)
        )
        self.assertTrue(
            any(target.target_type.value == "add_expected_assertion" for target in result.edit_targets.targets)
        )

    def test_compile_mode_surfaces_external_variable_requirement(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(Path(tmp), _external_variable_scenario())

            result = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(file_path=scenario_path, validation_mode="compile")
            )

        self.assertEqual(result.compile_validation.compile_status.value, "success")
        self.assertEqual(result.execution_readiness_category.value, "compile_valid_but_incomplete")
        self.assertTrue(
            any(warning.issue_type.value == "variable_requirement" for warning in result.compile_validation.warnings)
        )
        self.assertIn("external_inputs_required", result.gap_summary.gap_codes)
        self.assertTrue(
            any(target.section_name == "Variables" for target in result.edit_targets.targets)
        )

    def test_compile_mode_skips_compile_when_parser_invalid(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(Path(tmp), _invalid_json_body_scenario())

            result = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(file_path=scenario_path, validation_mode="compile")
            )

        self.assertEqual(result.parse_status.value, "invalid")
        self.assertEqual(result.compile_validation.compile_status.value, "skipped")
        self.assertEqual(result.execution_readiness_category.value, "parser_invalid")

    def test_compile_mode_surfaces_future_capture_dependency(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(Path(tmp), _future_capture_dependency_scenario())

            result = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(file_path=scenario_path, validation_mode="compile")
            )

        self.assertEqual(result.compile_validation.compile_status.value, "failed")
        self.assertEqual(result.execution_readiness_category.value, "compile_blocked")
        self.assertTrue(
            any(issue.issue_type.value == "capture_reference" for issue in result.compile_validation.issues)
        )
        self.assertTrue(any(target.target_type.value == "add_capture" for target in result.edit_targets.targets))

    def test_compile_mode_allows_multi_step_negative_flow_without_capture_when_no_step_depends_on_prior_output(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(Path(tmp), _missing_tenant_negative_flow_scenario())

            result = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(file_path=scenario_path, validation_mode="compile")
            )

        self.assertEqual(result.parse_status.value, "valid")
        self.assertEqual(result.compile_validation.compile_status.value, "success")
        self.assertEqual(result.execution_readiness_category.value, "compile_valid_runner_ready")
        self.assertNotIn("captures_not_generated", result.gap_summary.gap_codes)

    def test_cli_compile_mode_outputs_readiness_and_compile_issues(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = _write_scenario(Path(tmp), _unsupported_expectation_scenario())

            json_stdout = io.StringIO()
            with redirect_stdout(json_stdout):
                json_code = cli.main(
                    ["--validate-scenario", "--path", str(scenario_path), "--mode", "compile"]
                )
            json_payload = json.loads(json_stdout.getvalue())

            text_stdout = io.StringIO()
            with redirect_stdout(text_stdout):
                text_code = cli.main(
                    [
                        "--validate-scenario",
                        "--path",
                        str(scenario_path),
                        "--mode",
                        "compile",
                        "--output-format",
                        "text",
                    ]
                )
            text_output = text_stdout.getvalue()

        self.assertEqual(json_code, 0)
        self.assertEqual(json_payload["compile_status"], "failed")
        self.assertEqual(json_payload["execution_readiness_category"], "compile_blocked")
        self.assertTrue(json_payload["compile_validation"]["issues"])
        self.assertEqual(text_code, 0)
        self.assertIn("Compile: failed", text_output)
        self.assertIn("Readiness: compile_blocked", text_output)
        self.assertIn("Compile issues:", text_output)

    def test_preflight_mode_skips_preflight_when_parser_invalid(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_path = _write_scenario(root, _invalid_json_body_scenario())

            result = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(
                    file_path=scenario_path,
                    validation_mode="preflight",
                    workspace_root=root,
                )
            )

        self.assertEqual(result.parse_status.value, "invalid")
        self.assertEqual(result.preflight_validation.preflight_status.value, "skipped")
        self.assertEqual(result.environment_readiness_category.value, "skipped_due_to_parser_error")

    def test_preflight_mode_skips_preflight_when_compile_blocked(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_path = _write_scenario(root, _unsupported_expectation_scenario())

            result = ScenarioRevalidationService().validate(
                ScenarioRevalidationRequest(
                    file_path=scenario_path,
                    validation_mode="preflight",
                    workspace_root=root,
                )
            )

        self.assertEqual(result.compile_validation.compile_status.value, "failed")
        self.assertEqual(result.preflight_validation.preflight_status.value, "skipped")
        self.assertEqual(result.environment_readiness_category.value, "skipped_due_to_compile_error")

    def test_preflight_mode_surfaces_missing_env_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _prepare_workspace(root, env_file=False, project=True)
            scenario_path = _write_scenario(root, _runner_ready_post_scenario())

            with patch("tools.scenario_runner.orchestration.preflight.importlib.util.find_spec", return_value=object()):
                result = ScenarioRevalidationService().validate(
                    ScenarioRevalidationRequest(
                        file_path=scenario_path,
                        validation_mode="preflight",
                        workspace_root=root,
                    )
                )

        self.assertEqual(result.preflight_validation.preflight_status.value, "failed")
        self.assertEqual(result.environment_readiness_category.value, "preflight_blocked")
        self.assertTrue(
            any(issue.issue_type.value == "missing_environment" for issue in result.preflight_validation.issues)
        )

    def test_preflight_mode_surfaces_missing_dependency(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _prepare_workspace(root, env_file=True, project=True)
            scenario_path = _write_scenario(root, _runner_ready_post_scenario())

            with patch("tools.scenario_runner.orchestration.preflight.importlib.util.find_spec", return_value=None):
                result = ScenarioRevalidationService().validate(
                    ScenarioRevalidationRequest(
                        file_path=scenario_path,
                        validation_mode="preflight",
                        workspace_root=root,
                    )
                )

        self.assertEqual(result.preflight_validation.preflight_status.value, "failed")
        self.assertEqual(result.environment_readiness_category.value, "preflight_blocked")
        self.assertTrue(
            any(issue.issue_type.value == "missing_dependency" for issue in result.preflight_validation.issues)
        )

    def test_preflight_mode_surfaces_missing_external_vars_as_blocked(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _prepare_workspace(root, env_file=True, project=True)
            scenario_path = _write_scenario(root, _external_variable_scenario())

            with patch("tools.scenario_runner.orchestration.preflight.importlib.util.find_spec", return_value=object()):
                result = ScenarioRevalidationService().validate(
                    ScenarioRevalidationRequest(
                        file_path=scenario_path,
                        validation_mode="preflight",
                        workspace_root=root,
                    )
                )

        self.assertEqual(result.compile_validation.compile_status.value, "success")
        self.assertEqual(result.preflight_validation.preflight_status.value, "failed")
        self.assertEqual(result.environment_readiness_category.value, "preflight_blocked")
        self.assertTrue(
            any(issue.issue_type.value == "external_variable" for issue in result.preflight_validation.issues)
        )

    def test_preflight_mode_marks_valid_workspace_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _prepare_workspace(root, env_file=True, project=True)
            scenario_path = _write_scenario(root, _runner_ready_post_scenario())

            with patch("tools.scenario_runner.orchestration.preflight.importlib.util.find_spec", return_value=object()):
                result = ScenarioRevalidationService().validate(
                    ScenarioRevalidationRequest(
                        file_path=scenario_path,
                        validation_mode="preflight",
                        workspace_root=root,
                    )
                )

        self.assertEqual(result.preflight_validation.preflight_status.value, "success")
        self.assertEqual(result.environment_readiness_category.value, "preflight_ready")
        self.assertEqual(result.preflight_validation.issues, [])

    def test_cli_preflight_mode_outputs_environment_readiness(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _prepare_workspace(root, env_file=False, project=True)
            scenario_path = _write_scenario(root, _runner_ready_post_scenario())

            with patch("tools.scenario_runner.orchestration.preflight.importlib.util.find_spec", return_value=object()):
                json_stdout = io.StringIO()
                with redirect_stdout(json_stdout):
                    json_code = cli.main(
                        [
                            "--validate-scenario",
                            "--path",
                            str(scenario_path),
                            "--mode",
                            "preflight",
                            "--workspace-root",
                            str(root),
                        ]
                    )
                json_payload = json.loads(json_stdout.getvalue())

                text_stdout = io.StringIO()
                with redirect_stdout(text_stdout):
                    text_code = cli.main(
                        [
                            "--validate-scenario",
                            "--path",
                            str(scenario_path),
                            "--mode",
                            "preflight",
                            "--workspace-root",
                            str(root),
                            "--output-format",
                            "text",
                        ]
                    )
                text_output = text_stdout.getvalue()

        self.assertEqual(json_code, 0)
        self.assertEqual(json_payload["preflight_status"], "failed")
        self.assertEqual(json_payload["readiness_category"], "preflight_blocked")
        self.assertTrue(json_payload["preflight_validation"]["issues"])
        self.assertEqual(text_code, 0)
        self.assertIn("Status: preflight_blocked", text_output)
        self.assertIn("Preflight: failed", text_output)
        self.assertIn("Preflight issues:", text_output)

    def test_directory_revalidation_compile_mode_summarizes_runner_ready_and_failures(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "good.md"
            bad = root / "bad.md"
            good.write_text(_compile_runner_ready_get_scenario(), encoding="utf-8")
            bad.write_text(_unsupported_expectation_scenario(), encoding="utf-8")

            result = ScenarioDirectoryRevalidationService().validate(
                ScenarioDirectoryRevalidationRequest(
                    directory_path=root,
                    validation_mode="compile",
                    workspace_root=root,
                )
            )

        self.assertEqual(result.status.value, "ERROR")
        self.assertEqual(result.scenario_count, 2)
        self.assertEqual(result.failure_count, 1)
        self.assertEqual(result.readiness_counts["compile_valid_runner_ready"], 1)
        self.assertEqual(result.readiness_counts["compile_blocked"], 1)
        self.assertTrue(any(str(item["file_path"]).endswith("bad.md") for item in result.failure_items))

    def test_cli_validate_scenario_dir_outputs_json_and_text(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "good.md").write_text(_compile_runner_ready_get_scenario(), encoding="utf-8")
            (root / "bad.md").write_text(_unsupported_expectation_scenario(), encoding="utf-8")

            json_stdout = io.StringIO()
            with redirect_stdout(json_stdout):
                json_code = cli.main(
                    ["--validate-scenario-dir", "--path", str(root), "--mode", "compile"]
                )
            json_payload = json.loads(json_stdout.getvalue())

            text_stdout = io.StringIO()
            with redirect_stdout(text_stdout):
                text_code = cli.main(
                    [
                        "--validate-scenario-dir",
                        "--path",
                        str(root),
                        "--mode",
                        "compile",
                        "--output-format",
                        "text",
                    ]
                )
            text_output = text_stdout.getvalue()

        self.assertEqual(json_code, 1)
        self.assertEqual(json_payload["status"], "ERROR")
        self.assertEqual(json_payload["scenario_count"], 2)
        self.assertEqual(json_payload["failure_count"], 1)
        self.assertIn("Status: ERROR", text_output)
        self.assertIn("Validation mode: compile", text_output)
        self.assertIn("Failures:", text_output)
        self.assertEqual(text_code, 1)


def _write_scenario(root: Path, content: str) -> Path:
    path = root / "scenario.md"
    path.write_text(content, encoding="utf-8")
    return path


def _prepare_workspace(root: Path, *, env_file: bool, project: bool) -> None:
    if project:
        (root / "code" / "demo").mkdir(parents=True)
    if env_file:
        env_dir = root / "env"
        env_dir.mkdir(parents=True)
        (env_dir / "demo.env").write_text("", encoding="utf-8")
    api_tool_dir = root / "tools" / "api"
    api_tool_dir.mkdir(parents=True)
    (api_tool_dir / "run_request.py").write_text("# test tool entrypoint\n", encoding="utf-8")


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


def _runner_ready_post_scenario() -> str:
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
- HTTP 201

## Final expectations

- HTTP 201
""".lstrip()


def _compile_runner_ready_get_scenario() -> str:
    return """
# Scenario: Get User

## Project
code/demo

## Environment
env/demo.env

## Notes
Auth strategy required: no.
Request body required: no.
DB verification required: no.

## Steps

### Step 1
Type: api
Name: get user
Method: GET
Path: /users/1
Expected:
- HTTP 200

## Final expectations

- HTTP 200
""".lstrip()


def _unsupported_expectation_scenario() -> str:
    return """
# Scenario: Unsupported Expectation

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
- user should be created successfully

## Final expectations

- user should be created successfully
""".lstrip()


def _external_variable_scenario() -> str:
    return """
# Scenario: Get User

## Project
code/demo

## Environment
env/demo.env

## Steps

### Step 1
Type: api
Name: get user
Method: GET
Path: /users/{{user_id}}
Expected:
- HTTP 200

## Final expectations

- HTTP 200
""".lstrip()


def _future_capture_dependency_scenario() -> str:
    return """
# Scenario: Future Capture

## Project
code/demo

## Environment
env/demo.env

## Steps

### Step 1
Type: api
Name: get user too early
Method: GET
Path: /users/{{user_id}}
Expected:
- HTTP 200

### Step 2
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
Capture:
- response.id -> user_id
Expected:
- HTTP 201

## Final expectations

- HTTP 200
""".lstrip()


def _missing_tenant_negative_flow_scenario() -> str:
    return """
# Scenario: Missing Tenant Negative Flow

## Project
code/demo

## Environment
env/demo.env

## Notes
Auth strategy required: no.
Request body required: no.
DB verification required: yes.

## Steps

### Step 1
Type: api
Name: get missing tenant
Method: GET
Path: /api/internal/v1/tenants/00000000-0000-4000-8000-000000000404
Expected:
- HTTP 404

### Step 2
Type: db
Name: verify tenant remains absent
SQL:
```sql
SELECT id
FROM tenants
WHERE id = '00000000-0000-4000-8000-000000000404'
```
Params:
```json
{}
```
Expected:
- no rows exist

## Final expectations

- HTTP 404
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
