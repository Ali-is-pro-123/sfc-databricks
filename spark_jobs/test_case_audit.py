"""Fixture checks for every difficult SRS menu case and time boundary."""

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import SparkSession
from spark_jobs.case_audit import CASE_COLUMNS, case_summary, item_evidence, local_evidence, run_audit, seasonal_evidence


class CaseAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.master("local[2]").appName("case audit tests")
                     .config("spark.sql.session.timeZone", "UTC").getOrCreate())
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_repeated_seasonal_pattern_uses_completed_comparable_windows(self):
        rows = [
            ("S", "completed", date(2025, 2, 1), 10),
            ("S", "completed", date(2025, 5, 1), 70),
            ("S", "completed", date(2026, 2, 1), 10),
            ("S", "completed", date(2026, 5, 1), 80),
            ("X", "completed", date(2025, 2, 1), 10),
            ("X", "completed", date(2025, 5, 1), 70),
            ("X", "completed", date(2026, 2, 1), 70),
            ("X", "completed", date(2026, 5, 1), 10),
            ("S", "cancelled", date(2026, 2, 1), 100),
            ("S", "completed", date(2026, 7, 1), 100),
        ]
        frame = self.spark.createDataFrame(rows, "item_code string, status string, date date, quantity long")
        evidence = {r.item_code: r for r in seasonal_evidence(frame, date(2026, 7, 1)).collect()}
        self.assertTrue(evidence["S"].seasonal_pattern_observed)
        self.assertEqual(evidence["S"].seasonal_half, "second")
        self.assertFalse(evidence["X"].seasonal_pattern_observed)
        self.assertEqual(evidence["S"].current_second_quantity, 80)

    def test_all_ten_case_flags_and_local_evidence(self):
        item_schema = ("item_code string, item_name string, menu_class string, "
                       "high_demand boolean, high_profitability boolean, "
                       "high_recorded_waste boolean, strong_rating boolean, "
                       "poor_rating boolean, high_promotion_reliance boolean, "
                       "promotion_dependency double, quantity_sold long, "
                       "contribution double, rating_count long, item_age_days long, "
                       "quantity_trend_percentage double, provisional_evidence boolean")
        items = self.spark.createDataFrame([
            ("A", "Loss dish", "Low Performer", True, False, True, False, True, True,
             0.7, 100, -20.0, 20, 90, -10.0, False),
            ("B", "Seasonal dish", "Hidden Opportunity", False, True, False, False,
             False, False, 0.1, 20, 40.0, 20, 600, 10.0, False),
            ("C", "Rated dish", "Low Performer", False, False, False, True,
             False, False, 0.1, 20, 2.0, 20, 90, 0.0, False),
            ("N", "New dish", "Low Performer", False, False, False, False,
             False, False, 0.0, 2, 0.0, 0, 10, None, True),
        ], item_schema)
        local = self.spark.createDataFrame([
            ("A", "R1", "Low Performer", 10, 20, 0.8),
            ("A", "R2", "Volume Driver", 10, 20, 0.2),
            ("B", "R1", "Hidden Opportunity", 20, 10, 0.2),
            ("C", "R1", "Low Performer", 20, 10, 0.2),
            ("N", "R1", "Low Performer", 2, 2, 0.0),
        ], "item_code string, restaurant_code string, menu_class string, quantity_sold long, order_frequency long, weekend_order_ratio double")
        local = local_evidence(local, items, date(2026, 7, 1))
        season = self.spark.createDataFrame([
            ("B", True, date(2025, 1, 1), 10, 70, 10, 80),
        ], "item_code string, seasonal_pattern_observed boolean, seasonal_prior_start date, prior_first_quantity long, prior_second_quantity long, current_first_quantity long, current_second_quantity long")
        evidence = item_evidence(items, local, season, date(2026, 7, 1))
        summary = case_summary(evidence)
        self.assertEqual(set(summary), set(CASE_COLUMNS))
        self.assertTrue(all(summary[name]["count"] > 0 for name in CASE_COLUMNS))
        actual = {r.item_code: r for r in evidence.collect()}
        self.assertTrue(actual["A"].case_high_sales_loss)
        self.assertTrue(actual["A"].case_location_difference)
        self.assertTrue(actual["A"].case_weekend_dominant)
        self.assertTrue(actual["B"].case_possible_seasonal_pattern)
        self.assertTrue(actual["N"].case_new_insufficient_history)
        self.assertEqual(actual["A"].menu_class, "Low Performer")

    def test_existing_output_rejected_before_input_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(ValueError, "unused output"):
                run_audit(self.spark, root / "class", root / "class.json",
                          root / "profit.json", root / "integration",
                          root / "integration.json", existing, root / "reports")


if __name__ == "__main__":
    unittest.main()
