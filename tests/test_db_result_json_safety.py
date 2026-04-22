from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.common import ExecutionResult, StepStatus
from tools.db.models import QueryData


class DbResultJsonSafetyTests(unittest.TestCase):
    def test_uuid_in_query_rows_is_json_safe(self) -> None:
        row_id = UUID("12345678-1234-5678-1234-567812345678")

        payload = self._query_payload([{"id": row_id}])

        self.assertEqual(payload["query"]["rows"][0]["id"], str(row_id))
        json.dumps(payload, ensure_ascii=False)

    def test_datetime_date_and_time_in_query_rows_are_iso_strings(self) -> None:
        created_at = datetime(2026, 4, 22, 10, 11, 12, 123456, tzinfo=timezone.utc)
        business_date = date(2026, 4, 22)
        business_time = time(10, 11, 12, 123456)

        payload = self._query_payload(
            [
                {
                    "created_at": created_at,
                    "business_date": business_date,
                    "business_time": business_time,
                }
            ]
        )

        row = payload["query"]["rows"][0]
        self.assertEqual(row["created_at"], created_at.isoformat())
        self.assertEqual(row["business_date"], business_date.isoformat())
        self.assertEqual(row["business_time"], business_time.isoformat())
        json.dumps(payload, ensure_ascii=False)

    def test_decimal_in_query_rows_is_exact_string(self) -> None:
        amount = Decimal("12345.678900")

        payload = self._query_payload([{"amount": amount}])

        self.assertEqual(payload["query"]["rows"][0]["amount"], "12345.678900")
        json.dumps(payload, ensure_ascii=False)

    def test_nested_query_result_structures_are_json_safe(self) -> None:
        row_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        created_at = datetime(2026, 4, 22, 10, 11, 12, tzinfo=timezone.utc)

        payload = self._query_payload(
            [
                {
                    "events": [
                        {
                            "id": row_id,
                            "created_at": created_at,
                            "amounts": (Decimal("10.50"), Decimal("20.75")),
                            "related_ids": {row_id},
                        }
                    ]
                }
            ]
        )

        event = payload["query"]["rows"][0]["events"][0]
        self.assertEqual(event["id"], str(row_id))
        self.assertEqual(event["created_at"], created_at.isoformat())
        self.assertEqual(event["amounts"], ["10.50", "20.75"])
        self.assertEqual(event["related_ids"], [str(row_id)])
        json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _query_payload(rows: list[dict]) -> dict:
        result = ExecutionResult(
            status=StepStatus.PASS,
            message="Query executed successfully",
            details={
                "query": QueryData(row_count=len(rows), rows=rows),
                "debug": {"nested": rows},
            },
        )
        return result.to_dict()


if __name__ == "__main__":
    unittest.main()
