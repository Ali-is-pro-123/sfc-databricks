"""Weekly and purchase-cohort anomaly rule checks."""

import unittest
from datetime import date, timedelta
from pathlib import Path

import duckdb

from python_pipeline.rating_anomalies import validate


class RatingAnomalyTests(unittest.TestCase):
    def setUp(self):
        self.con=duckdb.connect()
        self.con.execute("""CREATE TABLE rating_events(item_code VARCHAR,
            restaurant_code VARCHAR,rating_local_date DATE,rating_score INTEGER)""")
        self.con.execute("""CREATE TABLE rating_metrics(grain VARCHAR,item_code VARCHAR,
            period VARCHAR,sold_lines INTEGER,rating_count INTEGER,
            sold_quantity INTEGER)""")
        start=date(2026,1,5)
        events=[]
        for week in range(10):
            count=5 if week<8 else 10 if week==8 else 20
            score=3 if week<8 else 5
            events.extend(("I1","R1",start+timedelta(days=7*week),score)
                          for _ in range(count))
        self.con.executemany("INSERT INTO rating_events VALUES (?,?,?,?)",events)
        self.con.executemany("INSERT INTO rating_metrics VALUES ('item_location_month_promotion','I1',?,?,?,?)",
                             [("2026-01",100,10,100),("2026-02",100,10,100),
                              ("2026-03",100,10,100),("2026-04",50,40,50)])
        self.sql=(Path(__file__).parent/"sql"/"rating_anomalies.sql").read_text(encoding="utf-8")
        self.con.execute(self.sql)
        self.source={"outputs":{"rating_events":{"rows":70},
                                "rating_metrics":{"rows":4}},
                     "checks":{"accepted_completed_lines":350}}

    def tearDown(self):
        self.con.close()

    def test_weekly_spike_and_monthly_purchase_mismatch(self):
        checks=validate(self.con,self.source)
        self.assertGreaterEqual(checks["weekly_flag_counts"]["sudden_rating_spike"],1)
        self.assertGreaterEqual(checks["weekly_flag_counts"]["excessive_identical_ratings"],1)
        self.assertEqual(checks["monthly_flag_counts"]["rating_coverage_vs_sales_spike"],1)
        self.assertEqual(checks["monthly_flag_counts"]["ratings_up_sales_down"],1)
        early=self.con.execute("""SELECT sudden_rating_spike FROM weekly_rating_anomalies
            WHERE grain='item' ORDER BY week_start LIMIT 1""").fetchone()[0]
        self.assertFalse(early)

    def test_source_count_mismatch_fails(self):
        changed={"outputs":{"rating_events":{"rows":71},
                            "rating_metrics":{"rows":4}},
                 "checks":{"accepted_completed_lines":350}}
        with self.assertRaisesRegex(ValueError,"source row counts differ"):
            validate(self.con,changed)


if __name__=="__main__":
    unittest.main()
