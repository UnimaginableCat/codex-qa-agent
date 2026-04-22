from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.scenario_runner.parser import ScenarioParseError
from tools.scenario_runner.parsing.markdown_document import MarkdownSection
from tools.scenario_runner.parsing.step_blocks import split_step_blocks
from tools.scenario_runner.parsing.step_fields import parse_step_block
from tools.scenario_runner.parsing.step_ir import StepBlock


class StepBoundaryParsingTests(unittest.TestCase):
    def test_multiple_step_blocks_keep_stable_boundaries(self) -> None:
        section = MarkdownSection(
            name="Steps",
            line_number=10,
            lines=[
                "",
                "### Step 1",
                "Type: api",
                "Name: first",
                "Method: GET",
                "Path: /first",
                "",
                "### Step 2",
                "Type: db",
                "Name: second",
                "SQL:",
                "```sql",
                "SELECT 1",
                "```",
            ],
        )

        blocks, warnings = split_step_blocks(section, Path("scenario.md"))

        self.assertFalse(warnings)
        self.assertEqual(
            [(block.step_number, block.line_number, len(block.lines)) for block in blocks],
            [(1, 2, 5), (2, 8, 6)],
        )

    def test_heading_like_text_inside_fence_does_not_create_step_block(self) -> None:
        section = MarkdownSection(
            name="Steps",
            line_number=1,
            lines=[
                "### Step 1",
                "Type: db",
                "Name: verify",
                "SQL:",
                "```sql",
                "-- ### Step 99",
                "-- ## Not a section",
                "SELECT 1",
                "```",
            ],
        )

        blocks, warnings = split_step_blocks(section, Path("scenario.md"))
        draft = parse_step_block(blocks[0], error_type=ScenarioParseError)

        self.assertFalse(warnings)
        self.assertEqual(len(blocks), 1)
        self.assertIn("-- ### Step 99", str(draft.fields["sql"]))


class StepFieldExtractionTests(unittest.TestCase):
    def test_api_step_fields_are_extracted(self) -> None:
        draft = parse_step_block(
            StepBlock(
                step_number=1,
                line_number=2,
                lines=[
                    "Type: api",
                    "Name: create item",
                    "Method: post",
                    "Path: /items",
                    "Headers:",
                    "```json",
                    '{"Content-Type": "application/json"}',
                    "```",
                    "Body:",
                    "```json",
                    '{"name": "abc"}',
                    "```",
                    "Capture:",
                    "- response.body.id -> created_id",
                    "Expected:",
                    "- HTTP 200",
                ],
            ),
            error_type=ScenarioParseError,
        )

        self.assertEqual(draft.step_number, 1)
        self.assertEqual(draft.line_number, 2)
        self.assertEqual(draft.fields["type"], "api")
        self.assertEqual(draft.fields["method"], "post")
        self.assertEqual(draft.fields["path"], "/items")
        self.assertEqual(draft.fields["headers"], {"Content-Type": "application/json"})
        self.assertEqual(draft.fields["body"], {"name": "abc"})
        self.assertEqual(draft.fields["capture"], ["response.body.id -> created_id"])
        self.assertEqual(draft.fields["expected"], ["HTTP 200"])

    def test_db_step_fields_are_extracted(self) -> None:
        draft = parse_step_block(
            StepBlock(
                step_number=2,
                line_number=8,
                lines=[
                    "Type: db",
                    "Name: verify item",
                    "SQL:",
                    "```sql",
                    "SELECT id",
                    "FROM items",
                    "WHERE id = :id",
                    "```",
                    "Params:",
                    "```json",
                    '{"id": "{{created_id}}"}',
                    "```",
                    "Expected:",
                    "- one row exists",
                ],
            ),
            error_type=ScenarioParseError,
        )

        self.assertEqual(draft.fields["type"], "db")
        self.assertIn("FROM items", str(draft.fields["sql"]))
        self.assertEqual(draft.fields["params"], {"id": "{{created_id}}"})
        self.assertEqual(draft.fields["expected"], ["one row exists"])

    def test_multiline_unfenced_field_content_stops_at_next_known_field(self) -> None:
        draft = parse_step_block(
            StepBlock(
                step_number=3,
                line_number=20,
                lines=[
                    "Type: db",
                    "Name: multiline sql",
                    "SQL:",
                    "SELECT id",
                    "FROM items",
                    "WHERE active = true",
                    "Expected:",
                    "- rows exist",
                ],
            ),
            error_type=ScenarioParseError,
        )

        self.assertEqual(draft.fields["sql"], "SELECT id\nFROM items\nWHERE active = true")
        self.assertEqual(draft.fields["expected"], ["rows exist"])

    def test_retry_capture_and_expected_blocks_are_extracted(self) -> None:
        draft = parse_step_block(
            StepBlock(
                step_number=4,
                line_number=30,
                lines=[
                    "Type: api",
                    "Name: retrying request",
                    "Method: GET",
                    "Path: /items",
                    "Retry:",
                    "  enabled: true",
                    "  max_attempts: 3",
                    "  retry_on_statuses:",
                    "    - 502",
                    "    - 503",
                    "Capture:",
                    "- response.body.id -> item_id",
                    "Expected: HTTP 200",
                    "- response contains field id",
                ],
            ),
            error_type=ScenarioParseError,
        )

        self.assertEqual(
            draft.fields["retry"],
            {"enabled": True, "max_attempts": 3, "retry_on_statuses": [502, 503]},
        )
        self.assertEqual(draft.fields["capture"], ["response.body.id -> item_id"])
        self.assertEqual(draft.fields["expected"], ["HTTP 200", "response contains field id"])

    def test_invalid_step_format_errors_remain_compatible_by_meaning(self) -> None:
        with self.assertRaisesRegex(ScenarioParseError, "duplicate field 'type'"):
            parse_step_block(
                StepBlock(
                    step_number=5,
                    line_number=40,
                    lines=[
                        "Type: api",
                        "Type: db",
                    ],
                ),
                error_type=ScenarioParseError,
            )

        with self.assertRaisesRegex(ScenarioParseError, "malformed fenced block for 'sql'"):
            parse_step_block(
                StepBlock(
                    step_number=6,
                    line_number=50,
                    lines=[
                        "Type: db",
                        "Name: bad fence",
                        "SQL:",
                        "```sql",
                        "SELECT 1",
                    ],
                ),
                error_type=ScenarioParseError,
            )


if __name__ == "__main__":
    unittest.main()
