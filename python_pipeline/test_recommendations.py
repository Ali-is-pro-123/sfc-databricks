"""Fixture checks for local association and commercial safety guards."""

import unittest
from datetime import date

import duckdb

from python_pipeline.recommendations import audit, build


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.con.execute("""CREATE TABLE order_coverage(order_code VARCHAR,restaurant_code VARCHAR,
            status VARCHAR,accepted_line_count INTEGER,known_rejected_lines INTEGER,
            ordered_at TIMESTAMP,timezone VARCHAR)""")
        self.con.execute("CREATE TABLE order_lines(order_code VARCHAR,item_code VARCHAR)")
        baskets = ([('A', 'B')] * 12 + [('A',)] * 10 + [('B',)] * 10 + [('C',)] * 50)
        coverage = [(f'O{i}', 'R1', 'completed', len(items), 0,
                     '2026-06-01 12:00:00', 'Asia/Karachi')
                    for i, items in enumerate(baskets)]
        lines = [(f'O{i}', item) for i, items in enumerate(baskets) for item in items]
        self.con.executemany("INSERT INTO order_coverage VALUES (?,?,?,?,?,?,?)", coverage)
        self.con.executemany("INSERT INTO order_lines VALUES (?,?)", lines)
        self.con.execute("""CREATE TABLE global_pairs(item_a VARCHAR,item_b VARCHAR,
            pair_baskets INTEGER,support DOUBLE,confidence_a_to_b DOUBLE,
            confidence_b_to_a DOUBLE,lift DOUBLE)""")
        self.con.execute("INSERT INTO global_pairs VALUES ('A','B',12,12.0/82,12.0/22,12.0/22,12.0*82/(22*22))")
        self.con.execute("""CREATE TABLE global_rules(antecedent_item_code VARCHAR,
            consequent_item_code VARCHAR,confidence DOUBLE)""")
        self.con.execute("INSERT INTO global_rules VALUES ('A','B',12.0/22),('B','A',12.0/22)")
        self.con.execute("""CREATE TABLE local_performance(restaurant_code VARCHAR,item_code VARCHAR,
            item_name VARCHAR,category_code VARCHAR,quantity_sold INTEGER,
            contribution DOUBLE,latest_unit_price DOUBLE)""")
        self.con.execute("""INSERT INTO local_performance VALUES
            ('R1','A','Dish A','CA',20,1000,100),
            ('R1','B','Dish B','CB',20,1000,150)""")
        self.con.execute("CREATE TABLE menu_items(code VARCHAR,is_available BOOLEAN)")
        self.con.execute("INSERT INTO menu_items VALUES ('A',TRUE),('B',TRUE)")

    def test_rule_direction_and_safety_blocks(self):
        build(self.con, date(2026, 7, 1))
        checks = audit(self.con, {"eligible_baskets":82,
                                  "distinct_item_presences":94,
                                  "all_pair_occurrences":12})
        self.assertEqual(checks["candidate_type_counts"],
                         {"frequently_paired":1,"combo_meal":1,
                          "upsell_add_on":1,"cross_sell":1})
        directed = self.con.execute("""SELECT recommendation_type,antecedent_item_code,
            consequent_item_code FROM candidate_recommendations
            WHERE recommendation_type IN ('cross_sell','upsell_add_on') ORDER BY 1""").fetchall()
        self.assertEqual(directed, [('cross_sell','B','A'),('upsell_add_on','A','B')])
        self.con.execute("UPDATE local_performance SET contribution=-1 WHERE item_code='B'")
        build(self.con, date(2026, 7, 1))
        self.assertEqual(self.con.execute("SELECT screen_status FROM pair_screen").fetchone()[0],
                         "nonpositive_direct_contribution")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM candidate_recommendations").fetchone()[0], 0)
        self.con.execute("UPDATE local_performance SET contribution=1000 WHERE item_code='B'")
        self.con.execute("UPDATE menu_items SET is_available=FALSE WHERE code='B'")
        build(self.con, date(2026, 7, 1))
        self.assertEqual(self.con.execute("SELECT screen_status FROM pair_screen").fetchone()[0],
                         "catalog_unavailable")


if __name__ == "__main__":
    unittest.main()
