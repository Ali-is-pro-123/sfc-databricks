"""Regression cases for exploratory metrics and aggregation grains."""

import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import functions as F
from spark_jobs import test_integration as fixtures
from spark_jobs.eda import TABLES, check_totals, prepare_views, rankings, run_eda
from spark_jobs.integrate import SQL_ROOT


class EDATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.IntegrationTests.setUpClass()
        base = fixtures.IntegrationTests
        cls.spark, cls.sources = base.spark, dict(base.sources)
        cls.sources["menu_items"] = cls.sources["menu_items"].withColumn(
            "introduced_on", F.lit("2025-01-01").cast("date"))
        cls.sources["menu_items"].createOrReplaceTempView("menu_items")
        empty = cls.spark.createDataFrame([], "_raw_json string, _errors array<string>")
        from spark_jobs.integrate import order_coverage
        cls.coverage = order_coverage(cls.sources["orders"], base.fact, empty,
                                      cls.sources["restaurants"])
        cls.views = prepare_views(cls.spark, cls.sources, base.fact, cls.coverage,
                                  base.daily, "2025-01-05")
        cls.tables = {}
        for name, (sql_file, _) in TABLES.items():
            frame = cls.spark.sql((SQL_ROOT / sql_file).read_text(encoding="utf-8"))
            cls.tables[name] = frame.cache()
            frame.count()

    @classmethod
    def tearDownClass(cls):
        for frame in cls.tables.values():
            frame.unpersist()
        for frame in cls.views.values():
            frame.unpersist()
        cls.spark.stop()

    def item(self, code):
        return self.tables["items"].filter(F.col("item_code") == code).first()

    def test_sales_and_money_are_not_multiplied(self):
        checks = check_totals(self.views, self.tables)
        self.assertEqual(checks["completed_line_totals"]["revenue"], Decimal("39.00"))
        self.assertEqual(checks["completed_line_totals"]["quantity"], 4)
        self.assertEqual(checks["completed_header_count"], 2)
        self.assertEqual(checks["sales_bearing_order_count"], 1)

    def test_zero_sale_item_and_category_distinct_orders(self):
        self.assertEqual(self.item("I3").quantity_sold, 0)
        self.assertIsNone(self.item("I3").margin_percentage)
        self.assertIsNone(self.item("I3").average_rating)
        self.assertEqual(self.tables["categories"].first().order_count, 1)
        self.assertEqual(sum(r.order_count for r in self.tables["items"].collect()), 2)

    def test_rating_and_waste_observations_have_separate_grains(self):
        self.assertEqual(self.item("I1").rating_count, 1)
        self.assertEqual(self.item("I1").average_rating, Decimal("4.0000"))
        self.assertEqual(self.item("I1").wasted_quantity, Decimal("3.000"))
        self.assertEqual(self.item("I1").waste_record_count, 2)
        self.assertEqual(float(self.item("I1").waste_share_of_accounted_portions), 50.0)

    def test_promotion_attribution_and_cancelled_order(self):
        promoted = self.tables["promotions"].filter("has_line_promotion").first()
        unpromoted = self.tables["promotions"].filter("NOT has_line_promotion").first()
        self.assertEqual(promoted.revenue, Decimal("20.00"))
        self.assertEqual(unpromoted.revenue, Decimal("19.00"))
        self.assertEqual(self.tables["channels"].first().completed_header_count, 2)

    def test_local_time_bins_and_empty_headers(self):
        hour = self.tables["hours"].filter("local_hour = 1").first()
        self.assertEqual(hour.order_count, 1)
        self.assertEqual(self.tables["weekdays"].filter("iso_weekday = 4").first().order_count, 1)
        self.assertEqual(self.tables["months"].first().local_month, "2025-01")
        self.assertEqual(self.tables["location_days"].filter("date = '2025-01-02'").first().completed_header_count, 2)

    def test_rankings_are_deterministic_and_rating_threshold_is_honest(self):
        ranked = rankings(self.tables["items"], self.tables["categories"],
                          self.tables["hours"], self.tables["weekdays"],
                          self.tables["months"], self.tables["locations"],
                          self.tables["channels"], self.tables["promotions"], 2, 3)
        self.assertEqual(ranked["items"]["top_selling"][0]["item_code"], "I1")
        self.assertEqual(ranked["items"]["lowest_selling"][0]["item_code"], "I3")
        self.assertEqual(ranked["items"]["best_rated"], [])
        self.assertEqual(ranked["items"]["poorly_rated"], [])

    def test_cutoff_excludes_future_rating_and_date(self):
        earlier = prepare_views(self.spark, self.sources, fixtures.IntegrationTests.fact,
                                self.coverage, fixtures.IntegrationTests.daily, "2025-01-03")
        self.assertEqual(earlier["ratings"].count(), 0)
        self.assertEqual(earlier["daily"].filter("date >= '2025-01-03'").count(), 0)
        for frame in earlier.values():
            frame.unpersist()

    def test_failed_upstream_and_output_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad_report = root / "integration.json"
            bad_report.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be passed"):
                run_eda(self.spark, root / "source", bad_report, root / "out", root / "reports",
                        "2025-01-05")
            with self.assertRaisesRegex(ValueError, "unused"):
                run_eda(self.spark, root / "source", bad_report, root, root / "reports",
                        "2025-01-05")
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
