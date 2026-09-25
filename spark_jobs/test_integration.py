"""Small adversarial fixtures for integration grains and accounting."""

import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import SparkSession, functions as F
from data_generator.schemas import SCHEMAS, field_type
from spark_jobs.integrate import SQL_ROOT, integrate, load_sources, order_coverage, unique


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.appName("DineIQ integration tests")
                     .config("spark.sql.session.timeZone", "UTC")
                     .config("spark.sql.shuffle.partitions", "2")
                     .config("spark.sql.ansi.enabled", "true").getOrCreate())
        cls.spark.sparkContext.setLogLevel("ERROR")
        fixtures = {
            "restaurants": [dict(code="R", name="Branch", city="City", timezone="Asia/Karachi")],
            "menu_categories": [dict(code="CAT", name="Main")],
            "menu_items": [dict(code=i, category_code="CAT", name=i) for i in ["I1", "I2", "I3"]],
            "customers": [dict(code="C", joined_on="2024-01-01", cohort="evaluation-only")],
            "ordering_channels": [dict(code="WEB", name="Web")],
            "promotions": [dict(code="P", name="Campaign", discount_percent="10")],
            "promotion_items": [dict(code="PI", promotion_code="P", item_code="I1")],
            "orders": [dict(code=o, restaurant_code="R", channel_code="WEB",
                            customer_code=None if o == "O1" else "C", promotion_code="P",
                            ordered_at="2025-01-01T20:00:00Z", status=status)
                       for o, status in [("O1", "completed"), ("O2", "cancelled"), ("O3", "completed")]],
            "order_items": [dict(code=code, order_code=o, line_number=str(n), item_code=item,
                                 quantity=str(q), unit_price=str(price), unit_cost=str(cost),
                                 discount_amount=str(discount), promotion_code=promo, unit="portion")
                            for code, o, n, item, q, price, cost, discount, promo in [
                                ("L1", "O1", 1, "I1", 2, 12, 5, 4, "P"),
                                ("L2", "O1", 2, "I1", 1, 12, 5, 0, None),
                                ("L3", "O1", 3, "I2", 1, 7, 3, 0, None),
                                ("L4", "O2", 1, "I1", 100, 12, 5, 0, None)]],
            "pricing_history": [dict(code=p, restaurant_code="R", item_code="I1",
                                     effective_at=t, unit_price=price, unit_cost="5")
                                for p, t, price in [("OLD", "2025-01-01T00:00:00Z", "10"),
                                                    ("CURRENT", "2025-01-01T20:00:00Z", "12"),
                                                    ("FUTURE", "2025-02-01T00:00:00Z", "100")]],
            "ratings": [dict(code="RT", order_item_code="L1", score="4", rated_at="2025-01-03T20:00:00Z")],
            "inventory": [dict(code="INV" + i, restaurant_code="R", item_code=i, date="2025-01-02",
                               opening_quantity="10", replenished_quantity="0", consumed_quantity=c, unit="portion")
                          for i, c in [("I1", "8"), ("I3", "0")]],
            "wastage": [dict(code=w, restaurant_code="R", item_code=i, recorded_at=t,
                             prepared_quantity="4", wasted_quantity=q, unit_cost="5", unit="portion")
                        for w, i, t, q in [("W1", "I1", "2025-01-02T12:00:00Z", "1"),
                                          ("W2", "I1", "2025-01-02T13:00:00Z", "2"),
                                          ("W3", "I2", "2025-01-03T12:00:00Z", "1")]],
        }
        cls.sources = {}
        for table, fields in SCHEMAS.items():
            raw = cls.spark.createDataFrame(
                [[row.get(f) for f in fields] for row in fixtures[table]],
                ", ".join(f"{f} string" for f in fields))
            frame = raw.select(*[F.col(f).cast("timestamp" if field_type(f) == "timestamp_utc"
                                              else field_type(f)).alias(f) for f in fields])
            frame.createOrReplaceTempView(table)
            cls.sources[table] = frame
        cls.fact = cls.spark.sql((SQL_ROOT / "order_lines.sql").read_text()).cache()
        cls.fact.count()
        cls.fact.createOrReplaceTempView("integrated_lines")
        cls.daily = cls.spark.sql((SQL_ROOT / "item_location_daily.sql").read_text()).cache()
        cls.daily.count()

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_line_grain_and_optional_customer(self):
        self.assertEqual(self.fact.count(), 4)
        self.assertEqual(self.fact.select("line_code").distinct().count(), 4)
        self.assertTrue(self.fact.filter("line_code = 'L1'").first().anonymous_customer)
        self.assertNotIn("cohort", self.fact.columns)
        self.assertEqual(self.fact.filter("status = 'cancelled'").count(), 1)

    def test_half_open_price_interval_and_missing_history(self):
        line = self.fact.filter("line_code = 'L1'").first()
        self.assertEqual(line.pricing_code, "CURRENT")
        self.assertFalse(line.price_snapshot_mismatch)
        self.assertTrue(self.fact.filter("line_code = 'L3'").first().missing_price_history)

    def test_mixed_campaign_and_line_accounting(self):
        line = self.fact.filter("line_code = 'L1'").first()
        self.assertEqual(line.revenue, Decimal("20.00"))
        self.assertEqual(line.contribution, Decimal("10.00"))
        other = self.fact.filter("line_code = 'L2'").first()
        self.assertEqual(other.order_promotion_code, "P")
        self.assertIsNone(other.line_promotion_code)

    def test_daily_no_fanout_or_cancelled_sales(self):
        row = self.daily.filter("item_code = 'I1' AND date = '2025-01-02'").first()
        self.assertEqual(row.sold_quantity, 3)
        self.assertEqual(row.revenue, Decimal("32.00"))
        self.assertEqual(row.wasted_quantity, Decimal("3.000"))
        self.assertEqual(row.waste_cost, Decimal("15.00000"))
        self.assertEqual(row.consumption_gap, Decimal("2.000"))

    def test_local_date_and_rating_observation_date(self):
        self.assertEqual(str(self.fact.filter("line_code = 'L1'").first().date), "2025-01-02")
        self.assertEqual(self.daily.filter("date = '2025-01-04'").first().rating_count, 1)
        self.assertEqual(self.daily.filter("item_code = 'I1' AND date = '2025-01-02'").first().rating_count, 0)

    def test_inventory_only_and_waste_only_keys(self):
        row = self.daily.filter("item_code = 'I3'").first()
        self.assertEqual(row.sold_quantity, 0)
        self.assertTrue(row.has_inventory)
        row = self.daily.filter("item_code = 'I2' AND date = '2025-01-03'").first()
        self.assertEqual(row.wasted_quantity, Decimal("1.000"))
        self.assertFalse(row.has_inventory)
        self.assertIsNone(row.consumption_gap)

    def test_coverage_and_duplicate_only_rejections(self):
        quarantine = self.spark.createDataFrame([
            (json.dumps(dict(code="L1", order_code="O1")), ["duplicate_exact"]),
            (json.dumps(dict(code="BAD", order_code="O1")), ["invalid_unit"]),
            (json.dumps(dict(code="L4", order_code="O2")), ["duplicate_exact"]),
        ], "_raw_json string, _errors array<string>")
        coverage = order_coverage(self.sources["orders"], self.fact, quarantine, self.sources["restaurants"])
        rows = {r.order_code: r for r in coverage.collect()}
        self.assertEqual(rows["O1"].coverage_status, "partial")
        self.assertEqual(rows["O1"].known_rejected_lines, 1)
        self.assertEqual(rows["O2"].coverage_status, "no_known_rejections")
        self.assertEqual(rows["O3"].coverage_status, "no_accepted_lines")

    def test_duplicate_join_key_guard(self):
        duplicate = self.sources["ratings"].union(self.sources["ratings"])
        with self.assertRaisesRegex(ValueError, "Duplicate grain"):
            unique(duplicate, ["order_item_code"], "ratings")

    def test_source_schema_and_report_count_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            counted = base / "counted"
            self.sources["restaurants"].write.parquet(str(counted / "clean" / "restaurants"))
            with self.assertRaisesRegex(ValueError, "count does not match"):
                load_sources(self.spark, counted, {"tables": {"restaurants": {"accepted_rows": 99}}})
            malformed = base / "malformed"
            self.sources["restaurants"].select("code").write.parquet(str(malformed / "clean" / "restaurants"))
            with self.assertRaisesRegex(ValueError, "type mismatch"):
                load_sources(self.spark, malformed, {"tables": {"restaurants": {"accepted_rows": 1}}})

    def test_failed_report_and_existing_output_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report = base / "quality.json"
            report.write_text(json.dumps({"status": "failed"}))
            with self.assertRaisesRegex(ValueError, "must be passed"):
                integrate(self.spark, base / "source", report, base / "out", base / "reports")
            with self.assertRaisesRegex(ValueError, "unused"):
                integrate(self.spark, base, report, base, base / "reports")
            with self.assertRaisesRegex(ValueError, "outside"):
                integrate(self.spark, base, report, base / "out", base / "reports")
            self.assertFalse((base / "out").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
