"""Failure cases for the chronological forecast audit."""

import unittest
from datetime import date

import duckdb

from python_pipeline.time_validation import audit_horizon


class TimeValidationTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.con.execute("""CREATE TABLE historic_snapshots(
            restaurant_code VARCHAR, item_code VARCHAR, first_sale_date DATE,
            cutoff DATE)""")
        self.con.execute("""INSERT INTO historic_snapshots VALUES
            ('R1', 'I1', '2025-01-01', '2025-12-01'),
            ('R1', 'I1', '2025-01-01', '2026-01-01'),
            ('R1', 'I1', '2025-01-01', '2026-03-01')""")
        self.reported = {"training_rows": 1, "validation_rows": 1,
                         "test_rows": 1,
                         "target_month_train_end_exclusive": "2026-01-01",
                         "target_month_validation_end_exclusive": "2026-03-01"}

    def tearDown(self):
        self.con.close()

    def test_chronological_boundaries_and_report_counts(self):
        result = audit_horizon(self.con, 1, date(2026, 4, 1), self.reported)
        self.assertEqual([result[key] for key in
                          ("training_rows", "validation_rows", "test_rows")],
                         [1, 1, 1])
        changed = dict(self.reported, test_rows=2)
        with self.assertRaisesRegex(ValueError, "row counts differ"):
            audit_horizon(self.con, 1, date(2026, 4, 1), changed)

    def test_future_first_sale_is_rejected(self):
        self.con.execute("""UPDATE historic_snapshots SET first_sale_date='2026-03-01'
            WHERE cutoff='2026-03-01'""")
        with self.assertRaisesRegex(ValueError, "crosses the forecast origin"):
            audit_horizon(self.con, 1, date(2026, 4, 1), self.reported)


if __name__ == "__main__":
    unittest.main()
