"""Boundary checks for descriptive customer segment precedence."""

import unittest
from datetime import date, timedelta

import duckdb

from python_pipeline.customer_segments import choose_segment


AS_OF = date(2026, 7, 1)


def customer(**changes):
    row = {"joined_on": AS_OF - timedelta(days=300),
           "first_visit": AS_OF - timedelta(days=270),
           "lifetime_visits": 2, "visits_90": 1, "visits_180": 2,
           "monetary_180": 100.0, "promotion_order_share": 0.0}
    row.update(changes)
    return row


class SegmentTests(unittest.TestCase):
    def test_sql_excludes_future_visits_and_counts_orders_once(self):
        con = duckdb.connect()
        con.execute("CREATE TABLE customers(code VARCHAR,joined_on DATE)")
        con.execute("INSERT INTO customers VALUES ('C1','2025-01-01')")
        con.execute("""CREATE TABLE order_coverage(order_code VARCHAR, customer_code VARCHAR,
            restaurant_code VARCHAR, accepted_line_count INTEGER,
            accepted_basket_revenue DECIMAL(12,2), ordered_at TIMESTAMP,
            timezone VARCHAR, status VARCHAR, known_rejected_lines INTEGER)""")
        con.execute("""INSERT INTO order_coverage VALUES
            ('O1','C1','R1',2,30,'2026-06-01 12:00:00','Asia/Karachi','completed',0),
            ('O2','C1','R1',1,90,'2026-07-01 12:00:00','Asia/Karachi','completed',0)""")
        con.execute("""CREATE TABLE order_lines(order_code VARCHAR,revenue DECIMAL(12,2),
            quantity INTEGER,channel_code VARCHAR,ordered_local_at TIMESTAMP,
            order_promotion_code VARCHAR,line_promotion_code VARCHAR,
            discount_amount DECIMAL(12,2),category_code VARCHAR)""")
        con.execute("""INSERT INTO order_lines VALUES
            ('O1',10,1,'delivery','2026-06-01 17:00:00',NULL,NULL,0,'A'),
            ('O1',20,2,'delivery','2026-06-01 17:00:00',NULL,NULL,0,'B'),
            ('O2',90,1,'dine_in','2026-07-01 17:00:00','P1',NULL,0,'B')""")
        from pathlib import Path
        sql = (Path(__file__).parent / "sql" / "customer_segments.sql").read_text(encoding="utf-8")
        for statement in sql.split(";"):
            if statement.strip():
                con.execute(statement, [AS_OF] * statement.count("?"))
        values = con.execute("""SELECT lifetime_visits,lifetime_monetary,
            visits_180,recency_days,favorite_category_code,favorite_channel_code,
            favorite_daypart,promotion_order_share
            FROM customer_features""").fetchone()
        self.assertEqual(values, (1, 30.0, 1, 30, 'B', 'delivery', 'afternoon', 0.0))

    def test_no_purchase_and_new_boundaries(self):
        self.assertEqual(choose_segment(customer(lifetime_visits=0), AS_OF, 500)[0],
                         "No Purchase Yet")
        self.assertEqual(choose_segment(customer(lifetime_visits=0,
                                                  joined_on=AS_OF-timedelta(days=60)), AS_OF, 500)[0],
                         "New Customers")
        self.assertEqual(choose_segment(customer(first_visit=AS_OF-timedelta(days=60)), AS_OF, 500)[0],
                         "New Customers")

    def test_at_risk_precedes_high_spend_and_promotion(self):
        row = customer(lifetime_visits=20, visits_90=0, visits_180=10,
                       monetary_180=1000, promotion_order_share=0.8)
        self.assertEqual(choose_segment(row, AS_OF, 500)[0], "At-Risk Customers")

    def test_promotion_precedes_loyalty_then_frequent(self):
        row = customer(lifetime_visits=10, visits_90=6, visits_180=6,
                       monetary_180=1000, promotion_order_share=0.5)
        self.assertEqual(choose_segment(row, AS_OF, 500)[0], "Promotion-Driven Customers")
        row["promotion_order_share"] = 0.49
        self.assertEqual(choose_segment(row, AS_OF, 500)[0], "High-Value Loyal Customers")
        row["monetary_180"] = 499.99
        self.assertEqual(choose_segment(row, AS_OF, 500)[0], "Frequent Customers")
        row["visits_180"] = 5
        self.assertEqual(choose_segment(row, AS_OF, 500)[0], "Occasional Customers")


if __name__ == "__main__":
    unittest.main()
