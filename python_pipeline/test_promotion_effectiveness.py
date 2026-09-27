"""Campaign basket, customer follow-up and eligible-waste checks."""

import unittest
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.promotion_effectiveness import validate


class PromotionEffectivenessTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.con.execute("""CREATE TABLE clean_orders(code VARCHAR,restaurant_code VARCHAR,
            customer_code VARCHAR,ordered_at TIMESTAMP,promotion_code VARCHAR,status VARCHAR)""")
        self.con.execute("""CREATE TABLE clean_order_items(order_code VARCHAR,item_code VARCHAR,
            quantity INTEGER,unit_price DOUBLE,unit_cost DOUBLE,discount_amount DOUBLE,
            promotion_code VARCHAR)""")
        self.con.execute("""CREATE TABLE clean_promotions(code VARCHAR,name VARCHAR,
            starts_at TIMESTAMP,ends_at TIMESTAMP,discount_percent DOUBLE)""")
        self.con.execute("CREATE TABLE clean_promotion_items(promotion_code VARCHAR,item_code VARCHAR)")
        self.con.execute("""CREATE TABLE clean_wastage(item_code VARCHAR,recorded_at TIMESTAMP,
            wasted_quantity DOUBLE,unit_cost DOUBLE)""")
        self.con.execute("INSERT INTO clean_promotions VALUES ('PR1','Offer','2026-01-10','2026-01-20',20)")
        self.con.execute("INSERT INTO clean_promotion_items VALUES ('PR1','I1')")
        self.con.execute("""INSERT INTO clean_orders VALUES
            ('O0','R1','CU2','2026-01-05','','completed'),
            ('O1','R1','CU1','2026-01-12','PR1','completed'),
            ('O2','R1','CU2','2026-01-13','PR1','completed'),
            ('O3','R1','CU1','2026-01-25','','completed'),
            ('O4','R1','CU2','2026-01-26','','completed'),
            ('O5','R1','CU1','2026-01-14','PR1','cancelled')""")
        self.con.execute("""INSERT INTO clean_order_items VALUES
            ('O0','I1',1,10,4,0,''),('O1','I1',1,10,4,2,'PR1'),
            ('O2','I1',1,10,4,2,'PR1'),('O3','I1',1,10,4,0,''),
            ('O4','I1',1,10,4,0,''),('O5','I1',1,10,4,2,'PR1')""")
        self.con.execute("""INSERT INTO clean_wastage VALUES
            ('I1','2026-01-04',3,2),('I1','2026-01-15',5,2)""")
        self.con.execute("CREATE TEMP TABLE analysis_parameters AS SELECT DATE '2026-02-25' AS as_of")
        self.sql = (Path(__file__).parent/"sql"/"promotion_effectiveness.sql").read_text(encoding="utf-8")
        self.con.execute(self.sql)

    def tearDown(self):
        self.con.close()

    def test_campaign_metrics_and_post_window(self):
        checks = validate(self.con,{"promotions":1})
        self.assertEqual(checks["campaign_orders"],2)
        row = self.con.execute("""SELECT order_volume,net_revenue,direct_contribution,
            average_order_value,first_observed_customers,returning_customers,
            post_30_day_repeat_customers,post_30_day_orders,
            active_eligible_item_waste,prior_equal_window_eligible_item_waste,
            followup_complete FROM promotion_effectiveness""").fetchone()
        self.assertEqual(row,(2,16,8,8,1,1,2,2,5,3,True))

    def test_partial_followup_is_marked(self):
        self.con.execute("CREATE OR REPLACE TEMP TABLE analysis_parameters AS SELECT DATE '2026-01-30' AS as_of")
        self.con.execute(self.sql)
        self.assertFalse(self.con.execute("SELECT followup_complete FROM promotion_effectiveness").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
