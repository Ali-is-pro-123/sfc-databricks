"""Timezone, exposure and channel-grain checks for peak periods."""

import unittest
from datetime import date

import duckdb

from python_pipeline.peak_periods import audit, build_facts, build_metrics, peaks


class PeakPeriodTests(unittest.TestCase):
    def test_midnight_boundary_and_calendar_normalization(self):
        con = duckdb.connect()
        con.execute("""CREATE TABLE order_coverage(order_code VARCHAR,restaurant_code VARCHAR,
            accepted_line_count INTEGER,accepted_basket_revenue DECIMAL(12,2),
            ordered_at TIMESTAMP,timezone VARCHAR,status VARCHAR,
            known_rejected_lines INTEGER)""")
        con.execute("""INSERT INTO order_coverage VALUES
            ('O1','R1',2,20,'2026-06-27 20:30:00','Asia/Karachi','completed',0),
            ('O2','R1',1,10,'2026-06-29 15:00:00','Asia/Karachi','completed',0),
            ('O3','R1',1,10,'2026-06-29 16:00:00','Asia/Karachi','completed',0),
            ('O4','R1',1,10,'2026-06-30 18:00:00','Asia/Karachi','completed',0),
            ('O5','R1',1,10,'2026-06-30 20:00:00','Asia/Karachi','completed',0),
            ('O6','R1',1,10,'2026-06-29 15:00:00','Asia/Karachi','cancelled',0),
            ('O7','R1',1,10,'2026-06-29 15:00:00','Asia/Karachi','completed',1)""")
        con.execute("""CREATE TABLE order_lines(order_code VARCHAR,channel_code VARCHAR,
            channel_name VARCHAR,revenue DECIMAL(12,2))""")
        con.execute("""INSERT INTO order_lines VALUES
            ('O1','D','Third-party Delivery',10),('O1','D','Third-party Delivery',10),
            ('O2','I','Dine-in',10),('O3','W','Website/App',10),
            ('O4','T','Takeaway',10),('O5','D','Third-party Delivery',10),
            ('O6','I','Dine-in',10),('O7','I','Dine-in',10)""")
        cutoff = date(2026, 7, 1)
        build_facts(con, cutoff)
        build_metrics(con)
        checks = audit(con, {"eligible_baskets":4}, cutoff)
        self.assertEqual(checks["eligible_orders"], 4)
        self.assertEqual(checks["calendar_days"], 3)
        self.assertEqual(checks["channel_order_counts"],
                         {"Dine-in":1,"Delivery":1,"Website/App":1,"Takeaway":1})
        sunday = con.execute("""SELECT local_date,local_hour,weekday_number
            FROM order_facts WHERE order_code='O1'""").fetchone()
        self.assertEqual(sunday, (date(2026, 6, 28), 1, 7))
        weekend = peaks(con)["weekend_patterns"]["ALL|ALL"]
        self.assertEqual(weekend["weekend_orders_per_day"], 1)
        self.assertEqual(weekend["weekday_orders_per_day"], 1.5)


if __name__ == "__main__":
    unittest.main()
