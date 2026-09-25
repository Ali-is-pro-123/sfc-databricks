"""Hand-calculated cutoff and feature-policy regression cases."""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import functions as F
from spark_jobs import test_integration as fixtures
from spark_jobs.features import feature_frames, prepare_views
from spark_jobs.integrate import order_coverage


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.IntegrationTests.setUpClass()
        base = fixtures.IntegrationTests
        cls.spark, cls.sources, cls.daily = base.spark, dict(base.sources), base.daily
        cls.sources["menu_items"] = cls.sources["menu_items"].withColumn("introduced_on", F.lit("2024-01-01").cast("date"))
        cls.sources["customers"] = cls.sources["customers"].union(
            cls.sources["customers"].withColumn("code", F.lit("C2")))
        for name, frame in cls.sources.items():
            frame.createOrReplaceTempView(name)
        fact = base.fact.withColumn("customer_code", F.lit("C"))
        extra = (fact.filter("line_code = 'L1'").withColumn("line_code", F.lit("L5"))
                 .withColumn("order_code", F.lit("O4")).withColumn("date", F.lit("2025-01-03").cast("date"))
                 .withColumn("ordered_local_at", F.lit("2025-01-03T01:00:00").cast("timestamp"))
                 .withColumn("rating_code", F.lit(None).cast("string")))
        partial = extra.withColumn("line_code", F.lit("L6")).withColumn("order_code", F.lit("O5"))
        future = extra.withColumn("line_code", F.lit("LF")).withColumn("order_code", F.lit("OF")).withColumn("date", F.lit("2025-01-04").cast("date"))
        cls.fact = fact.unionByName(extra).unionByName(partial).unionByName(future).cache()
        cls.fact.count()
        empty = cls.spark.createDataFrame([], "_raw_json string, _errors array<string>")
        orders = cls.sources["orders"].withColumn("customer_code", F.lit("C"))
        for code in ["O4", "O5"]:
            orders = orders.unionByName(cls.sources["orders"].filter("code = 'O1'")
                .withColumn("code", F.lit(code)).withColumn("customer_code", F.lit("C"))
                .withColumn("ordered_at", F.lit("2025-01-02T20:00:00Z").cast("timestamp")))
        cls.sources["orders"] = orders
        orders.createOrReplaceTempView("orders")
        cls.coverage = order_coverage(orders, cls.fact, empty, cls.sources["restaurants"])
        cls.coverage = cls.coverage.withColumn("coverage_status", F.when(F.col("order_code") == "O5", "partial").otherwise(F.col("coverage_status")))
        cls.outputs, _, _ = feature_frames(cls.spark, cls.sources, cls.fact, cls.coverage, cls.daily, "2025-01-04", 3)
        cls.rows = {}
        for name, frame in cls.outputs.items():
            cls.rows[name] = frame.collect()

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def item(self, code):
        return next(r for r in self.rows["item_location_features"] if r.item_code == code)

    def test_window_financial_totals_and_future_exclusion(self):
        self.assertEqual(sum(r.revenue for r in self.rows["item_location_features"]), Decimal("79.00"))
        self.assertEqual(self.rows["location_features"][0].revenue, Decimal("79.00"))
        self.assertNotIn("OF", [r.order_code for r in self.rows["order_features"]])
        self.assertNotIn("O2", [r.order_code for r in self.rows["order_features"]])

    def test_customer_rfm_excludes_partial_and_empty_orders(self):
        customer = next(r for r in self.rows["customer_features"] if r.customer_code == "C")
        self.assertEqual(customer.frequency, 2)
        self.assertEqual(customer.monetary_value, Decimal("59.00"))
        self.assertEqual(customer.recency_days, 1)
        self.assertEqual(customer.preferred_channel_code, "WEB")
        self.assertEqual(customer.preferred_category_code, "CAT")

    def test_zero_history_customer(self):
        customer = next(r for r in self.rows["customer_features"] if r.customer_code == "C2")
        self.assertEqual(customer.frequency, 0)
        self.assertIsNone(customer.recency_days)
        self.assertIsNone(customer.average_order_value)

    def test_repeat_purchase_and_promotion_attribution(self):
        self.assertEqual(float(self.item("I1").repeat_purchase_rate), 1.0)
        self.assertAlmostEqual(float(self.item("I1").promotion_dependency), 6 / 7)
        self.assertEqual(self.item("I1").order_frequency, 3)

    def test_zero_sales_and_undefined_ratios(self):
        item = self.item("I3")
        self.assertEqual(item.quantity_sold, 0)
        self.assertIsNone(item.profit_percentage)
        self.assertIsNone(item.accounted_wastage_percentage)
        self.assertIsNone(item.repeat_purchase_rate)

    def test_future_rating_is_not_a_purchase_time_feature(self):
        self.assertEqual(self.item("I1").rating_count, 0)
        prepare_views(self.spark, self.sources, self.fact, self.coverage, self.daily, "2025-01-05", 4)
        self.assertEqual(self.spark.table("feature_ratings").count(), 1)

    def test_price_history_uses_only_events_before_cutoff(self):
        item = self.item("I1")
        self.assertEqual(item.latest_unit_price, Decimal("12.00"))
        self.assertEqual(float(item.price_change_percentage), 20.0)
        prepare_views(self.spark, self.sources, self.fact, self.coverage, self.daily, "2025-01-02", 1)
        self.assertEqual(self.spark.table("feature_prices").first().latest_unit_price, Decimal("10.00"))

    def test_basket_coverage_flags_remain_visible(self):
        rows = {r.order_code: r for r in self.rows["order_features"]}
        self.assertFalse(rows["O5"].customer_metric_eligible)
        self.assertEqual(rows["O1"].distinct_items, 2)

    def test_invalid_window_is_refused(self):
        with self.assertRaisesRegex(ValueError, "window-days"):
            prepare_views(self.spark, self.sources, self.fact, self.coverage, self.daily, "2025-01-04", 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
