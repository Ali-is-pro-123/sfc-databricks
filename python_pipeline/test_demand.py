"""Focused checks for independent monthly feature construction."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import (TRAIN_END, VALIDATION_END, build_snapshots,
                                    cutoffs, metrics, validate_paths)


class DemandTests(unittest.TestCase):
    def test_cutoffs_are_monthly_and_chronological(self):
        months = cutoffs()
        self.assertEqual(len(months), 14)
        self.assertEqual((months[0], months[-1]), (date(2025, 5, 1), date(2026, 6, 1)))
        self.assertLess(months[0], TRAIN_END)
        self.assertLess(TRAIN_END, VALIDATION_END)

    def test_local_date_and_future_sales_do_not_leak(self):
        con = duckdb.connect()
        con.execute("CREATE TABLE clean_restaurants(code VARCHAR, timezone VARCHAR)")
        con.execute("INSERT INTO clean_restaurants VALUES ('R1','Asia/Karachi')")
        con.execute("CREATE TABLE clean_menu_items(code VARCHAR, category_code VARCHAR)")
        con.execute("INSERT INTO clean_menu_items VALUES ('I1','C1')")
        con.execute("CREATE TABLE clean_orders(code VARCHAR, restaurant_code VARCHAR, ordered_at TIMESTAMP, status VARCHAR)")
        con.execute("""INSERT INTO clean_orders VALUES
            ('O0','R1','2025-05-31 20:00:00','completed'),
            ('O1','R1','2025-12-31 20:00:00','completed'),
            ('O1B','R1','2026-01-14 20:00:00','completed'),
            ('O2','R1','2026-01-31 20:00:00','completed')""")
        con.execute("""CREATE TABLE clean_order_items(code VARCHAR, order_code VARCHAR,
            item_code VARCHAR, quantity INTEGER, unit_price DECIMAL(12,2),
            discount_amount DECIMAL(12,2), unit_cost DECIMAL(12,2))""")
        con.execute("""INSERT INTO clean_order_items VALUES
            ('L0','O0','I1',1,10,0,4),
            ('L1','O1','I1',2,10,0,4),('L1B','O1B','I1',2,10,0,4),
            ('L2','O2','I1',3,10,0,4)""")
        con.execute("CREATE TABLE clean_ratings(order_item_code VARCHAR, rated_at TIMESTAMP, score INTEGER)")
        con.execute("CREATE TABLE clean_wastage(restaurant_code VARCHAR, item_code VARCHAR, recorded_at TIMESTAMP, wasted_quantity INTEGER)")
        checks = build_snapshots(con)
        self.assertEqual(checks["source_sales"], checks["daily_sales"])
        dates = con.execute("SELECT local_date FROM sale_days ORDER BY local_date").fetchall()
        self.assertEqual(dates, [(date(2025, 6, 1),), (date(2026, 1, 1),),
                                 (date(2026, 1, 15),), (date(2026, 2, 1),)])
        january = con.execute("""SELECT quantity_last_30, label, split FROM supervised_snapshots
            WHERE cutoff='2026-02-01'""").fetchone()
        self.assertEqual(january, (2.0, 3.0, "validation"))
        con.execute("UPDATE clean_order_items SET quantity=8 WHERE code='L2'")
        build_snapshots(con)
        changed = con.execute("""SELECT quantity_last_30, label FROM supervised_snapshots
            WHERE cutoff='2026-02-01'""").fetchone()
        self.assertEqual(changed, (2.0, 8.0))

    def test_metrics_and_output_guard(self):
        self.assertEqual(metrics([1, 3], [2, 2])["mae"], 1.0)
        with tempfile.TemporaryDirectory() as location:
            root = Path(location)
            clean = root / "clean"
            clean.mkdir()
            quality = root / "quality.json"
            quality.write_text('{"status":"passed"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inside clean source"):
                validate_paths(clean, quality, clean / "output", root / "reports", root / "model")


if __name__ == "__main__":
    unittest.main()
