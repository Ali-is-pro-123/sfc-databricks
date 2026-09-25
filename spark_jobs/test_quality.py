"""Run these regression checks with spark-submit in the Linux container."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import SparkSession, types as T
from data_generator.schemas import OPTIONAL, SCHEMAS, field_type
from spark_jobs.ingest import ingest
from spark_jobs.quality import cast_and_check, conflicts, references


class QualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.appName("DineIQ quality regression tests")
                     .config("spark.sql.shuffle.partitions", "2")
                     .config("spark.sql.session.timeZone", "UTC")
                     .config("spark.sql.ansi.enabled", "false").getOrCreate())
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def checked(self, table, rows):
        fields = SCHEMAS[table]
        schema = T.StructType([T.StructField(f, T.StringType())
                               for f in fields + ["_corrupt_record", "_source_file"]])
        raw = self.spark.createDataFrame([
            [r.get(f) for f in fields] + [r.get("_corrupt_record"), "fixture.csv"]
            for r in rows], schema)
        return cast_and_check(raw, table, fields,
                              {f: field_type(f) for f in fields}, OPTIONAL)

    def line(self, **changes):
        row = dict(code="L1", order_code="O1", line_number="1", item_code="I1",
                   quantity="2", unit_price="10.00", unit_cost="6.00",
                   discount_amount="0.00", promotion_code="", unit="portion")
        return row | changes

    def test_exact_copy_and_conflicting_keys(self):
        rows = conflicts(self.checked("order_items", [self.line(), self.line()]),
                         "order_items").collect()
        self.assertEqual(sum(not r._errors for r in rows), 1)
        self.assertEqual(sum("duplicate_exact" in r._errors for r in rows), 1)
        rows = conflicts(self.checked("order_items", [self.line(), self.line(quantity="3")]),
                         "order_items").collect()
        self.assertTrue(all("conflicting_code" in r._errors for r in rows))
        rows = conflicts(self.checked("order_items", [self.line(), self.line(code="L2")]),
                         "order_items").collect()
        self.assertTrue(all("conflicting_business_key" in r._errors for r in rows))

    def test_numeric_precision_units_and_missing_keys(self):
        cases = [(dict(quantity="1.5"), "invalid_precision:quantity"),
                 (dict(unit_price="1.001"), "invalid_precision:unit_price"),
                 (dict(unit_cost="oops"), "invalid_type:unit_cost"),
                 (dict(quantity="-1"), "negative:quantity"),
                 (dict(discount_amount="21"), "excess_discount"),
                 (dict(item_code=""), "missing:item_code"),
                 (dict(unit="kg"), "invalid_unit"),
                 (dict(_corrupt_record="extra,columns"), "malformed_csv")]
        for changes, reason in cases:
            with self.subTest(reason=reason):
                self.assertIn(reason, self.checked("order_items", [self.line(**changes)]).first()._errors)

    def test_unknown_reference(self):
        clean = {"items": self.spark.createDataFrame([("I2",)], "code string")}
        row = references(self.checked("order_items", [self.line()]), "fixture", clean,
                         {"fixture": {"item_code": "items"}}).first()
        self.assertIn("unknown_reference:item_code", row._errors)

    def test_anonymous_cancelled_order_and_invalid_date(self):
        order = dict(code="O1", restaurant_code="R1", customer_code="", channel_code="C1",
                     promotion_code="", ordered_at="2025-01-02T10:00:00Z", status="cancelled")
        self.assertEqual(self.checked("orders", [order]).first()._errors, [])
        self.assertIn("invalid_type:ordered_at",
                      self.checked("orders", [order | {"ordered_at": "not-a-date"}]).first()._errors)

    def test_rating_and_wastage_bounds(self):
        rating = dict(code="A1", order_item_code="L1", score="6", rated_at="2025-01-02T12:00:00Z")
        self.assertIn("invalid_rating", self.checked("ratings", [rating]).first()._errors)
        waste = dict(code="W1", restaurant_code="R1", item_code="I1",
                     recorded_at="2025-01-02T12:00:00Z", prepared_quantity="5",
                     wasted_quantity="6", unit_cost="1", reason="spoilage", unit="portion")
        self.assertIn("impossible_wastage", self.checked("wastage", [waste]).first()._errors)

    def test_campaign_attribution_and_item_eligibility(self):
        clean = {
            "orders": self.spark.createDataFrame(
                [("O1", "P1", "2025-01-02T10:00:00Z")],
                "code string, promotion_code string, ordered_at string"),
            "promotion_items": self.spark.createDataFrame(
                [("P1", "I1")], "promotion_code string, item_code string"),
        }
        rows = references(self.checked("order_items", [
            self.line(code="valid", promotion_code="P1"),
            self.line(code="mismatch", promotion_code="P2"),
            self.line(code="ineligible", promotion_code="P1", item_code="I2"),
        ]), "order_items", clean, {}).collect()
        errors = {r.code: r._errors for r in rows}
        self.assertEqual(errors["valid"], [])
        self.assertIn("campaign_mismatch", errors["mismatch"])
        self.assertIn("ineligible_campaign_item", errors["ineligible"])

    def test_ratings_require_completed_prior_purchase(self):
        clean = {
            "order_items": self.spark.createDataFrame(
                [("L1", "O1")], "code string, order_code string"),
            "orders": self.spark.createDataFrame(
                [("O1", "2025-01-02T10:00:00Z", "cancelled")],
                "code string, ordered_at string, status string"),
        }
        rating = dict(code="A1", order_item_code="L1", score="5", rated_at="2025-01-01T12:00:00Z")
        row = references(self.checked("ratings", [rating]), "ratings", clean, {}).first()
        self.assertIn("invalid_purchase_rating", row._errors)

    def test_input_and_overwrite_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaises(ValueError):
                ingest(self.spark, base / "clean_reference", base / "output", base / "reports")
            with self.assertRaises(FileExistsError):
                ingest(self.spark, base / "raw", base, base / "reports")
            with self.assertRaisesRegex(ValueError, "Missing input table"):
                ingest(self.spark, base / "raw", base / "output", base / "reports")
            self.assertFalse((base / "output").exists())
            (base / "raw" / "restaurants").mkdir(parents=True)
            (base / "raw" / "restaurants" / "bad.csv").write_text("wrong,header\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid header"):
                ingest(self.spark, base / "raw", base / "output", base / "reports")
            self.assertFalse((base / "output").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
