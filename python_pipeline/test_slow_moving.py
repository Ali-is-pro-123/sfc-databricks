"""Long purchase gaps, zero sales and new-item abstention."""

import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from python_pipeline.slow_moving import validate


class SlowMovingTests(unittest.TestCase):
    def setUp(self):
        self.con=duckdb.connect()
        self.con.execute("CREATE TABLE clean_restaurants(code VARCHAR,timezone VARCHAR)")
        self.con.execute("""CREATE TABLE clean_orders(code VARCHAR,restaurant_code VARCHAR,
            ordered_at TIMESTAMP,status VARCHAR)""")
        self.con.execute("""CREATE TABLE clean_order_items(order_code VARCHAR,item_code VARCHAR,
            quantity INTEGER,unit_price DOUBLE,unit_cost DOUBLE,discount_amount DOUBLE)""")
        self.con.execute("""CREATE TABLE performance(
            restaurant_code VARCHAR,item_code VARCHAR,item_name VARCHAR,
            category_code VARCHAR,restaurant_name VARCHAR,item_age_days INTEGER,
            quantity_sold INTEGER,order_frequency INTEGER,revenue DOUBLE,cost DOUBLE,
            contribution DOUBLE,profit_percentage DOUBLE,eligible_customers INTEGER,
            repeat_purchase_rate DOUBLE,wasted_quantity DOUBLE,
            accounted_wastage_percentage DOUBLE,prior_30d_quantity INTEGER,
            recent_30d_quantity INTEGER,prior_30d_exposure_days INTEGER,
            recent_30d_exposure_days INTEGER,quantity_trend_percentage DOUBLE)""")
        self.con.execute("INSERT INTO clean_restaurants VALUES ('R1','UTC')")
        orders=[]
        lines=[]
        performance=[]
        for item in range(9):
            count=1 if item==0 else 0 if item in (7,8) else 20
            for purchase in range(count):
                code=f"O{item}-{purchase}"
                day=date(2026,1,5) if item==0 else date(2026,1,10)+timedelta(days=purchase*3)
                orders.append((code,"R1",datetime.combine(day,datetime.min.time()).replace(hour=12),"completed"))
                lines.append((code,f"I{item}",1,10,4,0))
            revenue=count*10
            cost=count*4
            performance.append(("R1",f"I{item}",f"Dish {item}","C1","Branch",
                                30 if item==7 else 200,count,count,revenue,cost,
                                revenue-cost,60 if count else None,
                                5 if item==0 else 25,None,0,
                                0 if count else None,1 if item==0 else 10,
                                0 if item==0 else 10,30,30,
                                None if item==0 else 0))
        self.con.executemany("INSERT INTO clean_orders VALUES (?,?,?,?)",orders)
        self.con.executemany("INSERT INTO clean_order_items VALUES (?,?,?,?,?,?)",lines)
        self.con.executemany("INSERT INTO performance VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",performance)
        self.con.execute("CREATE TEMP TABLE analysis_parameters AS SELECT DATE '2026-04-01' AS as_of")
        sql=(Path(__file__).parent/"sql"/"slow_moving.sql").read_text(encoding="utf-8")
        self.con.execute(sql)

    def tearDown(self):
        self.con.close()

    def test_sparse_old_and_no_sale_pairs_are_slow_new_item_abstains(self):
        checks=validate(self.con,{"outputs":{"item_location_performance":{"rows":9}}})
        self.assertEqual(checks["pairs"],9)
        classes=dict(self.con.execute("SELECT item_code,movement_class FROM slow_moving_pairs").fetchall())
        self.assertEqual(classes["I0"],"slow_moving")
        self.assertEqual(classes["I7"],"insufficient_evidence")
        self.assertEqual(classes["I8"],"slow_moving")
        gap=self.con.execute("SELECT longest_no_sale_gap_days FROM slow_moving_pairs WHERE item_code='I0'").fetchone()[0]
        self.assertGreaterEqual(gap,21)

    def test_tampered_feature_quantity_fails(self):
        self.con.execute("UPDATE performance SET quantity_sold=99 WHERE item_code='I0'")
        with self.assertRaisesRegex(ValueError,"differ from accepted clean sales"):
            validate(self.con,{"outputs":{"item_location_performance":{"rows":9}}})


if __name__=="__main__":
    unittest.main()
