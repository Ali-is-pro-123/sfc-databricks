"""Evidence thresholds and class abstention for price response."""

import unittest
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.price_sensitivity import validate


class PriceSensitivityTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.con.execute("""CREATE TABLE price_epochs(
            restaurant_code VARCHAR,item_code VARCHAR,category_code VARCHAR)""")
        self.con.execute("""CREATE TABLE price_transitions(
            price_code VARCHAR,restaurant_code VARCHAR,item_code VARCHAR,
            category_code VARCHAR,start_date DATE,end_date DATE,
            prior_unit_price DOUBLE,unit_price DOUBLE,price_change_rate DOUBLE,
            prior_exposure_days INTEGER,exposure_days INTEGER,
            prior_sold_quantity DOUBLE,sold_quantity DOUBLE,
            prior_sold_per_day DOUBLE,sold_per_exposure_day DOUBLE,
            prior_net_revenue DOUBLE,net_revenue DOUBLE,
            discount_amount DOUBLE,promoted_quantity DOUBLE)""")
        self.con.executemany("INSERT INTO price_epochs VALUES ('R1',?,'C1')",
                             [(f"I{i}",) for i in range(8)])
        rows = []
        for period, start in enumerate((date(2026, 2, 1), date(2026, 4, 1))):
            for item in range(7):
                target = item == 0
                prior_rate = 10 if period == 0 else (8 if target else 10)
                current_rate = (8 if period == 0 else 6) if target else 10
                prior_price = 10 if period == 0 else 11
                rows.append((f"P{period}-{item}","R1",f"I{item}","C1",start,
                             date(2026, 3, 1) if period == 0 else date(2026, 5, 1),
                             prior_price,prior_price*1.1,0.1,40,40,
                             prior_rate*40,current_rate*40,prior_rate,current_rate,
                             prior_rate*40*prior_price,current_rate*40*prior_price*1.1,
                             0,0))
        self.con.executemany("INSERT INTO price_transitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.sql = (Path(__file__).parent / "sql" / "price_sensitivity.sql").read_text(encoding="utf-8")
        self.con.execute(self.sql)

    def tearDown(self):
        self.con.close()

    def test_high_pair_requires_two_peer_supported_transitions(self):
        result = validate(self.con, {"outputs":{"price_epochs":{"rows":8},
                                                  "price_transitions":{"rows":14}}})
        self.assertEqual(result["eligible_transitions"],14)
        target = self.con.execute("""SELECT eligible_changes,sensitivity_class
            FROM pair_sensitivity WHERE item_code='I0'""").fetchone()
        self.assertEqual(target,(2,"highly_price_sensitive"))
        missing = self.con.execute("""SELECT sensitivity_class FROM pair_sensitivity
            WHERE item_code='I7'""").fetchone()[0]
        self.assertEqual(missing,"insufficient_evidence")
        self.assertEqual(self.con.execute("SELECT sensitivity_class FROM item_sensitivity WHERE item_code='I0'").fetchone()[0],
                         "insufficient_evidence")

    def test_source_row_count_mismatch_fails(self):
        with self.assertRaisesRegex(ValueError,"source row counts differ"):
            validate(self.con,{"outputs":{"price_epochs":{"rows":9},
                                          "price_transitions":{"rows":14}}})


if __name__ == "__main__":
    unittest.main()
