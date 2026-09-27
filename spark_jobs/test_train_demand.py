"""Temporal and metric regression checks for the Spark demand-model task."""

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import SparkSession, functions as F
from spark_jobs.train_demand import candidate_models, evaluate, make_snapshots, month_cutoffs


class DemandModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.master("local[2]").appName("demand model tests")
                     .config("spark.sql.session.timeZone", "UTC").getOrCreate())
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def daily(self, future_quantity):
        schema = ("restaurant_code string, item_code string, category_code string, "
                  "date date, sold_quantity long, order_count long, revenue decimal(12,2), "
                  "contribution decimal(12,2), wasted_quantity decimal(12,3), "
                  "rating_count long, rating_sum long")
        rows = [
            ("R", "I", "C", date(2025, 3, 1), 2, 1, Decimal("20.00"),
             Decimal("5.00"), Decimal("0.000"), 0, 0),
            ("R", "I", "C", date(2025, 4, 15), 3, 1, Decimal("30.00"),
             Decimal("8.00"), Decimal("1.000"), 1, 4),
            ("R", "I", "C", date(2025, 5, 15), future_quantity, 2,
             Decimal("40.00"), Decimal("10.00"), Decimal("0.000"), 1, 5),
            ("R", "I", "C", date(2025, 6, 15), 6, 3, Decimal("60.00"),
             Decimal("15.00"), Decimal("0.000"), 0, 0),
        ]
        return self.spark.createDataFrame(rows, schema)

    def test_month_cutoffs_are_calendar_aligned(self):
        self.assertEqual(month_cutoffs(date(2025, 12, 1), date(2026, 3, 1)),
                         [date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)])
        with self.assertRaisesRegex(ValueError, "first-of-month"):
            month_cutoffs(date(2025, 5, 2), date(2025, 7, 1))

    def test_future_target_changes_without_changing_past_features(self):
        args = (date(2025, 5, 1), date(2025, 7, 1), date(2025, 6, 1), date(2025, 7, 1))
        a = make_snapshots(self.spark, self.daily(4), *args)
        b = make_snapshots(self.spark, self.daily(40), *args)
        may_a = a.filter(F.col("cutoff") == F.lit(date(2025, 5, 1))).first()
        may_b = b.filter(F.col("cutoff") == F.lit(date(2025, 5, 1))).first()
        self.assertEqual(may_a.quantity_last_30, may_b.quantity_last_30)
        self.assertEqual(may_a.quantity_last_90, may_b.quantity_last_90)
        self.assertEqual(may_a.rating_mean_last_90, may_b.rating_mean_last_90)
        self.assertEqual(may_a.label, 4.0)
        self.assertEqual(may_b.label, 40.0)
        self.assertEqual(may_a.quantity_last_30, 3.0)
        self.assertEqual(may_a.rating_mean_last_90, 4.0)
        self.assertEqual(may_a.split, "train")
        june = a.filter(F.col("cutoff") == F.lit(date(2025, 6, 1))).first()
        self.assertEqual(june.label, 6.0)
        self.assertEqual(june.quantity_last_30, 4.0)
        self.assertEqual(june.split, "validation")

    def test_metrics_and_three_candidate_algorithms(self):
        rows = [(0.0, 2.0), (4.0, 3.0), (2.0, 2.0)]
        frame = self.spark.createDataFrame(rows, "label double, prediction double")
        metric = evaluate(frame, "prediction")
        self.assertEqual(metric["rows"], 3)
        self.assertAlmostEqual(metric["mae"], 1.0)
        self.assertAlmostEqual(metric["wape"], 0.5)
        self.assertEqual(set(candidate_models()),
                         {"linear_regression", "decision_tree", "random_forest"})


if __name__ == "__main__":
    unittest.main()
