"""Rating coverage and future-repeat censoring checks."""

import unittest
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.rating_satisfaction import validate


class RatingSatisfactionTests(unittest.TestCase):
    def setUp(self):
        self.con=duckdb.connect()
        self.con.execute("CREATE TABLE clean_restaurants(code VARCHAR,timezone VARCHAR)")
        self.con.execute("CREATE TABLE clean_menu_items(code VARCHAR,category_code VARCHAR)")
        self.con.execute("""CREATE TABLE clean_orders(code VARCHAR,restaurant_code VARCHAR,
            customer_code VARCHAR,ordered_at TIMESTAMP,status VARCHAR)""")
        self.con.execute("""CREATE TABLE clean_order_items(code VARCHAR,order_code VARCHAR,
            item_code VARCHAR,quantity INTEGER,unit_price DOUBLE,unit_cost DOUBLE,
            discount_amount DOUBLE,promotion_code VARCHAR)""")
        self.con.execute("CREATE TABLE clean_ratings(code VARCHAR,order_item_code VARCHAR,score INTEGER,rated_at TIMESTAMP)")
        self.con.execute("INSERT INTO clean_restaurants VALUES ('R1','Asia/Karachi')")
        self.con.execute("INSERT INTO clean_menu_items VALUES ('I1','C1')")
        self.con.execute("""INSERT INTO clean_orders VALUES
            ('O1','R1','CU1','2026-01-01 10:00:00','completed'),
            ('O2','R1','CU1','2026-01-15 10:00:00','completed'),
            ('O3','R1','CU1','2026-03-20 10:00:00','completed'),
            ('O4','R1','CU1','2026-03-21 10:00:00','cancelled')""")
        self.con.execute("""INSERT INTO clean_order_items VALUES
            ('L1','O1','I1',1,10,4,2,'P1'),
            ('L2','O2','I1',1,10,4,0,''),
            ('L3','O3','I1',1,10,4,0,''),
            ('L4','O4','I1',1,10,4,0,'')""")
        self.con.execute("""INSERT INTO clean_ratings VALUES
            ('RT1','L1',5,'2026-01-01 11:00:00'),
            ('RT2','L2',2,'2026-03-30 11:00:00'),
            ('RT3','L3',4,'2026-04-02 11:00:00')""")
        self.con.execute("CREATE TEMP TABLE analysis_parameters AS SELECT DATE '2026-04-02' AS as_of")
        sql=(Path(__file__).parent/"sql"/"rating_satisfaction.sql").read_text(encoding="utf-8")
        self.con.execute(sql)

    def tearDown(self):
        self.con.close()

    def test_late_rating_preserves_sales_and_repeat_is_censored(self):
        checks=validate(self.con,{"ratings":3},date(2026,4,2))
        self.assertEqual(checks["accepted_completed_lines"],3)
        self.assertEqual(checks["joined_completed_ratings"],2)
        self.assertEqual(checks["accepted_ratings_outside_completed_cohort"],1)
        self.assertEqual(checks["eligible_90_day_rating_followups"],1)
        self.assertEqual(checks["observed_same_item_90_day_repeats"],1)
        promoted=self.con.execute("""SELECT sold_lines,rating_count,mean_rating
            FROM rating_metrics WHERE grain='promotion_status' AND
            promotion_status='promoted'""").fetchone()
        self.assertEqual(promoted,(1,1,5))

    def test_duplicate_rating_cannot_multiply_sales(self):
        self.con.execute("INSERT INTO clean_ratings VALUES ('RT4','L1',4,'2026-01-01 12:00:00')")
        sql=(Path(__file__).parent/"sql"/"rating_satisfaction.sql").read_text(encoding="utf-8")
        self.con.execute(sql)
        with self.assertRaisesRegex(ValueError,"multiplied"):
            validate(self.con,{"ratings":4},date(2026,4,2))


if __name__=="__main__":
    unittest.main()
