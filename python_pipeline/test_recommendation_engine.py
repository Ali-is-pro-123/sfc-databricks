"""Regression checks for review-only recommendation coverage and safety gates."""

import json
import unittest
from pathlib import Path

import duckdb


class RecommendationEngineTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.output = root / "parquet_data" / "step37-full" / "recommendation_candidates.parquet"
        self.report = root / "processed_data" / "step37-full" / "recommendation_engine_report.json"
        if not self.output.is_file() or not self.report.is_file():
            self.skipTest("Full recommendation output is not available")
        self.con = duckdb.connect()

    def test_counts_and_unique_keys(self):
        report = json.loads(self.report.read_text(encoding="utf-8"))
        expected = report["checks"]["candidates"]
        self.assertEqual(sum(report["checks"]["by_type"].values()), expected)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(self.output)]).fetchone()[0], expected)
        duplicates = self.con.execute("""SELECT COUNT(*) FROM (
            SELECT recommendation_type,scope,restaurant_code,subject_code,related_code
            FROM read_parquet(?) GROUP BY 1,2,3,4,5 HAVING COUNT(*)>1)""", [str(self.output)]).fetchone()[0]
        self.assertEqual(duplicates, 0)

    def test_evidence_and_abstention(self):
        self.assertEqual(self.con.execute("""SELECT COUNT(*) FROM read_parquet(?) WHERE
            evidence_json IS NULL OR try_cast(evidence_json AS JSON) IS NULL
            OR source_steps IS NULL OR recommended_action IS NULL""", [str(self.output)]).fetchone()[0], 0)
        types = {r[0] for r in self.con.execute("SELECT DISTINCT recommendation_type FROM read_parquet(?)", [str(self.output)]).fetchall()}
        self.assertNotIn("increase_stock_before_predicted_hourly_peak", types)
        self.assertNotIn("automatic_price_change", types)
        self.assertNotIn("automatic_item_removal", types)

    def test_hidden_opportunities_are_not_provisional(self):
        root = Path(__file__).resolve().parents[1]
        menu = str(root / "parquet_data" / "step34-full" / "location_menu_items.parquet")
        bad = self.con.execute("""SELECT COUNT(*) FROM read_parquet(?) c
            JOIN read_parquet(?) m ON c.restaurant_code=m.restaurant_code AND c.subject_code=m.item_code
            WHERE c.recommendation_type='promote_hidden_opportunity'
              AND (m.location_menu_class<>'Hidden Opportunity' OR m.provisional_evidence
                   OR m.direct_margin_percentage<30 OR m.average_rating<4)""",
            [str(self.output), menu]).fetchone()[0]
        self.assertEqual(bad, 0)


if __name__ == "__main__":
    unittest.main()
