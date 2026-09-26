"""Boundary and tie checks for point-in-time RFM scoring."""

import unittest
from datetime import date

import duckdb

from python_pipeline.rfm import create_scores


class RfmTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.con.execute("""CREATE TABLE customer_source(
            customer_code VARCHAR, joined_on DATE, first_visit DATE,
            last_visit DATE, recency_days INTEGER, visits_180 INTEGER,
            monetary_180 DOUBLE, lifetime_visits INTEGER,
            lifetime_monetary DOUBLE, segment VARCHAR)""")
        self.con.execute("""INSERT INTO customer_source VALUES
            ('A','2025-01-01','2025-06-01','2026-06-01',30,6,400,9,800,'Frequent Customers'),
            ('B','2025-01-01','2025-06-01','2026-05-02',60,4,300,5,600,'Occasional Customers'),
            ('C','2025-01-01','2025-06-01','2026-04-02',90,2,200,4,500,'At-Risk Customers'),
            ('D','2025-01-01','2025-06-01','2026-01-02',180,1,100,3,400,'At-Risk Customers'),
            ('E','2025-01-01','2025-06-01','2026-01-01',181,0,0,2,300,'At-Risk Customers'),
            ('F','2025-01-01',NULL,NULL,NULL,0,0,0,0,'No Purchase Yet'),
            ('G','2025-01-01','2025-06-01','2026-06-01',30,2,200,3,500,'Occasional Customers')""")

    def test_boundaries_and_no_purchase(self):
        thresholds, _ = create_scores(self.con, date(2026, 7, 1))
        self.assertEqual(thresholds["p50"], 200)
        scores = {code: (r, f, m, tier) for code, r, f, m, tier in self.con.execute(
            "SELECT customer_code,r_score,f_score,m_score,rfm_tier FROM rfm_scores").fetchall()}
        self.assertEqual(scores["A"], (5, 5, 5, "Top RFM"))
        self.assertEqual(scores["B"][0:2], (4, 4))
        self.assertEqual(scores["C"][0:2], (3, 3))
        self.assertEqual(scores["D"][0:2], (2, 2))
        self.assertEqual(scores["E"], (1, 1, 1, "Low RFM"))
        self.assertEqual(scores["F"], (0, 0, 0, "No Purchase History"))
        self.assertEqual(scores["C"][2], scores["G"][2])


if __name__ == "__main__":
    unittest.main()
