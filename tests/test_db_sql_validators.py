from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.db.errors import SqlSafetyError
from tools.db.validators import ReadOnlySqlValidator, SqlNormalizer


class ReadOnlySqlValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = ReadOnlySqlValidator(normalizer=SqlNormalizer())

    def test_allows_keywords_inside_string_literals_and_comments(self) -> None:
        allowed_sql = [
            "SELECT * FROM tenants WHERE name = 'AUTOTEST Should Not Update Tenant 123';",
            "SELECT * FROM tenants WHERE note LIKE '%delete me%';",
            "SELECT '-- update' AS text;",
            "SELECT '/* delete */' AS text;",
            "SELECT 1 -- update",
            "SELECT 1 /* outer /* update */ still comment */;",
            "SELECT 'It''s not an update';",
            "SELECT '' AS empty_text;",
            (
                "SELECT COUNT(*) FROM users "
                "WHERE display_name LIKE ('AUTOTEST Invalid User ' || :run_suffix || CHR(37));"
            ),
            (
                "SELECT COUNT(*) FROM tenants\n"
                "WHERE name = 'AUTOTEST Missing Tenant Update 123';"
            ),
            (
                "SELECT COUNT(*) FROM tenants\n"
                "WHERE name = 'AUTOTEST Should Not Update Tenant 123';"
            ),
        ]

        for sql in allowed_sql:
            with self.subTest(sql=sql):
                self.validator.validate(sql)

    def test_blocks_mutating_statements(self) -> None:
        blocked_sql = [
            "UPDATE tenants SET name = 'x' WHERE id = 1;",
            "DELETE FROM tenants WHERE id = 1;",
            "WITH t AS (UPDATE tenants SET name = 'x' RETURNING *) SELECT * FROM t;",
            "SELECT * FROM tenants; UPDATE tenants SET name = 'x';",
        ]

        for sql in blocked_sql:
            with self.subTest(sql=sql):
                with self.assertRaises(SqlSafetyError):
                    self.validator.validate(sql)

    def test_ignores_quoted_identifiers_and_dollar_quoted_strings(self) -> None:
        allowed_sql = [
            'SELECT "update" FROM "tenant delete audit";',
            "SELECT $$update$$ AS text;",
            "SELECT $tag$/* delete */ and update$tag$ AS text;",
        ]

        for sql in allowed_sql:
            with self.subTest(sql=sql):
                self.validator.validate(sql)

    def test_blocks_forbidden_keyword_inside_select_cte_body(self) -> None:
        with self.assertRaisesRegex(SqlSafetyError, "Only SELECT queries are allowed|Read-only policy violation"):
            self.validator.validate("WITH t AS (UPDATE tenants SET name = 'x' RETURNING *) SELECT * FROM t;")


if __name__ == "__main__":
    unittest.main()
