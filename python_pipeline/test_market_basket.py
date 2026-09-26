"""Hand-calculated association metrics and basket-exclusion checks."""

import unittest
from datetime import date

import duckdb

from python_pipeline.market_basket import audit, build_baskets


class MarketBasketTests(unittest.TestCase):
    def test_presence_denominator_and_directional_metrics(self):
        con = duckdb.connect()
        con.execute("""CREATE TABLE order_coverage(order_code VARCHAR,ordered_at TIMESTAMP,
            timezone VARCHAR,status VARCHAR,accepted_line_count INTEGER,
            known_rejected_lines INTEGER,accepted_basket_revenue DECIMAL(12,2))""")
        con.execute("""INSERT INTO order_coverage VALUES
            ('O1','2026-06-01 12:00:00','Asia/Karachi','completed',3,0,30),
            ('O2','2026-06-01 12:00:00','Asia/Karachi','completed',2,0,20),
            ('O3','2026-06-01 12:00:00','Asia/Karachi','completed',2,0,20),
            ('O4','2026-06-01 12:00:00','Asia/Karachi','completed',1,0,10),
            ('O5','2026-06-01 12:00:00','Asia/Karachi','completed',1,0,10),
            ('O6','2026-06-01 12:00:00','Asia/Karachi','cancelled',2,0,20),
            ('O7','2026-06-01 12:00:00','Asia/Karachi','completed',2,1,20),
            ('O8','2026-07-01 12:00:00','Asia/Karachi','completed',2,0,20)""")
        con.execute("CREATE TABLE order_lines(order_code VARCHAR,item_code VARCHAR,revenue DECIMAL(12,2))")
        con.execute("""INSERT INTO order_lines VALUES
            ('O1','A',10),('O1','A',10),('O1','B',10),
            ('O2','A',10),('O2','B',10),('O3','A',10),('O3','C',10),
            ('O4','B',10),('O5','A',10),('O6','A',10),('O6','B',10),
            ('O7','A',10),('O7','B',10),('O8','A',10),('O8','B',10)""")
        build_baskets(con, date(2026, 7, 1), 1)
        counts = audit(con, date(2026, 7, 1), 1)
        self.assertEqual(counts["eligible_baskets"], 5)
        self.assertEqual(counts["distinct_item_presences"], 8)
        self.assertEqual(counts["all_pair_occurrences"], 3)
        self.assertEqual(counts["retained_pairs"], 2)
        self.assertEqual(counts["directed_rules"], 4)
        ab = con.execute("""SELECT support,confidence,lift,pair_baskets,
            antecedent_baskets,consequent_baskets FROM association_rules
            WHERE antecedent_item_code='A' AND consequent_item_code='B'""").fetchone()
        self.assertAlmostEqual(ab[0], 2 / 5)
        self.assertAlmostEqual(ab[1], 2 / 4)
        self.assertAlmostEqual(ab[2], (2 / 4) / (3 / 5))
        self.assertEqual(ab[3:], (2, 4, 3))
        ba = con.execute("""SELECT confidence,lift FROM association_rules
            WHERE antecedent_item_code='B' AND consequent_item_code='A'""").fetchone()
        self.assertAlmostEqual(ba[0], 2 / 3)
        self.assertAlmostEqual(ba[1], ab[2])
        self.assertEqual(counts["excluded_order_counts"]["cancelled"], 1)
        self.assertEqual(counts["excluded_order_counts"]["known_partial_basket"], 1)
        self.assertEqual(counts["excluded_order_counts"]["on_or_after_cutoff"], 1)


if __name__ == "__main__":
    unittest.main()
