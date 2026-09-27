"""Focused checks for Step 34's cross-location interpretation."""

import unittest
from pathlib import Path

import duckdb


class LocationMenuPerformanceTests(unittest.TestCase):
    def test_class_spread_counts_distinct_local_classes(self):
        con = duckdb.connect()
        con.execute("""CREATE VIEW local_classes AS SELECT * FROM (VALUES
            ('R1','I1','Profit Driver'), ('R2','I1','Low Performer'),
            ('R1','I2','Volume Driver'), ('R2','I2','Volume Driver'))
            t(restaurant_code,item_code,menu_class)""")
        sql = (Path(__file__).parent / "sql" / "location_menu_performance.sql").read_text(encoding="utf-8")
        con.execute(sql.split("CREATE TEMP TABLE location_menu_items")[0])
        self.assertEqual(con.execute("SELECT distinct_location_classes FROM class_spread WHERE item_code='I1'").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT distinct_location_classes FROM class_spread WHERE item_code='I2'").fetchone()[0], 1)

    def test_full_output_has_all_four_classes_and_reconciled_locations(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "parquet_data" / "step34-full"
        if not path.is_dir():
            self.skipTest("Full generated output is not available")
        con = duckdb.connect()
        pairs = str(path / "location_menu_items.parquet")
        summary = str(path / "location_menu_summary.parquet")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [pairs]).fetchone()[0], 4320)
        self.assertEqual(con.execute("""SELECT COUNT(*) FROM read_parquet(?) WHERE
            profit_drivers+volume_drivers+hidden_opportunities+low_performers=menu_items""", [summary]).fetchone()[0], 24)
        self.assertEqual(con.execute("SELECT COUNT(DISTINCT location_menu_class) FROM read_parquet(?)", [pairs]).fetchone()[0], 4)


if __name__ == "__main__":
    unittest.main()
