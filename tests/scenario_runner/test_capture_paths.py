from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.scenario_runner.runtime.executors import ApiStepExecutor, CaptureResolutionError
from tools.scenario_runner.runtime.interpolator import PlaceholderInterpolator


class CapturePathResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = _InspectableApiStepExecutor()

    def test_capture_resolves_bracket_index_in_response_body_array(self) -> None:
        payload = {"response": {"body": {"attributes": [{"id": 29}, {"id": 32}]}}}

        result = self.executor.resolve_capture_value(payload, "response.body.attributes[0].id")

        self.assertEqual(result, 29)

    def test_capture_resolves_second_bracket_indexed_item(self) -> None:
        payload = {"response": {"body": {"items": [{"name": "a"}, {"name": "b"}]}}}

        result = self.executor.resolve_capture_value(payload, "response.body.items[1].name")

        self.assertEqual(result, "b")

    def test_capture_resolves_root_rows_bracket_index(self) -> None:
        payload = {"rows": [{"id": 100}]}

        result = self.executor.resolve_capture_value(payload, "rows[0].id")

        self.assertEqual(result, 100)

    def test_capture_keeps_existing_dotted_numeric_list_index(self) -> None:
        payload = {"response": {"body": {"attributes": [{"id": 29}]}}}

        result = self.executor.resolve_capture_value(payload, "response.body.attributes.0.id")

        self.assertEqual(result, 29)

    def test_capture_resolves_nested_bracket_indexes(self) -> None:
        payload = {"payload": {"data": {"categories": [{"attributes": [[{"code": "x"}]]}]}}}

        result = self.executor.resolve_capture_value(payload, "payload.data.categories[0].attributes[0][0].code")

        self.assertEqual(result, "x")

    def test_capture_reports_bracket_index_out_of_range(self) -> None:
        payload = {"response": {"body": {"attributes": [{"id": 29}]}}}

        with self.assertRaisesRegex(CaptureResolutionError, "index 3 is out of range"):
            self.executor.resolve_capture_value(payload, "response.body.attributes[3].id")

    def test_capture_reports_missing_key_before_bracket_index(self) -> None:
        payload = {"response": {"body": {}}}

        with self.assertRaisesRegex(CaptureResolutionError, "Missing path segment 'attributes'"):
            self.executor.resolve_capture_value(payload, "response.body.attributes[0].id")

    def test_capture_reports_expected_list_for_bracket_index(self) -> None:
        payload = {"response": {"body": {"attributes": {"id": 29}}}}

        with self.assertRaisesRegex(CaptureResolutionError, "Expected list at response.body.attributes"):
            self.executor.resolve_capture_value(payload, "response.body.attributes[0].id")

    def test_capture_regression_for_category_create_attributes(self) -> None:
        payload = {
            "response": {
                "body": {
                    "attributes": [
                        {"id": 29, "name": "Brand"},
                        {"id": 32, "name": "Season"},
                    ]
                }
            }
        }

        result = self.executor.resolve_capture_value(payload, "response.body.attributes[0].id")

        self.assertEqual(result, 29)


class _InspectableApiStepExecutor(ApiStepExecutor):
    def __init__(self) -> None:
        super().__init__(workspace_root=Path.cwd(), interpolator=PlaceholderInterpolator())

    def resolve_capture_value(self, payload: dict, expression: str):
        return self._resolve_capture_value(payload, expression)


if __name__ == "__main__":
    unittest.main()
