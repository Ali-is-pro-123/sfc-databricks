"""Temporal feature and metric edge cases for monthly wastage risk."""

import unittest
from pathlib import Path

import duckdb

from python_pipeline.wastage_risk import score


class WastageRiskTests(unittest.TestCase):
    def test_score_handles_single_class_and_rejects_invalid_probability(self):
        result = score([0, 0], [0.1, 0.2])
        self.assertIsNone(result["average_precision"])
        self.assertIsNone(result["roc_auc"])
        with self.assertRaisesRegex(ValueError, "Invalid risk scores"):
            score([0, 1], [0.2, 1.2])

    def test_future_features_use_only_previous_months(self):
        con = duckdb.connect()
        con.execute("""CREATE TABLE wastage_daily(
            restaurant_code VARCHAR,item_code VARCHAR,category_code VARCHAR,
            business_date DATE,sold_quantity DOUBLE,wasted_quantity DOUBLE,
            promoted_sold_quantity DOUBLE,prepared_quantity DOUBLE)""")
        con.execute("""INSERT INTO wastage_daily VALUES
            ('R1','I1','C1','2026-04-01',10,1,0,2),
            ('R1','I1','C1','2026-05-01',20,5,2,7),
            ('R1','I1','C1','2026-06-01',30,0,0,0)""")
        sql = (Path(__file__).parent / "sql" / "wastage_risk.sql").read_text(encoding="utf-8")
        con.execute(sql)
        row = con.execute("""SELECT prior_3m_sold,prior_3m_wasted,
            prior_3m_high_waste_months,prior_month_sold,waste_event
            FROM monthly_risk WHERE month_start='2026-07-01'""").fetchone()
        self.assertEqual(row, (60, 6, 1, 30, None))
        con.close()


if __name__ == "__main__":
    unittest.main()
