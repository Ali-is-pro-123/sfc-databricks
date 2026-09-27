"""Regression checks for location comparison definitions and verified inputs."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.location_intelligence import load_reports


class LocationIntelligenceTests(unittest.TestCase):
    def test_customer_repeat_is_local_and_requires_two_eligible_visits(self):
        con = duckdb.connect()
        con.execute("""CREATE TABLE order_features AS SELECT * FROM (VALUES
            ('R1','C1',TRUE), ('R1','C1',TRUE), ('R2','C1',TRUE),
            ('R1','C2',TRUE), ('R1','C3',FALSE))
            t(restaurant_code,customer_code,customer_metric_eligible)""")
        sql = (Path(__file__).parent / "sql" / "location_intelligence.sql").read_text(encoding="utf-8")
        con.execute(sql.split("CREATE TEMP VIEW order_location")[0])
        self.assertEqual(con.execute("""SELECT eligible_customers, eligible_customer_orders,
            repeat_customers FROM customer_location WHERE restaurant_code='R1'""").fetchone(),
            (2, 3, 1))
        self.assertEqual(con.execute("""SELECT eligible_customers, repeat_customers
            FROM customer_location WHERE restaurant_code='R2'""").fetchone(), (1, 0))

    def test_report_cutoff_and_status_are_required(self):
        with tempfile.TemporaryDirectory() as root:
            from python_pipeline.location_intelligence import REPORTS
            for relative in REPORTS.values():
                path = Path(root) / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"status": "passed", "as_of_exclusive": "2026-07-01",
                                            "window_days": 90}), encoding="utf-8")
            load_reports(Path(root), date(2026, 7, 1))
            bad = Path(root) / REPORTS["slow"]
            bad.write_text(json.dumps({"status": "passed", "as_of_exclusive": "2026-06-01",
                                       "window_days": 90}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cutoff differs"):
                load_reports(Path(root), date(2026, 7, 1))


if __name__ == "__main__":
    unittest.main()
