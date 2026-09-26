"""Focused regression tests for menu profitability periods and evidence flags."""

import sys
import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import SparkSession
from spark_jobs.profitability import build_profitability, performance_frame, period_totals, source_report


class ProfitabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.master("local[2]").appName("profitability tests")
                     .config("spark.sql.session.timeZone", "UTC").getOrCreate())
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_periods_exclude_cancelled_future_and_old_lines(self):
        rows = [
            ("R", "loss", "completed", date(2025, 4, 2), 3, Decimal("30.00")),
            ("R", "loss", "completed", date(2025, 5, 2), 20, Decimal("100.00")),
            ("R", "loss", "completed", date(2025, 6, 1), 40, Decimal("200.00")),
            ("R", "loss", "cancelled", date(2025, 6, 2), 90, Decimal("900.00")),
            ("R", "loss", "completed", date(2025, 7, 1), 90, Decimal("900.00")),
            ("R", "new", "completed", date(2025, 6, 25), 2, Decimal("40.00")),
        ]
        schema = "restaurant_code string, item_code string, status string, date date, quantity long, revenue decimal(12,2)"
        result = {row.item_code: row for row in period_totals(
            self.spark.createDataFrame(rows, schema), "2025-07-01").collect()}
        self.assertEqual(result["loss"].prior_30d_quantity, 20)
        self.assertEqual(result["loss"].recent_30d_quantity, 40)
        self.assertEqual(result["loss"].recent_30d_revenue, Decimal("200.00"))
        self.assertEqual(result["new"].prior_30d_quantity, 0)

    def test_multidimensional_evidence_does_not_turn_volume_into_success(self):
        schema = ("restaurant_code string, item_code string, introduced_on date, "
                  "quantity_sold long, revenue decimal(12,2), cost decimal(12,2), "
                  "contribution decimal(12,2), rating_count long, "
                  "repeat_purchase_rate double, _month string")
        rows = [
            ("R", "loss", date(2025, 1, 1), 100, Decimal("500.00"),
             Decimal("600.00"), Decimal("-100.00"), 0, None, "2025-07"),
            ("R", "new", date(2025, 6, 20), 2, Decimal("40.00"),
             Decimal("10.00"), Decimal("30.00"), 2, 0.5, "2025-07"),
            ("R", "none", date(2025, 1, 1), 0, Decimal("0.00"),
             Decimal("0.00"), Decimal("0.00"), 0, None, "2025-07"),
        ]
        periods = self.spark.createDataFrame([
            ("R", "loss", 20, 40, Decimal("100.00"), Decimal("200.00")),
            ("R", "new", 0, 2, Decimal("0.00"), Decimal("40.00")),
        ], "restaurant_code string, item_code string, prior_30d_quantity long, recent_30d_quantity long, prior_30d_revenue decimal(12,2), recent_30d_revenue decimal(12,2)")
        result = {r.item_code: r for r in performance_frame(
            self.spark.createDataFrame(rows, schema), periods, "2025-07-01").collect()}
        self.assertTrue(result["loss"].negative_contribution)
        self.assertEqual(float(result["loss"].quantity_trend_percentage), 100.0)
        self.assertTrue(result["loss"].rating_unobserved)
        self.assertTrue(result["loss"].repeat_rate_unobserved)
        self.assertIsNone(result["new"].quantity_trend_percentage)
        self.assertEqual(result["new"].prior_30d_exposure_days, 0)
        self.assertEqual(result["new"].recent_30d_exposure_days, 11)
        self.assertTrue(result["none"].trend_unobserved)
        self.assertFalse(result["none"].negative_contribution)

    def test_failed_upstream_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failed.json"
            path.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be passed"):
                source_report(path, "Feature")

    def test_existing_output_is_rejected_before_loading_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(ValueError, "unused output"):
                build_profitability(self.spark, root / "integration", root / "integration.json",
                                    root / "features", root / "features.json", existing,
                                    root / "reports")


if __name__ == "__main__":
    unittest.main()
