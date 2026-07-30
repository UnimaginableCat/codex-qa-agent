from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.common.errors import ValidationError
from tools.common.statuses import StepStatus
from tools.db.models import DbEnvConfig, QueryStep
from tools.db.services import DatabaseQueryService
from tools.db.sql_params import NamedSqlParamConverter


class NamedSqlParamConverterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.converter = NamedSqlParamConverter()

    def test_named_params_escape_literal_percents_for_psycopg(self) -> None:
        sql = (
            "SELECT :prefix::text AS prefix, '%' AS wildcard, 10 % 3 AS modulo, "
            "FORMAT('%s-%s', first_name, last_name) AS formatted, "
            '"percent%" FROM demo -- 100%\n'
            "WHERE note = $$50%$$ /* 25% */"
        )

        prepared = self.converter.prepare(sql, {"prefix": "AUTOTEST"})

        self.assertEqual(
            prepared.sql,
            (
                "SELECT %(prefix)s::text AS prefix, '%%' AS wildcard, 10 %% 3 AS modulo, "
                "FORMAT('%%s-%%s', first_name, last_name) AS formatted, "
                '"percent%%" FROM demo -- 100%%\n'
                "WHERE note = $$50%%$$ /* 25%% */"
            ),
        )
        self.assertEqual(prepared.params, {"prefix": "AUTOTEST"})
        self.assertEqual(prepared.placeholder_names, ["prefix"])
        self.assertNotIn("%%(prefix)s", prepared.sql)

    def test_query_without_named_params_keeps_standard_sql_unchanged(self) -> None:
        sql = "SELECT * FROM users WHERE display_name LIKE '%AUTOTEST%'"

        prepared = self.converter.prepare(sql, {})

        self.assertEqual(prepared.sql, sql)
        self.assertEqual(prepared.params, {})
        self.assertEqual(prepared.placeholder_names, [])

    def test_named_conversion_preserves_repeated_params_and_colons_in_literals(self) -> None:
        sql = (
            "SELECT ':ignored%' AS literal -- :comment 10%\n"
            "FROM users WHERE id = :user_id OR parent_id = :user_id "
            "AND status = :status AND pattern = '%%'"
        )

        prepared = self.converter.prepare(
            sql,
            {"user_id": 42, "status": "ACTIVE"},
        )

        self.assertEqual(
            prepared.sql,
            (
                "SELECT ':ignored%%' AS literal -- :comment 10%%\n"
                "FROM users WHERE id = %(user_id)s OR parent_id = %(user_id)s "
                "AND status = %(status)s AND pattern = '%%%%'"
            ),
        )
        self.assertEqual(prepared.placeholder_names, ["user_id", "user_id", "status"])

    def test_native_positional_placeholder_path_is_left_unchanged(self) -> None:
        sql = "SELECT * FROM users WHERE id = %s AND name LIKE 'AUTOTEST%%'"
        params = [42]

        prepared = self.converter.prepare(sql, params)

        self.assertEqual(prepared.sql, sql)
        self.assertEqual(prepared.params, params)
        self.assertEqual(prepared.placeholder_names, [])

    def test_missing_named_param_remains_a_validation_error(self) -> None:
        with self.assertRaisesRegex(ValidationError, "Missing SQL params.*status"):
            self.converter.prepare(
                "SELECT * FROM users WHERE id = :user_id AND status = :status",
                {"user_id": 42},
            )


class DatabaseQueryServiceTests(unittest.TestCase):
    def test_named_params_and_literal_percent_reach_cursor_in_psycopg_format(self) -> None:
        cursor = _RecordingCursor()
        connection = _RecordingConnection(cursor)
        service = DatabaseQueryService(sql_param_converter=NamedSqlParamConverter())
        env = DbEnvConfig(database_url="postgresql://user:password@localhost:5432/demo")
        params = {"run_suffix": "20260730"}
        step = QueryStep(
            sql="SELECT 1 WHERE 'AUTOTEST 20260730' LIKE :run_suffix || '%'",
            params=params,
        )

        with patch("tools.db.services.psycopg.connect", return_value=connection):
            result = service.execute(env, step)

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertEqual(
            cursor.execute_args,
            (
                "SELECT 1 WHERE 'AUTOTEST 20260730' LIKE %(run_suffix)s || '%%'",
                params,
            ),
        )

    def test_empty_params_do_not_enable_psycopg_placeholder_parsing(self) -> None:
        cursor = _RecordingCursor()
        connection = _RecordingConnection(cursor)
        service = DatabaseQueryService(sql_param_converter=NamedSqlParamConverter())
        env = DbEnvConfig(database_url="postgresql://user:password@localhost:5432/demo")
        sql = "SELECT 1 WHERE 'AUTOTEST' LIKE '%TEST%'"

        with patch("tools.db.services.psycopg.connect", return_value=connection):
            result = service.execute(env, QueryStep(sql=sql))

        self.assertEqual(result.status, StepStatus.PASS)
        self.assertEqual(cursor.execute_args, (sql,))


class _RecordingCursor:
    def __init__(self) -> None:
        self.execute_args: tuple | None = None

    def __enter__(self) -> "_RecordingCursor":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def execute(self, *args) -> None:
        self.execute_args = args

    @staticmethod
    def fetchall() -> list[dict]:
        return []


class _RecordingConnection:
    def __init__(self, cursor: _RecordingCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_RecordingConnection":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def cursor(self) -> _RecordingCursor:
        return self._cursor


if __name__ == "__main__":
    unittest.main()
