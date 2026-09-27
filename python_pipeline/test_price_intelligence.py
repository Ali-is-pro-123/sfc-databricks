"""Price-period attribution and repeat/rating checks."""

import unittest
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.price_intelligence import validate


class PriceIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.con.execute("CREATE TABLE clean_restaurants(code VARCHAR,timezone VARCHAR)")
        self.con.execute("CREATE TABLE clean_menu_items(code VARCHAR,category_code VARCHAR,introduced_on DATE)")
        self.con.execute("""CREATE TABLE clean_pricing_history(code VARCHAR,restaurant_code VARCHAR,
            item_code VARCHAR,effective_at TIMESTAMP,unit_price DOUBLE,unit_cost DOUBLE)""")
        self.con.execute("""CREATE TABLE clean_orders(code VARCHAR,restaurant_code VARCHAR,
            customer_code VARCHAR,ordered_at TIMESTAMP,status VARCHAR)""")
        self.con.execute("""CREATE TABLE clean_order_items(code VARCHAR,order_code VARCHAR,
            item_code VARCHAR,quantity INTEGER,unit_price DOUBLE,unit_cost DOUBLE,
            discount_amount DOUBLE,promotion_code VARCHAR)""")
        self.con.execute("CREATE TABLE clean_ratings(order_item_code VARCHAR,score INTEGER)")
        self.con.execute("INSERT INTO clean_restaurants VALUES ('R1','Asia/Karachi')")
        self.con.execute("INSERT INTO clean_menu_items VALUES ('I1','C1','2026-01-01')")
        self.con.execute("""INSERT INTO clean_pricing_history VALUES
            ('P1','R1','I1','2025-12-31 19:00:00',10,4),
            ('P2','R1','I1','2026-01-31 19:00:00',12,4)""")
        self.con.execute("""INSERT INTO clean_orders VALUES
            ('O1','R1','CU1','2026-01-15 10:00:00','completed'),
            ('O2','R1','CU1','2026-02-15 10:00:00','completed'),
            ('O3','R1','CU1','2026-02-16 10:00:00','cancelled')""")
        self.con.execute("""INSERT INTO clean_order_items VALUES
            ('L1','O1','I1',1,10,4,0,''),
            ('L2','O2','I1',1,12,4,2,'PR1'),
            ('L3','O3','I1',2,12,4,0,'')""")
        self.con.execute("INSERT INTO clean_ratings VALUES ('L2',5)")
        sql = (Path(__file__).parent / "sql" / "price_intelligence.sql").read_text(encoding="utf-8")
        for statement in sql.split(";"):
            if statement.strip():
                self.con.execute(statement, [date(2026, 3, 1)] * statement.count("?"))

    def tearDown(self):
        self.con.close()

    def test_periods_reconcile_and_repeat_is_historical(self):
        totals = validate(self.con, date(2026, 3, 1))
        self.assertEqual(totals["accepted_completed_lines"], 2)
        self.assertEqual(totals["net_revenue"], 20)
        self.assertEqual(totals["discount_amount"], 2)
        rows = self.con.execute("""SELECT sold_quantity,repeat_lines,rated_lines,
            mean_rating FROM price_epochs ORDER BY start_date""").fetchall()
        self.assertEqual(rows, [(1, 0, 0, None), (1, 1, 1, 5)])
        change = self.con.execute("""SELECT price_change_rate,notable_demand_change
            FROM price_transitions""").fetchone()
        self.assertAlmostEqual(change[0], 0.2)
        self.assertFalse(change[1])

    def test_duplicate_rating_is_detected(self):
        self.con.execute("INSERT INTO clean_ratings VALUES ('L2',4)")
        sql = (Path(__file__).parent / "sql" / "price_intelligence.sql").read_text(encoding="utf-8")
        for statement in sql.split(";"):
            if statement.strip():
                self.con.execute(statement, [date(2026, 3, 1)] * statement.count("?"))
        with self.assertRaisesRegex(ValueError, "do not reconcile"):
            validate(self.con, date(2026, 3, 1))


if __name__ == "__main__":
    unittest.main()
