from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.scenario_runner.domain.models import (
    ApiStepDefinition,
    ScenarioDefinition,
    ScenarioStep,
    ScenarioStepType,
    ScenarioVariableDefinition,
    ScenarioVariableSource,
)
from tools.scenario_runner.orchestration.preflight import PreflightCheckResult, PreflightResult
from tools.scenario_runner.orchestration.services import ScenarioRunnerService
from tools.scenario_runner.parser import MarkdownScenarioParser
from tools.scenario_runner.runtime.executors import ApiStepExecutor, DbStepExecutor
from tools.scenario_runner.runtime.interpolator import InterpolationError, PlaceholderInterpolator


class ScenarioVariableTests(unittest.TestCase):
    def test_interpolator_resolves_placeholders_in_mapping_keys(self) -> None:
        interpolated = PlaceholderInterpolator().interpolate(
            {
                "template_inputs": [
                    {
                        "variable_values": {
                            "{{thickness_code}}": "{{thickness_value}}",
                            "static_{{suffix}}": "kept",
                        }
                    }
                ]
            },
            {
                "thickness_code": "tpl_var_abc123",
                "thickness_value": "7",
                "suffix": "key",
            },
        )

        self.assertEqual(
            interpolated["template_inputs"][0]["variable_values"],
            {"tpl_var_abc123": "7", "static_key": "kept"},
        )

    def test_interpolator_blocks_mapping_key_collisions_after_interpolation(self) -> None:
        with self.assertRaisesRegex(InterpolationError, "mapping key collision"):
            PlaceholderInterpolator().interpolate(
                {"{{first_key}}": "first", "{{second_key}}": "second"},
                {"first_key": "same", "second_key": "same"},
            )

    def test_variables_section_is_parsed_preserved_and_not_unknown(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Variables

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - company_guid = env:COMPANY_GUID
                - run_suffix = generated
                - literal_name = literal:fixed value
                - generated_price_list_name = template:AUTOTEST Attributes Flow {{run_suffix}}

                ## Steps

                ### Step 1
                Type: api
                Name: create
                Method: POST
                Path: /companies/{{company_guid}}/price-lists
                """,
            )

            scenario = MarkdownScenarioParser().parse(scenario_path)

        self.assertEqual(
            [variable.name for variable in scenario.variables],
            ["company_guid", "run_suffix", "literal_name", "generated_price_list_name"],
        )
        self.assertEqual(scenario.variables[0].source, ScenarioVariableSource.ENV)
        self.assertEqual(scenario.variables[1].source, ScenarioVariableSource.GENERATED)
        self.assertEqual(scenario.variables[2].source, ScenarioVariableSource.LITERAL)
        self.assertEqual(scenario.variables[3].source, ScenarioVariableSource.TEMPLATE)
        self.assertFalse(
            any("Unknown scenario section 'Variables'" in warning for warning in scenario.metadata["parse_warnings"])
        )
        self.assertIn("variables", scenario.to_dict())
        self.assertEqual(scenario.to_dict()["variables"][0]["env_name"], "COMPANY_GUID")

    def test_initial_context_resolves_run_suffix_env_and_template_variables(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-123\n")
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._scenario(root), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.run_variables["company_guid"], "company-123")
        self.assertIn("run_suffix", executor.run_variables)
        self.assertTrue(str(executor.run_variables["run_suffix"]).startswith("202"))
        self.assertEqual(
            executor.run_variables["generated_price_list_name"],
            f"AUTOTEST Attributes Flow {executor.run_variables['run_suffix']}",
        )

    def test_prose_like_variables_block_before_runtime(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-partial\n")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Partial Variables

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - company_guid comes from environment
                - run_suffix generated dynamically
                - generated_price_list_name derived from run suffix
                - @@@ this is not a variable definition

                ## Steps

                ### Step 1
                Type: api
                Name: create price list
                Method: POST
                Path: /companies/{{company_guid}}/price-lists
                Headers:
                ```json
                {"X-Company-Guid": "{{company_guid}}"}
                ```
                Params:
                ```json
                {"companyGuid": "{{company_guid}}"}
                ```
                Body:
                ```json
                {"name": "{{generated_price_list_name}}"}
                ```
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_VariableAwarePreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(executor.execute_count, 0)
        self.assertTrue(scenario.metadata["variables_validation_errors"])
        self.assertTrue(any("compile_variables_section_invalid" in issue for issue in summary.tooling_issues))
        self.assertTrue(any("company_guid comes from environment" in warning for warning in summary.details["warnings"]))
        self.assertEqual(summary.details["executed_step_count"], 0)
        self.assertEqual(summary.details["compile_statuses"], [StepStatus.BLOCKED.value])

    def test_variables_section_supports_tables_backticks_and_dash_assignments(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-table\n")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Variable Formats

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                | Variable | Source | Env | Value |
                | --- | --- | --- | --- |
                | company_guid | env | COMPANY_GUID | |
                | unique_suffix | generated | | run_suffix |
                | scenario_run_id | generated | | run_id |
                | generated_name | template | | AUTOTEST {{unique_suffix}} |
                - `literal_name`: "Fixed literal"
                - dashed_template — Item {{unique_suffix}}

                ## Steps

                ### Step 1
                Type: api
                Name: create
                Method: POST
                Path: /companies/{{company_guid}}/items/{{unique_suffix}}
                Body:
                ```json
                {
                  "name": "{{generated_name}}",
                  "literal": "{{literal_name}}",
                  "dash": "{{dashed_template}}",
                  "run": "{{scenario_run_id}}"
                }
                ```
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(
            [variable.name for variable in scenario.variables],
            [
                "company_guid",
                "unique_suffix",
                "scenario_run_id",
                "generated_name",
                "literal_name",
                "dashed_template",
            ],
        )
        self.assertEqual(executor.run_variables["company_guid"], "company-table")
        self.assertEqual(executor.run_variables["scenario_run_id"], summary.run_id)
        self.assertEqual(executor.run_variables["unique_suffix"], summary.run_id.removeprefix("run-"))
        self.assertEqual(
            executor.run_variables["generated_name"],
            f"AUTOTEST {executor.run_variables['unique_suffix']}",
        )
        self.assertEqual(executor.run_variables["literal_name"], "Fixed literal")
        self.assertEqual(
            executor.run_variables["dashed_template"],
            f"Item {executor.run_variables['unique_suffix']}",
        )
        self.assertIn("/companies/company-table/items/", executor.step_payload["path"])

    def test_actor_variable_flows_into_api_step_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Actor Payload

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - actor = literal:api-client

                ## Steps

                ### Step 1
                Type: api
                Name: actor check
                Method: GET
                Path: /health
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.run_variables["actor"], "api-client")
        self.assertEqual(executor.step_payload["actor"], "api-client")

    def test_step_actor_overrides_scenario_actor_for_api_step_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Step Actor Payload

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - actor = literal:founder

                ## Steps

                ### Step 1
                Type: api
                Name: partner action
                Actor: partner
                Method: GET
                Path: /health
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.run_variables["actor"], "founder")
        self.assertEqual(executor.step_payload["actor"], "partner")

    def test_actor_variable_flows_into_db_step_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Actor DB Payload

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - actor = literal:admin

                ## Steps

                ### Step 1
                Type: db
                Name: actor db check
                SQL:
                ```sql
                select 1
                ```
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory(tool_results=[self._db_result([{"value": 1}])])
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.run_variables["actor"], "admin")
        self.assertEqual(executor.step_payload["actor"], "admin")

    def test_step_actor_overrides_scenario_actor_for_db_step_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Step Actor DB Payload

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - actor = literal:founder

                ## Steps

                ### Step 1
                Type: db
                Name: partner db check
                Actor: partner
                SQL:
                ```sql
                select 1
                ```
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory(tool_results=[self._db_result([{"value": 1}])])
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.run_variables["actor"], "founder")
        self.assertEqual(executor.step_payload["actor"], "partner")

    def test_variables_section_supports_generated_template_and_derived_transforms(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Generated As Variables

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - run_suffix = generated:run_suffix
                - email_suffix = derived:run_suffix|lower
                - primary_display_name = template:AUTOTEST User Primary {{run_suffix}}
                - primary_email_mixed_case = template:AUTOTEST.Primary.{{email_suffix}}@Example.COM
                - primary_email_normalized = derived:primary_email_mixed_case|trim|lower
                - missing_user_id = generated:uuid

                ## Steps

                ### Step 1
                Type: api
                Name: create primary
                Method: POST
                Path: /users/{{missing_user_id}}
                Body:
                ```json
                {
                  "displayName": "{{primary_display_name}}",
                  "email": "{{primary_email_mixed_case}}",
                  "expectedEmail": "{{primary_email_normalized}}"
                }
                ```
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(
            [variable.name for variable in scenario.variables],
            [
                "run_suffix",
                "email_suffix",
                "primary_display_name",
                "primary_email_mixed_case",
                "primary_email_normalized",
                "missing_user_id",
            ],
        )
        self.assertEqual(
            executor.run_variables["primary_display_name"],
            f"AUTOTEST User Primary {executor.run_variables['run_suffix']}",
        )
        self.assertEqual(
            executor.run_variables["primary_email_mixed_case"],
            f"AUTOTEST.Primary.{executor.run_variables['run_suffix'].lower()}@Example.COM",
        )
        self.assertEqual(
            executor.run_variables["primary_email_normalized"],
            f"autotest.primary.{executor.run_variables['run_suffix'].lower()}@example.com",
        )
        self.assertEqual(executor.run_variables["email_suffix"], executor.run_variables["run_suffix"].lower())
        self.assertRegex(
            executor.run_variables["missing_user_id"],
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        )
        self.assertEqual(executor.step_payload["body"]["displayName"], executor.run_variables["primary_display_name"])

    def test_integer_transform_preserves_numeric_type_in_exact_request_placeholder(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "PRICE_LIST_ID=20474\n")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Integer Variable

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - target_price_list_id_raw = env:PRICE_LIST_ID
                - target_price_list_id = derived:target_price_list_id_raw|int

                ## Steps

                ### Step 1
                Type: api
                Name: copy category
                Method: POST
                Path: /price-lists/{{target_price_list_id}}/copy-to
                Body:
                ```json
                {
                  "target_price_list_id": "{{target_price_list_id}}",
                  "reference": "price-list-{{target_price_list_id}}"
                }
                ```
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.run_variables["target_price_list_id"], 20474)
        self.assertIsInstance(executor.run_variables["target_price_list_id"], int)
        self.assertEqual(executor.step_payload["path"], "/price-lists/20474/copy-to")
        self.assertEqual(executor.step_payload["body"]["target_price_list_id"], 20474)
        self.assertIsInstance(executor.step_payload["body"]["target_price_list_id"], int)
        self.assertEqual(executor.step_payload["body"]["reference"], "price-list-20474")

    def test_integer_transform_blocks_non_integer_env_value_before_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "PRICE_LIST_ID=20.5\n")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Invalid Integer Variable

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - target_price_list_id_raw = env:PRICE_LIST_ID
                - target_price_list_id = derived:target_price_list_id_raw|int

                ## Steps

                ### Step 1
                Type: api
                Name: copy category
                Method: POST
                Path: /price-lists/copy-to
                Body:
                ```json
                {"target_price_list_id": "{{target_price_list_id}}"}
                ```
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(executor.execute_count, 0)
        self.assertIn("could not be converted to int", summary.steps[0].message)
        self.assertNotIn("20.5", summary.steps[0].message)

    def test_generated_numeric_suffix_resolves_to_digits_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Numeric Suffix

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - numeric_suffix = generated:numeric_suffix
                - telegram_subject = template:700{{numeric_suffix}}

                ## Steps

                ### Step 1
                Type: api
                Name: link telegram
                Method: POST
                Path: /users/u1/identities
                Body:
                ```json
                {"provider": "TELEGRAM", "subject": "{{telegram_subject}}"}
                ```
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertRegex(executor.run_variables["numeric_suffix"], r"^\d+$")
        self.assertRegex(executor.step_payload["body"]["subject"], r"^700\d+$")

    def test_email_suffix_regression_requires_machine_readable_derived_variable(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Email Suffix Regression

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - run_suffix = generated:run_suffix
                - email_suffix = derived:run_suffix|lower
                - primary_email = template:autotest.primary.{{email_suffix}}@example.com

                ## Steps

                ### Step 1
                Type: api
                Name: create user
                Method: POST
                Path: /users
                Body:
                ```json
                {"email": "{{primary_email}}"}
                ```
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertNotIn("lowercase form", executor.step_payload["body"]["email"])
        self.assertEqual(
            executor.step_payload["body"]["email"],
            f"autotest.primary.{executor.run_variables['run_suffix'].lower()}@example.com",
        )

    def test_prose_email_suffix_blocks_with_summary_message_before_runtime(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "")
            scenario_path = self._write_scenario(
                root,
                """
                # Scenario: Bad Email Suffix

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - run_suffix = generated:run_suffix
                - email_suffix = the lowercase form of `run_suffix` and must be used for emails
                - primary_email = template:autotest.primary.{{email_suffix}}@example.com

                ## Steps

                ### Step 1
                Type: api
                Name: create user
                Method: POST
                Path: /users
                Body:
                ```json
                {"email": "{{primary_email}}"}
                ```
                """,
            )
            scenario = MarkdownScenarioParser().parse(scenario_path)
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_VariableAwarePreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)
            summary_json = (summary.run_state_dir / "summary.json").read_text(encoding="utf-8")

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(executor.execute_count, 0)
        self.assertIn("Variables section contains invalid definition", summary.tooling_issues[0])
        self.assertIn("lowercase form", summary.tooling_issues[0])
        self.assertEqual(summary.message, "Scenario compilation failed with status BLOCKED.")
        self.assertTrue(summary.report_path is not None)
        self.assertIn("lowercase form", summary_json)

    def test_step_one_payload_interpolates_path_headers_body_and_params_from_initial_variables(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-456\n")
            executor = _CapturingExecutorFactory()
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._scenario(root), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.step_payload["path"], "/companies/company-456/price-lists")
        self.assertEqual(executor.step_payload["headers"]["X-Company-Guid"], "company-456")
        self.assertEqual(
            executor.step_payload["body"]["name"],
            executor.run_variables["generated_price_list_name"],
        )
        self.assertEqual(executor.step_payload["query_params"]["companyGuid"], "company-456")

    def test_unresolved_initial_variable_returns_blocked_without_step_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-789\n")
            (root / "scenario.md").write_text("# Scenario: Variables Demo\n", encoding="utf-8")
            (root / "code" / "demo").mkdir(parents=True, exist_ok=True)
            (root / "tools" / "api").mkdir(parents=True, exist_ok=True)
            (root / "tools" / "api" / "run_request.py").write_text("# api tool placeholder\n", encoding="utf-8")
            executor = _CapturingExecutorFactory()
            scenario = self._scenario(root)
            scenario.steps[0].api.body["missing"] = "{{missing_variable}}"
            service = ScenarioRunnerService(step_executor_factory=executor)
            with patch("tools.scenario_runner.orchestration.preflight.importlib.util.find_spec", return_value=object()):
                summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(executor.execute_count, 0)
        self.assertEqual(summary.steps, [])
        self.assertEqual(summary.message, "Scenario preflight failed with status BLOCKED.")
        self.assertEqual(summary.details["compile_statuses"], [StepStatus.PASS.value])
        self.assertEqual(summary.details["preflight_statuses"], [StepStatus.BLOCKED.value])
        self.assertTrue(any("external_inputs_resolvable" in issue for issue in summary.tooling_issues))
        self.assertTrue(any("missing_variable" in issue for issue in summary.tooling_issues))

    def test_later_step_can_use_variable_captured_by_step_one_without_initial_block(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-capture\n")
            executor = _CapturingExecutorFactory(
                tool_results=[
                    self._api_result({"id": 123}),
                    self._api_result({"ok": True}),
                ]
            )
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._captured_variable_scenario(root), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.execute_count, 2)
        self.assertTrue(all(result.status == StepStatus.PASS for result in summary.steps[0].expectation_results))
        self.assertEqual(executor.step_payloads[0]["path"], "/companies/company-capture/price-lists")
        self.assertEqual(executor.step_payloads[1]["path"], "/price-lists/123")
        self.assertFalse(any(step.details.get("phase") == "initial_context" for step in summary.steps))

    def test_bracket_index_capture_updates_variables_for_next_step(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-attributes\n")
            executor = _CapturingExecutorFactory(
                tool_results=[
                    self._api_result(
                        {
                            "attributes": [
                                {"id": 29, "name": "Brand"},
                                {"id": 32, "name": "Season"},
                            ]
                        }
                    ),
                    self._api_result({"ok": True}),
                ]
            )
            scenario = self._captured_variable_scenario(root)
            scenario.steps[0].api.capture = ["response.body.attributes[0].id -> brand_attribute_id"]
            scenario.steps[0].api.expected = []
            scenario.steps[1].api.path = "/attributes/{{brand_attribute_id}}"
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.PASS)
        self.assertEqual(executor.execute_count, 2)
        self.assertEqual(executor.step_payloads[1]["path"], "/attributes/29")
        self.assertEqual(summary.steps[0].details["capture_keys"], ["brand_attribute_id"])

    def test_later_step_placeholder_is_deferred_until_that_step_is_active(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-deferred\n")
            executor = _CapturingExecutorFactory(tool_results=[self._api_result({"ok": True})])
            scenario = self._captured_variable_scenario(root)
            scenario.steps[0].api.capture = []
            scenario.steps[0].api.expected = []
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(scenario, workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(executor.execute_count, 1)
        self.assertEqual(summary.steps[0].status, StepStatus.PASS)
        self.assertEqual(summary.steps[1].status, StepStatus.BLOCKED)
        self.assertEqual(summary.steps[1].details["phase"], "step_variable_resolution")
        self.assertIn("price_list_id", summary.steps[1].details["unresolved_variables"])

    def test_failed_producer_marks_dependent_future_step_blocked_not_initial_preflight(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-fail\n")
            executor = _CapturingExecutorFactory(
                tool_results=[
                    {
                        "status": StepStatus.FAIL.value,
                        "message": "create failed",
                        "response": {"http_status": 500, "body": {}},
                    }
                ]
            )
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._captured_variable_scenario(root), workspace_root=root)

        self.assertEqual(executor.execute_count, 1)
        self.assertEqual(summary.steps[0].status, StepStatus.FAIL)
        self.assertEqual(summary.steps[1].status, StepStatus.BLOCKED)
        self.assertEqual(summary.steps[1].details["phase"], "deferred_capture")
        self.assertIn("price_list_id", summary.steps[1].details["unresolved_variables"])

    def test_blocked_producer_marks_dependent_future_step_blocked(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_env(root, "COMPANY_GUID=company-blocked\n")
            executor = _CapturingExecutorFactory(
                tool_results=[
                    {
                        "status": StepStatus.BLOCKED.value,
                        "message": "Request failed: DNS lookup failed",
                        "classification": "connectivity",
                    }
                ]
            )
            service = ScenarioRunnerService(
                step_executor_factory=executor,
                preflight_checker=_PassingPreflightChecker(),
            )

            summary = service.run(self._captured_variable_scenario(root), workspace_root=root)

        self.assertEqual(summary.final_status, StepStatus.BLOCKED)
        self.assertEqual(summary.steps[0].status, StepStatus.BLOCKED)
        self.assertEqual(summary.steps[1].status, StepStatus.BLOCKED)
        self.assertEqual(summary.steps[1].details["phase"], "deferred_capture")
        self.assertIn("price_list_id", summary.steps[1].details["unresolved_variables"])

    @staticmethod
    def _scenario(
        root: Path,
        variables: list[ScenarioVariableDefinition] | None = None,
    ) -> ScenarioDefinition:
        return ScenarioDefinition(
            scenario_path=root / "scenario.md",
            scenario_slug="variables-demo",
            scenario_name="Variables Demo",
            project="code/demo",
            environment="env/demo.env",
            variables=variables
            or [
                ScenarioVariableDefinition(
                    name="company_guid",
                    raw_value="env:COMPANY_GUID",
                    source=ScenarioVariableSource.ENV,
                    env_name="COMPANY_GUID",
                ),
                ScenarioVariableDefinition(
                    name="run_suffix",
                    raw_value="generated:run_suffix",
                    source=ScenarioVariableSource.GENERATED,
                ),
                ScenarioVariableDefinition(
                    name="generated_price_list_name",
                    raw_value="AUTOTEST Attributes Flow {{run_suffix}}",
                    source=ScenarioVariableSource.TEMPLATE,
                ),
            ],
            steps=[
                ScenarioStep(
                    step_id="step-1",
                    step_number=1,
                    title="create price list",
                    step_type=ScenarioStepType.API,
                    api=ApiStepDefinition(
                        method="POST",
                        path="/companies/{{company_guid}}/price-lists",
                        headers={"X-Company-Guid": "{{company_guid}}"},
                        params={"companyGuid": "{{company_guid}}"},
                        body={"name": "{{generated_price_list_name}}"},
                    ),
                )
            ],
        )

    @classmethod
    def _captured_variable_scenario(cls, root: Path) -> ScenarioDefinition:
        scenario = cls._scenario(root)
        scenario.steps[0].api.capture = ["response.body.id -> price_list_id"]
        scenario.steps[0].api.expected = [
            "response contains field id",
            "response id = {{price_list_id}}",
        ]
        scenario.steps.append(
            ScenarioStep(
                step_id="step-2",
                step_number=2,
                title="read price list",
                step_type=ScenarioStepType.API,
                api=ApiStepDefinition(
                    method="GET",
                    path="/price-lists/{{price_list_id}}",
                ),
            )
        )
        return scenario

    @staticmethod
    def _api_result(body: dict) -> dict:
        return {
            "status": StepStatus.PASS.value,
            "message": "ok",
            "response": {"http_status": 200, "body": body},
        }

    @staticmethod
    def _db_result(rows: list[dict]) -> dict:
        return {
            "status": StepStatus.PASS.value,
            "message": "ok",
            "query": {"row_count": len(rows), "rows": rows},
        }

    @staticmethod
    def _prepare_env(root: Path, content: str) -> None:
        (root / "env").mkdir(parents=True, exist_ok=True)
        (root / "env" / "demo.env").write_text(content, encoding="utf-8")

    @staticmethod
    def _write_scenario(root: Path, content: str) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        scenario_path = root / "scenario.md"
        scenario_path.write_text(_dedent(content), encoding="utf-8")
        return scenario_path


class _CapturingExecutorFactory:
    def __init__(self, tool_results: list[dict] | None = None) -> None:
        self.execute_count = 0
        self.step_payload: dict | None = None
        self.step_payloads: list[dict] = []
        self.run_variables: dict | None = None
        self._tool_results = list(
            tool_results
            or [
                {
                    "status": StepStatus.PASS.value,
                    "message": "ok",
                    "response": {"http_status": 200, "body": {"ok": True}},
                }
            ]
        )

    def create(self, step: ScenarioStep, workspace_root: Path) -> "_CapturingStepExecutor":
        if step.step_type == ScenarioStepType.DB:
            return _CapturingDbStepExecutor(workspace_root, self)
        return _CapturingApiStepExecutor(workspace_root, self)

    def next_tool_result(self) -> dict:
        if self._tool_results:
            return self._tool_results.pop(0)
        return {
            "status": StepStatus.PASS.value,
            "message": "ok",
            "response": {"http_status": 200, "body": {"ok": True}},
        }


class _CapturingApiStepExecutor(ApiStepExecutor):
    def __init__(self, workspace_root: Path, owner: _CapturingExecutorFactory) -> None:
        super().__init__(workspace_root=workspace_root, interpolator=PlaceholderInterpolator())
        self._owner = owner

    def execute(self, run_context, scenario_definition, step: ScenarioStep):
        self._owner.execute_count += 1
        self._owner.run_variables = dict(run_context.variables)
        return super().execute(run_context, scenario_definition, step)

    def _invoke_cli(self, env_path: Path, step_file: Path) -> dict:
        self._owner.step_payload = json.loads(step_file.read_text(encoding="utf-8"))
        self._owner.step_payloads.append(self._owner.step_payload)
        return {
            "command": ["test-api"],
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "result": self._owner.next_tool_result(),
        }


class _CapturingDbStepExecutor(DbStepExecutor):
    def __init__(self, workspace_root: Path, owner: _CapturingExecutorFactory) -> None:
        super().__init__(workspace_root=workspace_root, interpolator=PlaceholderInterpolator())
        self._owner = owner

    def execute(self, run_context, scenario_definition, step: ScenarioStep):
        self._owner.execute_count += 1
        self._owner.run_variables = dict(run_context.variables)
        return super().execute(run_context, scenario_definition, step)

    def _invoke_cli(self, env_path: Path, step_file: Path) -> dict:
        self._owner.step_payload = json.loads(step_file.read_text(encoding="utf-8"))
        self._owner.step_payloads.append(self._owner.step_payload)
        return {
            "command": ["test-db"],
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "result": self._owner.next_tool_result(),
        }


class _PassingPreflightChecker:
    @staticmethod
    def run(scenario_definition, workspace_root):
        return PreflightResult(
            checks=[
                PreflightCheckResult(
                    name="test_preflight",
                    status=StepStatus.PASS,
                    message="Test preflight passed.",
                )
            ]
        )


class _VariableAwarePreflightChecker:
    @staticmethod
    def run(scenario_definition, workspace_root):
        errors = scenario_definition.metadata.get("variables_validation_errors", [])
        if errors:
            return PreflightResult(
                checks=[
                    PreflightCheckResult(
                        name="variables_section_valid",
                        status=StepStatus.BLOCKED,
                        message="Variables section contains invalid definition(s); scenario execution was blocked before API/DB runtime.",
                        details={"errors": list(errors)},
                    )
                ]
            )
        return _PassingPreflightChecker.run(scenario_definition, workspace_root)


def _dedent(value: str) -> str:
    lines = value.strip("\n").splitlines()
    non_empty_lines = [line for line in lines if line.strip()]
    indent = min((len(line) - len(line.lstrip())) for line in non_empty_lines) if non_empty_lines else 0
    return "\n".join(line[indent:] for line in lines) + "\n"


if __name__ == "__main__":
    unittest.main()

