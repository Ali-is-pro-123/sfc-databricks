"""Edge-case checks for the dual-pipeline comparison contract."""

import unittest

import duckdb

from python_pipeline.compare_demand import (classify_difference,
                                            match_tolerance, unique_rows,
                                            assert_unique_table)


class ComparisonTests(unittest.TestCase):
    def test_disclosed_tolerance_and_signed_model_difference(self):
        self.assertEqual(match_tolerance(0), 2)
        self.assertEqual(match_tolerance(50), 10)
        self.assertEqual(classify_difference(50, 40, 50, 45, 20, False)[0], "match")
        self.assertEqual(classify_difference(50, 40, 51, 45, 20, False)[:2],
                         ("mismatch", "high_volume_model_sensitivity"))

    def test_disagreement_explanations_are_diagnostic(self):
        self.assertEqual(classify_difference(5, 2, 10, 5, 20, True)[1], "feature_divergence")
        self.assertEqual(classify_difference(25, 2, 15, 5, 20, False)[1],
                         "demand_shift_model_sensitivity")
        self.assertEqual(classify_difference(5, 2, 10, 5, 2, False)[1],
                         "sparse_history_model_sensitivity")

    def test_duplicate_record_keys_rejected(self):
        row = {"restaurant_code": "R1", "item_code": "I1", "cutoff": "2026-03-01"}
        self.assertEqual(len(unique_rows([row], "fixture")), 1)
        with self.assertRaisesRegex(ValueError, "Duplicate fixture record key"):
            unique_rows([row, row], "fixture")

    def test_parquet_grain_guard_rejects_duplicates_and_nulls(self):
        con = duckdb.connect()
        con.execute("CREATE TABLE fixture(restaurant_code VARCHAR,item_code VARCHAR,cutoff DATE)")
        con.execute("INSERT INTO fixture VALUES ('R1','I1','2026-03-01'),('R1','I1','2026-03-01')")
        with self.assertRaisesRegex(ValueError, "Duplicate keys"):
            assert_unique_table(con, "fixture")
        con.execute("DELETE FROM fixture")
        con.execute("INSERT INTO fixture VALUES (NULL,'I1','2026-03-01')")
        with self.assertRaisesRegex(ValueError, "Null keys"):
            assert_unique_table(con, "fixture")


if __name__ == "__main__":
    unittest.main()
