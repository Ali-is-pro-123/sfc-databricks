"""Check channel comparisons preserve basket totals and local peak evidence."""

import unittest
from pathlib import Path

import duckdb


class OrderingChannelTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.output = self.root / "parquet_data" / "step35-verified-full"
        if not self.output.is_dir():
            self.skipTest("Verified channel output is not available")
        self.con = duckdb.connect()

    def test_channel_and_location_totals_reconcile(self):
        channel = str(self.output / "channel_summary.parquet")
        location = str(self.output / "location_channel_summary.parquet")
        self.assertEqual(self.con.execute("SELECT SUM(completed_orders) FROM read_parquet(?)", [channel]).fetchone()[0], 73982)
        self.assertEqual(self.con.execute("SELECT SUM(completed_orders) FROM read_parquet(?)", [location]).fetchone()[0], 73982)
        self.assertEqual(self.con.execute("SELECT SUM(revenue) FROM read_parquet(?)", [channel]).fetchone()[0],
                         self.con.execute("SELECT SUM(revenue) FROM read_parquet(?)", [location]).fetchone()[0])

    def test_menu_and_peak_grains(self):
        menu = str(self.output / "channel_menu_preferences.parquet")
        peaks = str(self.output / "channel_peak_hours.parquet")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM read_parquet(?)", [menu]).fetchone()[0], 720)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM read_parquet(?) WHERE local_hour BETWEEN 0 AND 23", [peaks]).fetchone()[0], 36)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM read_parquet(?) WHERE order_volume_rank=1", [peaks]).fetchone()[0], 4)


if __name__ == "__main__":
    unittest.main()
