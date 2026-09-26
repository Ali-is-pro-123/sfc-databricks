"""Regression tests for the four auditable menu classes and evidence rules."""

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import SparkSession
from spark_jobs.classify import apply_policy, build_classification, item_summary, score_peers


class ClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.master("local[2]").appName("classification tests")
                     .config("spark.sql.session.timeZone", "UTC").getOrCreate())
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_policy_handles_tricky_economics_and_quality(self):
        schema = ("item_code string, contribution double, quantity_sold long, "
                  "high_demand boolean, high_profitability boolean, "
                  "high_recorded_waste boolean, poor_rating boolean, "
                  "high_promotion_reliance boolean, declining_sales boolean, "
                  "strong_rating boolean, strong_repeat boolean, "
                  "item_age_days long, rating_count long, eligible_customers long")
        rows = [
            ("profit", 100.0, 80, True, True, False, False, False, False, True, True, 90, 30, 50),
            ("volume", 25.0, 80, True, False, False, False, False, False, False, False, 90, 30, 50),
            ("hidden", 40.0, 4, False, True, False, False, False, False, True, False, 90, 10, 10),
            ("loss", -10.0, 100, True, True, False, False, False, False, True, True, 90, 30, 50),
            ("waste", 100.0, 100, True, True, True, False, False, False, True, True, 90, 30, 50),
            ("poor", 100.0, 100, True, True, False, True, False, False, False, True, 90, 30, 50),
            ("promo", 100.0, 100, True, True, False, False, True, True, False, False, 90, 30, 50),
            ("new", 10.0, 2, False, False, False, False, False, False, False, False, 10, 0, 0),
        ]
        actual = {row.item_code: row for row in apply_policy(
            self.spark.createDataFrame(rows, schema)).collect()}
        expected = {"profit": "Profit Driver", "volume": "Volume Driver",
                    "hidden": "Hidden Opportunity", "loss": "Low Performer",
                    "waste": "Low Performer", "poor": "Low Performer",
                    "promo": "Volume Driver", "new": "Low Performer"}
        self.assertEqual({code: row.menu_class for code, row in actual.items()}, expected)
        self.assertEqual(actual["loss"].classification_reason, "negative direct contribution")
        self.assertTrue(actual["new"].provisional_evidence)
        self.assertTrue(actual["hidden"].provisional_evidence)

    def test_item_summary_weights_ratings_and_preserves_money(self):
        schema = ("restaurant_code string, item_code string, item_name string, "
                  "category_code string, category_name string, item_age_days long, "
                  "order_frequency long, quantity_sold long, revenue decimal(12,2), "
                  "cost decimal(12,2), contribution decimal(12,2), rating_count long, "
                  "average_rating double, eligible_customers long, repeat_purchase_rate double, "
                  "wasted_quantity decimal(12,3), promotion_dependency double, "
                  "prior_30d_quantity long, recent_30d_quantity long, "
                  "profitability_as_of date, _month string")
        rows = [
            ("R1", "I", "Dish", "C", "Category", 90, 2, 3, Decimal("30.00"),
             Decimal("20.00"), Decimal("10.00"), 1, 5.0, 2, 0.5,
             Decimal("1.000"), 0.0, 1, 2, date(2025, 7, 1), "2025-07"),
            ("R2", "I", "Dish", "C", "Category", 90, 4, 5, Decimal("50.00"),
             Decimal("40.00"), Decimal("10.00"), 3, 3.0, 6, 0.25,
             Decimal("1.000"), 0.4, 2, 3, date(2025, 7, 1), "2025-07"),
        ]
        item = item_summary(self.spark.createDataFrame(rows, schema)).first()
        self.assertEqual(item.quantity_sold, 8)
        self.assertEqual(item.revenue, Decimal("80.00"))
        self.assertEqual(item.average_rating, 3.5)
        self.assertEqual(item.repeat_purchase_rate, 0.3125)
        self.assertEqual(item.prior_30d_quantity, 3)
        self.assertEqual(item.recent_30d_quantity, 5)
        self.assertEqual(item.repeat_rate_basis, "eligible customer-location weighted")

    def test_peer_scores_use_category_data_not_fixed_sales_cutoffs(self):
        schema = ("item_code string, category_code string, item_age_days long, "
                  "quantity_sold long, order_frequency long, contribution double, "
                  "profit_percentage double, rating_count long, average_rating double, "
                  "eligible_customers long, repeat_purchase_rate double, "
                  "wasted_quantity double, accounted_wastage_percentage double, "
                  "promotion_dependency double, quantity_trend_percentage double")
        rows = [
            ("A", "C", 90, 5, 3, 2.0, 10.0, 20, 3.0, 20, 0.1, 1.0, 16.7, 0.1, -10.0),
            ("B", "C", 90, 20, 12, 15.0, 30.0, 20, 4.0, 20, 0.3, 0.0, 0.0, 0.2, 10.0),
            ("C", "C", 90, 40, 25, 40.0, 50.0, 20, 5.0, 20, 0.5, 0.0, 0.0, 0.3, 20.0),
        ]
        result = {r.item_code: r for r in score_peers(
            self.spark.createDataFrame(rows, schema), ["category_code"]).collect()}
        self.assertLess(result["A"].demand_score, result["C"].demand_score)
        self.assertLess(result["A"].profitability_score, result["C"].profitability_score)
        self.assertTrue(result["A"].high_recorded_waste)
        self.assertTrue(result["A"].poor_rating)
        self.assertEqual(result["C"].peer_count, 3)

    def test_reused_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(ValueError, "unused output"):
                build_classification(self.spark, root / "source", root / "report.json",
                                     existing, root / "reports")


if __name__ == "__main__":
    unittest.main()
