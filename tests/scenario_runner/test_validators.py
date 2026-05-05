from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.scenario_runner.domain.models import ApiStepDefinition, DbStepDefinition, ScenarioStep, ScenarioStepType
from tools.scenario_runner.runtime.validators import ScenarioStepValidator


class ScenarioStepValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = ScenarioStepValidator()

    def test_api_supported_object_expectations(self) -> None:
        payload = {
            "response": {
                "http_status": 200,
                "body": {
                    "id": 123,
                    "name": "abc",
                    "sort_order": 0,
                    "root_category_id": 10,
                    "default_measurement_unit": "pcs",
                    "root": {"id": 123},
                    "items": [{"id": 123}],
                },
            }
        }

        results = self.validator.validate(
            self._api_step(
                [
                    "HTTP 200",
                    "response JSON exists",
                    "response contains field id",
                    "response contains field root_category_id",
                    "response contains field default_measurement_unit",
                    "response contains field id",
                    "response contains field `id`",
                    'response name = "abc"',
                    "response sort_order = 0",
                    "response root_category_id is not null",
                    "response root.id = 123",
                    "response items.0.id = 123",
                ]
            ),
            payload,
        )

        self.assertTrue(all(result.status == StepStatus.PASS for result in results), results)

    def test_api_response_body_exists_supports_binary_or_text_bodies(self) -> None:
        results = self.validator.validate(
            self._api_step(["response body exists"]),
            {
                "response": {
                    "http_status": 200,
                    "body": "<non-text response body omitted: content-type=application/pdf>",
                    "content_length_bytes": 12,
                }
            },
        )

        self.assertEqual(results[0].status, StepStatus.PASS)

    def test_api_response_body_exists_fails_for_zero_length_binary_metadata(self) -> None:
        results = self.validator.validate(
            self._api_step(["response body exists"]),
            {
                "response": {
                    "http_status": 200,
                    "body": "<non-text response body omitted: content-type=application/pdf, bytes=0>",
                    "content_length_bytes": 0,
                }
            },
        )

        self.assertEqual(results[0].status, StepStatus.FAIL)
        self.assertIn("Content length bytes: 0", results[0].detail)

    def test_api_response_body_exists_fails_for_empty_body(self) -> None:
        results = self.validator.validate(
            self._api_step(["response body exists"]),
            {"response": {"http_status": 204, "body": ""}},
        )

        self.assertEqual(results[0].status, StepStatus.FAIL)

    def test_api_response_body_exists_is_supported_by_contract_inspection(self) -> None:
        diagnostics = self.validator.inspect_contract(self._api_step(["response body exists"]))

        self.assertTrue(diagnostics[0].supported)

    def test_api_response_length_expectations_support_nested_bracket_paths(self) -> None:
        payload = self._category_create_payload()

        results = self.validator.validate(
            self._api_step(
                [
                    "response attributes length = 6",
                    "response attributes length >= 6",
                    "response attributes length<7",
                    "response attributes[3].options length = 3",
                    "response attributes.3.options length = 3",
                ]
            ),
            payload,
        )

        self.assertTrue(all(result.status == StepStatus.PASS for result in results), results)

    def test_api_comparison_operators_support_response_fields_and_placeholders(self) -> None:
        payload = {
            "response": {
                "http_status": 200,
                "body": {
                    "id": 1929529,
                    "root_category_id": 233585,
                    "price": 5900.0,
                    "quantity": 7,
                    "name": "AUTOTEST Tire Copy",
                },
            }
        }

        results = self.validator.validate(
            self._api_step(
                [
                    "response id != {{source_position_id}}",
                    "response root_category_id = {{duplicated_price_list_root_category_id}}",
                    "response price >= 5900",
                    "response quantity>5",
                    "response quantity <= 7",
                    'response name != "Original exact name"',
                ]
            ),
            payload,
            variables={
                "source_position_id": 1929528,
                "duplicated_price_list_root_category_id": 233585,
            },
        )

        self.assertTrue(all(result.status == StepStatus.PASS for result in results), results)

    def test_api_response_length_expectation_bad_path_fails_clearly(self) -> None:
        payload = self._category_create_payload()

        results = self.validator.validate(
            self._api_step(["response attributes[9].options length = 3"]),
            payload,
        )

        self.assertEqual(results[0].status, StepStatus.FAIL)
        self.assertIn("index 9 is out of range", results[0].detail)

    def test_api_expectation_placeholders_are_interpolated_before_validation(self) -> None:
        payload = {
            "response": {
                "http_status": 201,
                "body": {
                    "id": 321,
                    "name": "AUTOTEST Attributes Flow run-123",
                },
            }
        }

        results = self.validator.validate(
            self._api_step(
                [
                    "HTTP 201",
                    "response id = {{price_list_id}}",
                    "response name = {{generated_price_list_name}}",
                ]
            ),
            payload,
            variables={
                "price_list_id": 321,
                "generated_price_list_name": "AUTOTEST Attributes Flow run-123",
            },
        )

        self.assertTrue(all(result.status == StepStatus.PASS for result in results), results)

    def test_api_scalar_equality_parses_unquoted_rhs_as_typed_literals(self) -> None:
        payload = {
            "response": {
                "http_status": 200,
                "body": {
                    "id": 1929525,
                    "cost_price": 4200.0,
                    "is_hidden": False,
                    "current_specification_import": None,
                    "unit": {"id": 27},
                    "attributes": [
                        {"option": {"id": 1}},
                        {"option": {"id": 2}},
                        {"option": {"id": 3}},
                        {"option": {"id": 16}},
                    ],
                },
            }
        }

        results = self.validator.validate(
            self._api_step(
                [
                    "response id = 1929525",
                    "response cost_price = 4200.0",
                    "response is_hidden = false",
                    "response current_specification_import = null",
                    "response unit.id = 27",
                    "response attributes[3].option.id = 16",
                ]
            ),
            payload,
        )

        self.assertTrue(all(result.status == StepStatus.PASS for result in results), results)

    def test_api_quoted_scalar_equality_remains_string_strict(self) -> None:
        payload = {
            "response": {
                "http_status": 200,
                "body": {
                    "id": 1929525,
                    "is_hidden": False,
                    "name": "Michelin",
                },
            }
        }

        results = self.validator.validate(
            self._api_step(
                [
                    'response id = "1929525"',
                    'response is_hidden = "false"',
                    'response name = "Michelin"',
                ]
            ),
            payload,
        )

        self.assertEqual(results[0].status, StepStatus.FAIL)
        self.assertEqual(results[1].status, StepStatus.FAIL)
        self.assertEqual(results[2].status, StepStatus.PASS)

    def test_api_equality_preserves_typed_rhs_placeholders(self) -> None:
        payload = {
            "response": {
                "http_status": 200,
                "body": {
                    "id": 1929526,
                    "cost_price": 5900.0,
                    "is_hidden": False,
                    "current_specification_import": None,
                },
            }
        }

        results = self.validator.validate(
            self._api_step(
                [
                    "response id = {{source_position_id}}",
                    "response `id` = `{{source_position_id}}`",
                    "response cost_price = {{expected_cost_price}}",
                    "response is_hidden = {{expected_hidden}}",
                    "response current_specification_import = {{expected_nullable}}",
                ]
            ),
            payload,
            variables={
                "source_position_id": 1929526,
                "expected_cost_price": 5900.0,
                "expected_hidden": False,
                "expected_nullable": None,
            },
        )

        self.assertTrue(all(result.status == StepStatus.PASS for result in results), results)

    def test_api_quoted_placeholder_remains_explicit_string(self) -> None:
        payload = {
            "response": {
                "http_status": 200,
                "body": {
                    "id": 1929526,
                    "name": "Michelin",
                },
            }
        }

        results = self.validator.validate(
            self._api_step(
                [
                    'response id = "{{source_position_id}}"',
                    'response name = "{{brand_name}}"',
                ]
            ),
            payload,
            variables={
                "source_position_id": 1929526,
                "brand_name": "Michelin",
            },
        )

        self.assertEqual(results[0].status, StepStatus.FAIL)
        self.assertEqual(results[1].status, StepStatus.PASS)

    def test_api_supported_array_expectations(self) -> None:
        payload = {
            "response": {
                "http_status": 201,
                "body": [{"id": 123}, {"id": 456}],
            }
        }

        results = self.validator.validate(
            self._api_step(
                [
                    "HTTP 200 or HTTP 201",
                    "response JSON is an array",
                    "array contains item with id = 123",
                ]
            ),
            payload,
        )

        self.assertTrue(all(result.status == StepStatus.PASS for result in results), results)

    def test_api_equality_parses_json_array_literal(self) -> None:
        payload = {
            "response": {
                "http_status": 200,
                "body": {"partner_permissions": []},
            }
        }

        results = self.validator.validate(
            self._api_step(["response partner_permissions = []"]),
            payload,
        )

        self.assertEqual(results[0].status, StepStatus.PASS)

    def test_api_response_field_is_empty_expectation(self) -> None:
        payload = {
            "response": {
                "http_status": 200,
                "body": {"partner_permissions": [], "name": "not-empty"},
            }
        }

        results = self.validator.validate(
            self._api_step(["response partner_permissions is empty", "response name is empty"]),
            payload,
        )

        self.assertEqual(results[0].status, StepStatus.PASS)
        self.assertEqual(results[1].status, StepStatus.FAIL)
        diagnostics = self.validator.inspect_contract(self._api_step(["response partner_permissions is empty"]))
        self.assertTrue(diagnostics[0].supported)

    def test_response_length_without_field_is_blocked_as_ambiguous(self) -> None:
        results = self.validator.validate(
            self._api_step(["response length >= 1"]),
            {"response": {"http_status": 200, "body": [{"id": 123}]}},
        )

        self.assertEqual(results[0].status, StepStatus.BLOCKED)
        self.assertIn("Unsupported expectation rule: response length >= 1", results[0].detail)

    def test_contract_inspection_rejects_ambiguous_root_response_length_assertion(self) -> None:
        diagnostics = self.validator.inspect_contract(self._api_step(["response length >= 1"]))

        self.assertEqual(len(diagnostics), 1)
        self.assertFalse(diagnostics[0].supported)
        self.assertIn("Unsupported expectation rule: response length >= 1", diagnostics[0].detail)

    def test_db_supported_expectations_use_first_row(self) -> None:
        payload = {
            "query": {
                "row_count": 1,
                "rows": [
                    {
                        "root_category_id": 10,
                        "parent_id": None,
                        "is_hidden": False,
                        "name": "Root category for price list: 123",
                    }
                ],
            }
        }

        results = self.validator.validate(
            self._db_step(
                [
                    "one row exists",
                    "root_category_id = 10",
                    "parent_id is null",
                    "is_hidden = false",
                    "name starts with Root category for price list:",
                ]
            ),
            payload,
        )

        self.assertTrue(all(result.status == StepStatus.PASS for result in results), results)
        self.assertTrue(all("first row" in result.detail.lower() for result in results[1:]), results)

    def test_db_no_rows_exist_expectation_passes_for_empty_result(self) -> None:
        results = self.validator.validate(
            self._db_step(["no rows exist"]),
            {"query": {"row_count": 0, "rows": []}},
        )

        self.assertEqual(results[0].status, StepStatus.PASS)
        self.assertIn("Actual row_count: 0", results[0].detail)

    def test_db_comparison_operators_support_scalar_fields(self) -> None:
        payload = {
            "query": {
                "row_count": 1,
                "rows": [
                    {
                        "duplicated_attr_value_count": 6,
                        "same_attr_code_count": 0,
                        "copied_position_id": 1929529,
                        "source_position_id": 1929528,
                    }
                ],
            }
        }

        results = self.validator.validate(
            self._db_step(
                [
                    "duplicated_attr_value_count >= 5",
                    "same_attr_code_count=0",
                    "copied_position_id!=1929528",
                    "duplicated_attr_value_count<7",
                    "duplicated_attr_value_count <= 6",
                ]
            ),
            payload,
        )

        self.assertTrue(all(result.status == StepStatus.PASS for result in results), results)

    def test_db_expectations_normalize_inline_code_rules_fields_and_values(self) -> None:
        payload = {
            "query": {
                "row_count": 1,
                "rows": [
                    {
                        "price_list_name": "AUTOTEST Attributes Flow run-123",
                        "root_category_id": 233573,
                        "sort_order": 0,
                        "default_measurement_unit_id": 7,
                        "root_parent_id": None,
                        "root_is_root": True,
                        "root_is_hidden": False,
                    }
                ],
            }
        }

        results = self.validator.validate(
            self._db_step(
                [
                    "`price_list_name = AUTOTEST Attributes Flow run-123`",
                    "`root_category_id = 233573`",
                    "`sort_order = 0`",
                    "`default_measurement_unit_id is not null`",
                    "`root_parent_id is null`",
                    "`root_is_root = true`",
                    "`root_is_hidden = false`",
                    "`price_list_name` = `AUTOTEST Attributes Flow run-123`",
                ]
            ),
            payload,
        )

        self.assertTrue(all(result.status == StepStatus.PASS for result in results), results)

    def test_db_backticked_numeric_expected_value_is_compared_as_number(self) -> None:
        payload = {
            "query": {
                "row_count": 1,
                "rows": [
                    {
                        "invalid_user_count": 0,
                    }
                ],
            }
        }

        results = self.validator.validate(
            self._db_step(
                [
                    "one row exists",
                    "`invalid_user_count` = `0`",
                ]
            ),
            payload,
        )

        self.assertTrue(all(result.status == StepStatus.PASS for result in results), results)

    def test_db_expectation_with_inner_backticks_is_parsed_as_comparison_not_unsupported(self) -> None:
        payload = {
            "query": {
                "row_count": 1,
                "rows": [
                    {
                        "email": "autotest.primary.20260422080300@example.com",
                    }
                ],
            }
        }

        results = self.validator.validate(
            self._db_step(
                [
                    "`email = the lowercase form of `run_suffix` and must be used for emails`",
                ]
            ),
            payload,
        )

        self.assertEqual(results[0].status, StepStatus.FAIL)
        self.assertNotIn("Unsupported expectation rule", results[0].detail)
        self.assertIn("Expected value", results[0].detail)

    def test_contract_inspection_rejects_ambiguous_response_contains_literals(self) -> None:
        diagnostics = self.validator.inspect_contract(
            self._api_step(["response contains {{user_id}}", "response contains AUTOTEST IUC Primary run-1"])
        )

        self.assertEqual(len(diagnostics), 2)
        self.assertTrue(all(not diagnostic.supported for diagnostic in diagnostics))

    def test_response_contains_without_field_keyword_is_blocked(self) -> None:
        results = self.validator.validate(
            self._api_step(["response contains id"]),
            {"response": {"body": {"id": 123}}},
        )

        self.assertEqual(results[0].status, StepStatus.BLOCKED)
        self.assertIn("Unsupported expectation rule", results[0].detail)

    def test_unsupported_expectation_returns_structured_blocked_result(self) -> None:
        results = self.validator.validate(self._api_step(["response magically works"]), {"response": {"body": {}}})

        self.assertEqual(results[0].status, StepStatus.BLOCKED)
        self.assertIn("Unsupported expectation rule: response magically works", results[0].detail)
        self.assertEqual(self.validator.final_status(results), StepStatus.BLOCKED)

    def test_contract_inspection_marks_unsupported_expectation_before_runtime(self) -> None:
        diagnostics = self.validator.inspect_contract(self._api_step(["response magically works"]))

        self.assertEqual(len(diagnostics), 1)
        self.assertFalse(diagnostics[0].supported)
        self.assertIn("Unsupported expectation rule: response magically works", diagnostics[0].detail)

    def test_contract_inspection_accepts_no_rows_exist_for_db_steps(self) -> None:
        diagnostics = self.validator.inspect_contract(self._db_step(["no rows exist"]))

        self.assertEqual(len(diagnostics), 1)
        self.assertTrue(diagnostics[0].supported)
        self.assertEqual(diagnostics[0].detail, "Expectation syntax is supported.")

    def test_unsupported_comparison_syntax_does_not_become_missing_path(self) -> None:
        results = self.validator.validate(
            self._api_step(["response id ! = 123", "response name is not equal to original exact name"]),
            {"response": {"body": {"id": 123, "name": "copy"}}},
        )

        self.assertTrue(all(result.status == StepStatus.BLOCKED for result in results), results)
        self.assertTrue(all("Unsupported expectation rule" in result.detail for result in results), results)
        self.assertTrue(all("Missing path segment" not in result.detail for result in results), results)

    def test_missing_field_path_returns_structured_failure(self) -> None:
        results = self.validator.validate(
            self._api_step(["response missing.id = 123"]),
            {"response": {"body": {"id": 123}}},
        )

        self.assertEqual(results[0].status, StepStatus.FAIL)
        self.assertIn("Missing path segment", results[0].detail)

    def test_scalar_json_where_object_expected_returns_structured_failure(self) -> None:
        results = self.validator.validate(
            self._api_step(["response contains field id"]),
            {"response": {"body": "abc"}},
        )

        self.assertEqual(results[0].status, StepStatus.FAIL)
        self.assertIn("actual type is str", results[0].detail)

    def test_non_array_where_array_expected_returns_structured_failure(self) -> None:
        results = self.validator.validate(
            self._api_step(["array contains item with id = 123"]),
            {"response": {"body": {"id": 123}}},
        )

        self.assertEqual(results[0].status, StepStatus.FAIL)
        self.assertIn("Actual response body type: dict", results[0].detail)

    def test_zero_db_rows_returns_structured_failure_for_field_check(self) -> None:
        results = self.validator.validate(
            self._db_step(["parent_id is null"]),
            {"query": {"row_count": 0, "rows": []}},
        )

        self.assertEqual(results[0].status, StepStatus.FAIL)
        self.assertIn("No DB rows available", results[0].detail)

    @staticmethod
    def _api_step(expected: list[str]) -> ScenarioStep:
        return ScenarioStep(
            step_id="step-api",
            step_number=1,
            title="API step",
            step_type=ScenarioStepType.API,
            api=ApiStepDefinition(expected=expected),
        )

    @staticmethod
    def _db_step(expected: list[str]) -> ScenarioStep:
        return ScenarioStep(
            step_id="step-db",
            step_number=1,
            title="DB step",
            step_type=ScenarioStepType.DB,
            db=DbStepDefinition(expected=expected),
        )

    @staticmethod
    def _category_create_payload() -> dict:
        return {
            "response": {
                "http_status": 201,
                "body": {
                    "attributes": [
                        {"id": 10, "name": "Brand"},
                        {"id": 11, "name": "Color"},
                        {"id": 12, "name": "Size"},
                        {
                            "id": 13,
                            "name": "Season",
                            "options": [
                                {"id": 1, "name": "Spring"},
                                {"id": 2, "name": "Summer"},
                                {"id": 3, "name": "Winter"},
                            ],
                        },
                        {"id": 14, "name": "Material"},
                        {"id": 15, "name": "Country"},
                    ]
                },
            }
        }


if __name__ == "__main__":
    unittest.main()
