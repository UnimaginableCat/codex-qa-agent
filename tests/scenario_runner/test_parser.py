from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.scenario_runner.parser import MarkdownScenarioParser, ScenarioParseError


class MarkdownScenarioParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = MarkdownScenarioParser()

    def test_fenced_json_blocks_inside_step_are_parsed(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: JSON Blocks

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Steps

                ### Step 1
                Type: api
                Name: create item
                Method: POST
                Path: /items
                Headers:
                ```json
                {
                  "Content-Type": "application/json",
                  "X-Note": "## Not a section"
                }
                ```
                Body:
                ```json
                {
                  "name": "abc",
                  "nested": {"value": 1}
                }
                ```
                Expected:
                - HTTP 200
                """,
            )

            scenario = self.parser.parse(scenario_path)

        self.assertEqual(scenario.steps[0].api.headers["X-Note"], "## Not a section")
        self.assertEqual(scenario.steps[0].api.body["nested"]["value"], 1)

    def test_api_retry_block_is_parsed_as_step_config(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Retry Config

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Steps

                ### Step 1
                Type: api
                Name: duplicate position
                Method: POST
                Path: /positions/1/duplicate/
                Retry:
                  enabled: true
                  max_attempts: 3
                  backoff_seconds: 2
                  backoff_multiplier: 2
                  retry_on:
                    - read_timeout
                    - connect_timeout
                    - connection_error
                  retry_on_statuses:
                    - 502
                    - 503
                    - 504
                """,
            )

            scenario = self.parser.parse(scenario_path)

        retry = scenario.steps[0].api.retry
        self.assertEqual(
            retry,
            {
                "enabled": True,
                "max_attempts": 3,
                "backoff_seconds": 2,
                "backoff_multiplier": 2,
                "retry_on": ["read_timeout", "connect_timeout", "connection_error"],
                "retry_on_statuses": [502, 503, 504],
            },
        )

    def test_fenced_sql_block_inside_db_step_is_parsed(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: SQL Block

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Steps

                ### Step 1
                Type: db
                Name: verify row
                SQL:
                ```sql
                ## Not a markdown section
                -- ### Step 99 is not a real step
                SELECT id, name
                FROM categories
                WHERE id = :id
                ```
                Params:
                ```json
                {"id": 10}
                ```
                Expected:
                - one row exists
                """,
            )

            scenario = self.parser.parse(scenario_path)

        self.assertIn("WHERE id = :id", scenario.steps[0].db.sql)
        self.assertIn("## Not a markdown section", scenario.steps[0].db.sql)
        self.assertEqual(len(scenario.steps), 1)
        self.assertEqual(scenario.steps[0].db.params["id"], 10)

    def test_duplicate_top_level_section_fails_clearly(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Duplicate Section

                ## Project
                code/demo

                ## Project
                code/other
                """,
            )

            with self.assertRaisesRegex(ScenarioParseError, "Duplicate top-level section"):
                self.parser.parse(scenario_path)

    def test_duplicate_step_field_fails_clearly(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Duplicate Field

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Steps

                ### Step 1
                Type: api
                Type: db
                Name: bad step
                Method: GET
                Path: /demo
                """,
            )

            with self.assertRaisesRegex(ScenarioParseError, "duplicate field 'type'"):
                self.parser.parse(scenario_path)

    def test_malformed_json_block_fails_clearly(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Bad JSON

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Steps

                ### Step 1
                Type: api
                Name: bad json
                Method: POST
                Path: /demo
                Body:
                ```json
                {"name": }
                ```
                """,
            )

            with self.assertRaisesRegex(ScenarioParseError, "invalid JSON in 'body'"):
                self.parser.parse(scenario_path)

    def test_db_step_missing_sql_fails_clearly(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Missing SQL

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Steps

                ### Step 1
                Type: db
                Name: missing sql
                """,
            )

            with self.assertRaisesRegex(ScenarioParseError, "DB step missing 'SQL:'"):
                self.parser.parse(scenario_path)

    def test_malformed_sql_fence_fails_clearly(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Bad SQL Fence

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Steps

                ### Step 1
                Type: db
                Name: bad sql fence
                SQL:
                ```sql
                SELECT 1
                """,
            )

            with self.assertRaisesRegex(ScenarioParseError, "malformed fenced block for 'sql'"):
                self.parser.parse(scenario_path)

    def test_api_step_without_required_fields_fails_clearly(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Missing Required Fields

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Steps

                ### Step 1
                Type: api
                Method: GET
                Path: /demo
                """,
            )

            with self.assertRaisesRegex(ScenarioParseError, "missing 'Name:'"):
                self.parser.parse(scenario_path)

    def test_multiple_steps_parse_with_stable_boundaries(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Multiple Steps

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Steps

                ### Step 1
                Type: api
                Name: first
                Method: GET
                Path: /first

                ### Step 2
                Type: db
                Name: second
                SQL:
                ```sql
                SELECT 1
                ```
                """,
            )

            scenario = self.parser.parse(scenario_path)

        self.assertEqual([step.step_number for step in scenario.steps], [1, 2])
        self.assertEqual(scenario.steps[0].api.path, "/first")
        self.assertEqual(scenario.steps[1].db.sql, "SELECT 1")

    def test_variables_section_records_unsupported_transform_for_preflight(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Bad Variable Transform

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - run_suffix = generated:run_suffix
                - email_suffix = derived:run_suffix|slugify

                ## Steps

                ### Step 1
                Type: api
                Name: first
                Method: GET
                Path: /users/{{email_suffix}}
                """,
            )

            scenario = self.parser.parse(scenario_path)

        self.assertTrue(scenario.metadata["variables_validation_errors"])
        self.assertIn("unsupported transform", scenario.metadata["variables_validation_errors"][0])

    def test_variables_section_records_ambiguous_prose_for_preflight(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Prose Variable

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Variables
                - email_suffix = the lowercase form of `run_suffix`

                ## Steps

                ### Step 1
                Type: api
                Name: first
                Method: GET
                Path: /users/{{email_suffix}}
                """,
            )

            scenario = self.parser.parse(scenario_path)

        self.assertTrue(scenario.metadata["variables_validation_errors"])
        self.assertIn("ambiguous untyped value", scenario.metadata["variables_validation_errors"][0])

    def test_comments_blank_lines_and_trailing_notes_do_not_corrupt_steps(self) -> None:
        with TemporaryDirectory() as tmp:
            scenario_path = self._write_scenario(
                Path(tmp),
                """
                # Scenario: Comments

                ## Project
                code/demo

                ## Environment
                env/demo.env

                ## Steps

                <!-- setup note before first step -->

                ### Step 1
                Type: api
                Name: first
                Method: GET
                Path: /first

                <!-- trailing note after fields -->
                """,
            )

            scenario = self.parser.parse(scenario_path)

        self.assertEqual(len(scenario.steps), 1)
        self.assertEqual(scenario.steps[0].api.path, "/first")
        self.assertTrue(scenario.steps[0].metadata["parse_warnings"])

    def test_compiled_plan_slug_does_not_collide_for_same_name_cases(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_path = self._write_scenario(root / "first", self._minimal_scenario("Same Name"))
            second_path = self._write_scenario(root / "second", self._minimal_scenario("Same Name"))

            first = self.parser.parse(first_path)
            second = self.parser.parse(second_path)

        self.assertNotEqual(first.scenario_slug, second.scenario_slug)
        self.assertTrue(first.scenario_slug.startswith("same-name-"))
        self.assertTrue(second.scenario_slug.startswith("same-name-"))

    def test_long_scenario_slug_is_shortened_stably_for_filesystem_safety(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            long_name = "Very Long Scenario Name " * 20
            scenario_path = self._write_scenario(root / ("nested-" * 10), self._minimal_scenario(long_name))

            first = self.parser.parse(scenario_path)
            second = self.parser.parse(scenario_path)

        self.assertLessEqual(len(first.scenario_slug), 120)
        self.assertEqual(first.scenario_slug, second.scenario_slug)
        self.assertTrue(first.scenario_slug.startswith("very-long-scenario-name"))

    @staticmethod
    def _write_scenario(root: Path, content: str) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        scenario_path = root / "scenario.md"
        scenario_path.write_text(_dedent(content), encoding="utf-8")
        return scenario_path

    @staticmethod
    def _minimal_scenario(name: str) -> str:
        return f"""
        # Scenario: {name}

        ## Project
        code/demo

        ## Environment
        env/demo.env

        ## Steps

        ### Step 1
        Type: api
        Name: first
        Method: GET
        Path: /first
        """


def _dedent(value: str) -> str:
    lines = value.strip("\n").splitlines()
    non_empty_lines = [line for line in lines if line.strip()]
    indent = min((len(line) - len(line.lstrip())) for line in non_empty_lines) if non_empty_lines else 0
    return "\n".join(line[indent:] for line in lines) + "\n"


if __name__ == "__main__":
    unittest.main()
