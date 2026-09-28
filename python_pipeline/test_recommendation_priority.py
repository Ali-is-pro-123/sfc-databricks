"""Check priority policy boundaries and one-to-one evidence coverage."""

import json
import unittest
from pathlib import Path

import duckdb

from python_pipeline.recommendation_priority import decide_priority


class RecommendationPriorityTests(unittest.TestCase):
    def test_waste_critical_requires_both_cost_and_rate(self):
        high_cost = {"waste_cost": 11000}
        self.assertEqual(decide_priority("review_preparation_quantity",
                                         {"accounted_wastage_percentage": 40}, high_cost)[0], "Critical")
        self.assertEqual(decide_priority("review_preparation_quantity",
                                         {"accounted_wastage_percentage": 39.9}, high_cost)[0], "High")
        self.assertEqual(decide_priority("review_preparation_quantity",
                                         {"accounted_wastage_percentage": 40}, {"waste_cost": 9999})[0], "High")

    def test_price_review_uses_exposure_not_predicted_gain(self):
        result = decide_priority("review_price_sensitivity", {}, {"revenue": 50000})
        self.assertEqual(result[0], "High")
        self.assertIn("revenue", result[3])
        self.assertIn("not causal", result[4])

    def test_full_output_covers_every_explanation(self):
        root = Path(__file__).resolve().parents[1]
        evidence = root / "parquet_data" / "step38-full" / "recommendation_evidence.parquet"
        priorities = root / "parquet_data" / "step39-full" / "prioritized_recommendations.parquet"
        report_path = root / "processed_data" / "step39-full" / "recommendation_priority_report.json"
        if not priorities.is_file():
            self.skipTest("Full priority output is not available")
        con = duckdb.connect()
        expected = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(evidence)]).fetchone()[0]
        rows = con.execute("""SELECT candidate_id,priority,impact_exposure,impact_unit,
            impact_basis,priority_reason FROM read_parquet(?)""", [str(priorities)]).fetchall()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), expected)
        self.assertEqual(len({row[0] for row in rows}), expected)
        self.assertEqual(sum(report["priority_counts"].values()), expected)
        for _, priority, exposure, unit, basis, reason in rows:
            self.assertIn(priority, ("Low", "Medium", "High", "Critical"))
            self.assertGreaterEqual(exposure, 0)
            self.assertTrue(unit and basis and reason)


if __name__ == "__main__":
    unittest.main()
