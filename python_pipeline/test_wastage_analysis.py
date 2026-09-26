"""Check wastage joins and additive reporting grains."""

import unittest
from pathlib import Path

import duckdb

from python_pipeline.wastage_analysis import summary_query, validate_facts


class WastageAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.con.execute("CREATE TABLE clean_orders(code VARCHAR,restaurant_code VARCHAR,ordered_at TIMESTAMP,status VARCHAR)")
        self.con.execute("CREATE TABLE clean_order_items(order_code VARCHAR,item_code VARCHAR,quantity INTEGER,promotion_code VARCHAR)")
        self.con.execute("CREATE TABLE clean_restaurants(code VARCHAR,timezone VARCHAR)")
        self.con.execute("CREATE TABLE clean_menu_items(code VARCHAR,category_code VARCHAR)")
        self.con.execute("""CREATE TABLE clean_wastage(restaurant_code VARCHAR,item_code VARCHAR,
            recorded_at TIMESTAMP,prepared_quantity INTEGER,wasted_quantity INTEGER,unit_cost DOUBLE)""")
        self.con.execute("""CREATE TABLE clean_inventory(restaurant_code VARCHAR,item_code VARCHAR,
            date DATE,opening_quantity INTEGER,replenished_quantity INTEGER,consumed_quantity INTEGER)""")
        self.con.execute("INSERT INTO clean_restaurants VALUES ('R1','Asia/Karachi')")
        self.con.execute("INSERT INTO clean_menu_items VALUES ('I1','C1')")
        self.con.execute("INSERT INTO clean_orders VALUES ('O1','R1','2026-03-01 23:00:00','completed')")
        self.con.execute("INSERT INTO clean_order_items VALUES ('O1','I1',2,'P1'),('O1','I1',3,'')")
        self.con.execute("INSERT INTO clean_wastage VALUES ('R1','I1','2026-03-01 23:00:00',7,2,4)")
        self.con.execute("INSERT INTO clean_inventory VALUES ('R1','I1','2026-03-02',0,7,7)")
        sql = (Path(__file__).parent / "sql" / "wastage_analysis.sql").read_text(encoding="utf-8")
        self.con.execute(sql)

    def tearDown(self):
        self.con.close()

    def test_daily_grain_no_join_multiplication(self):
        row = self.con.execute("""SELECT business_date,sold_quantity,promoted_sold_quantity,
            wasted_quantity,prepared_quantity,consumed_quantity,waste_cost
            FROM wastage_daily""").fetchone()
        self.assertEqual(str(row[0]), "2026-03-02")
        self.assertEqual(row[1:], (5, 2, 2, 7, 7, 8))
        totals = validate_facts(self.con, {"wastage": 1, "inventory": 1})
        self.assertEqual(totals["inventory_consumption_mismatch_days"], 0)
        grouped = self.con.execute(summary_query(("category_code",))).fetchone()
        self.assertEqual(grouped[0], "C1")
        self.assertEqual(grouped[2], 5)
        self.assertEqual(grouped[5], 2)

    def test_inventory_gap_is_reported(self):
        self.con.execute("UPDATE clean_inventory SET consumed_quantity=8,replenished_quantity=8")
        sql = (Path(__file__).parent / "sql" / "wastage_analysis.sql").read_text(encoding="utf-8")
        self.con.execute(sql)
        totals = validate_facts(self.con, {"wastage": 1, "inventory": 1})
        self.assertEqual(totals["inventory_minus_accepted_sales_and_waste"], 1)
        self.assertEqual(totals["inventory_consumption_mismatch_days"], 1)


if __name__ == "__main__":
    unittest.main()
