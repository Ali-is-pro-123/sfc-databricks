"""Regression checks for churn-review coverage and abstention rules."""

import json
import unittest
from pathlib import Path

import duckdb


class ChurnRiskTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.output = root / "parquet_data" / "step36-full" / "churn_risk.parquet"
        self.report = root / "processed_data" / "step36-full" / "churn_risk_report.json"
        if not self.output.is_file() or not self.report.is_file():
            self.skipTest("Full churn-review output is not available")
        self.con = duckdb.connect()

    def test_population_and_period_conservation(self):
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["checks"]["customers"], 60000)
        self.assertEqual(self.con.execute("SELECT SUM(prior_90_visits+recent_90_visits) FROM read_parquet(?)", [str(self.output)]).fetchone()[0],
                         report["checks"]["window_eligible_visits"])
        self.assertEqual(self.con.execute("SELECT COUNT(DISTINCT customer_code) FROM read_parquet(?)", [str(self.output)]).fetchone()[0], 60000)

    def test_abstention_and_high_priority_policy(self):
        self.assertEqual(self.con.execute("""SELECT COUNT(*) FROM read_parquet(?) WHERE
            (lifetime_visits=0 AND churn_review_band<>'No Purchase History')
            OR (lifetime_visits>0 AND NOT sufficient_history AND churn_review_band<>'Insufficient History')
            OR (churn_review_band='High Review Priority' AND NOT
                (sufficient_history AND (stale_recency OR
                (recency_days>45 AND declining_frequency AND declining_monetary))))""",
            [str(self.output)]).fetchone()[0], 0)

    def test_signal_ratios_are_null_without_prior_denominator(self):
        self.assertEqual(self.con.execute("""SELECT COUNT(*) FROM read_parquet(?) WHERE
            (prior_90_visits=0 AND visit_frequency_ratio IS NOT NULL)
            OR (prior_90_spend=0 AND monetary_ratio IS NOT NULL)""",
            [str(self.output)]).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
