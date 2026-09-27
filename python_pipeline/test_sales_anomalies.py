"""Chronological sales baselines and exact-duplicate candidate checks."""

import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from python_pipeline.sales_anomalies import validate


class SalesAnomalyTests(unittest.TestCase):
    def setUp(self):
        self.con=duckdb.connect()
        self.con.execute("CREATE TABLE clean_restaurants(code VARCHAR,timezone VARCHAR)")
        self.con.execute("CREATE TABLE clean_menu_categories(code VARCHAR)")
        self.con.execute("CREATE TABLE clean_menu_items(code VARCHAR,category_code VARCHAR)")
        self.con.execute("""CREATE TABLE clean_orders(code VARCHAR,restaurant_code VARCHAR,
            customer_code VARCHAR,ordered_at TIMESTAMP,status VARCHAR)""")
        self.con.execute("""CREATE TABLE clean_order_items(order_code VARCHAR,item_code VARCHAR,
            line_number INTEGER,quantity INTEGER,unit_price DOUBLE,unit_cost DOUBLE,
            discount_amount DOUBLE)""")
        self.con.execute("INSERT INTO clean_restaurants VALUES ('R1','UTC')")
        self.con.execute("INSERT INTO clean_menu_categories VALUES ('C1')")
        self.con.execute("INSERT INTO clean_menu_items VALUES ('I1','C1')")
        orders=[]
        lines=[]
        index=0
        for day in (date(2025,10,1),date(2025,10,2)):
            for _ in range(30):
                code=f"O{index}"
                orders.append((code,"R1",f"CU{index}",datetime.combine(day,datetime.min.time()).replace(hour=12),"completed"))
                lines.append((code,"I1",1,1,10,4,1 if day.day==1 else 0))
                index+=1
        first_monday=date(2025,11,10)
        for week in range(8):
            day=first_monday+timedelta(days=7*week)
            for _ in range(5):
                code=f"O{index}"
                orders.append((code,"R1",f"CU{index}",datetime.combine(day,datetime.min.time()).replace(hour=12),"completed"))
                lines.append((code,"I1",1,2,10,4,0))
                index+=1
        day=date(2026,1,5)
        for position in range(15):
            code=f"O{index}"
            customer="CU-DUP" if position<2 else f"CU{index}"
            orders.append((code,"R1",customer,datetime.combine(day,datetime.min.time()).replace(hour=12),"completed"))
            quantity=20 if position==2 else 2
            discount=8 if position==3 else 0
            lines.append((code,"I1",1,quantity,10,4,discount))
            index+=1
        self.con.executemany("INSERT INTO clean_orders VALUES (?,?,?,?,?)",orders)
        self.con.executemany("INSERT INTO clean_order_items VALUES (?,?,?,?,?,?,?)",lines)
        self.con.execute("""CREATE TEMP TABLE analysis_parameters AS
            SELECT DATE '2026-02-01' AS as_of,DATE '2026-01-01' AS monitor_start""")
        sql=(Path(__file__).parent/"sql"/"sales_anomalies.sql").read_text(encoding="utf-8")
        self.con.execute(sql)

    def tearDown(self):
        self.con.close()

    def test_spike_value_discount_and_duplicate_candidates(self):
        result=validate(self.con,date(2026,2,1))
        self.assertEqual(result["accepted_completed_orders"],115)
        self.assertGreaterEqual(result["flag_counts"]["sudden_sales_spike"],1)
        self.assertGreaterEqual(result["flag_counts"]["unexpected_high_demand"],1)
        self.assertGreaterEqual(result["flag_counts"]["abnormally_high_order_value"],1)
        self.assertGreaterEqual(result["flag_counts"]["unusual_discount"],1)
        self.assertEqual(result["duplicate_candidate_groups"],1)
        self.assertEqual(result["orders_in_duplicate_candidate_groups"],2)

    def test_early_day_has_no_lookahead_baseline(self):
        early=self.con.execute("""SELECT prior_same_weekdays,sudden_sales_spike
            FROM location_day_anomalies WHERE local_date='2025-11-10'""").fetchone()
        self.assertEqual(early,(5,False))


if __name__=="__main__":
    unittest.main()
