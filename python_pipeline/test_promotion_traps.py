"""Threshold and abstention tests for potential promotion traps."""

import unittest
from pathlib import Path

import duckdb

from python_pipeline.promotion_traps import validate


class PromotionTrapTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.con.execute("""CREATE TABLE clean_promotions(code VARCHAR,starts_at TIMESTAMP,
            ends_at TIMESTAMP)""")
        self.con.execute("CREATE TABLE clean_promotion_items(promotion_code VARCHAR,item_code VARCHAR)")
        self.con.execute("CREATE TABLE clean_menu_items(code VARCHAR,category_code VARCHAR)")
        self.con.execute("""CREATE TABLE clean_order_items(order_code VARCHAR,item_code VARCHAR,
            quantity DOUBLE,unit_price DOUBLE,unit_cost DOUBLE,discount_amount DOUBLE)""")
        self.con.execute("""CREATE TABLE accepted_orders(order_code VARCHAR,restaurant_code VARCHAR,
            customer_code VARCHAR,ordered_at TIMESTAMP)""")
        self.con.execute("""CREATE TABLE promotion_effectiveness(
            promotion_code VARCHAR,name VARCHAR,starts_at TIMESTAMP,ends_at TIMESTAMP,
            campaign_days INTEGER,order_volume INTEGER,net_revenue DOUBLE,
            direct_contribution DOUBLE,identified_customers INTEGER,
            post_30_day_repeat_rate DOUBLE,followup_complete BOOLEAN,
            prior_equal_window_eligible_item_waste DOUBLE,
            active_eligible_item_waste DOUBLE,attributed_quantity DOUBLE,
            sold_quantity DOUBLE)""")
        self.con.execute("INSERT INTO clean_promotions VALUES ('PR1','2026-01-10','2026-01-20')")
        self.con.execute("INSERT INTO clean_promotion_items VALUES ('PR1','I1')")
        self.con.execute("INSERT INTO clean_menu_items VALUES ('I1','C1')")
        self.con.execute("""INSERT INTO accepted_orders VALUES
            ('O1','R1','CU1','2026-01-05'),('O2','R1','CU2','2026-01-15')""")
        self.con.execute("""INSERT INTO clean_order_items VALUES
            ('O1','I1',10,10,4,0),('O2','I1',15,10,4,20)""")
        self.con.execute("""INSERT INTO promotion_effectiveness VALUES
            ('PR1','Offer','2026-01-10','2026-01-20',10,1,130,70,2,
             0.50,TRUE,10,25,15,15)""")
        self.sql = (Path(__file__).parent/"sql"/"promotion_traps.sql").read_text(encoding="utf-8")
        self.con.execute(self.sql)
        self.prior = {"checks":{"campaigns":1,"campaign_orders":1,
                                "campaign_net_revenue":130,
                                "campaign_direct_contribution":70}}

    def tearDown(self):
        self.con.close()

    def test_waste_flag_and_small_sample_abstention(self):
        checks = validate(self.con,self.prior)
        self.assertEqual(checks["flag_counts"]["eligible_waste_up"],1)
        self.assertEqual(checks["flag_counts"]["sales_up_contribution_down"],0)
        self.assertEqual(checks["flag_counts"]["low_post_discount_repeat"],0)

    def test_discount_followup_requires_complete_window(self):
        self.con.execute("""UPDATE promotion_effectiveness SET
            identified_customers=40,post_30_day_repeat_rate=0.02,
            attributed_quantity=10,sold_quantity=20,followup_complete=FALSE""")
        self.con.execute(self.sql)
        self.assertFalse(self.con.execute("SELECT low_post_discount_repeat FROM promotion_traps").fetchone()[0])
        self.con.execute("UPDATE promotion_effectiveness SET followup_complete=TRUE")
        self.con.execute(self.sql)
        self.assertTrue(self.con.execute("SELECT low_post_discount_repeat FROM promotion_traps").fetchone()[0])

    def test_rebuilt_campaign_mismatch_fails(self):
        changed = {"checks":dict(self.prior["checks"],campaign_orders=2)}
        with self.assertRaisesRegex(ValueError,"totals differ"):
            validate(self.con,changed)


if __name__=="__main__":
    unittest.main()
