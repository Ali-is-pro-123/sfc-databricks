"""Every Step 37 candidate must have a readable reason and a caveat."""

import json
import unittest
from pathlib import Path

import duckdb

from python_pipeline.recommendation_evidence import explain


class RecommendationEvidenceTests(unittest.TestCase):
    def test_all_saved_candidates_have_rendered_evidence(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "parquet_data" / "step37-full" / "recommendation_candidates.parquet"
        output = root / "parquet_data" / "step38-full" / "recommendation_evidence.parquet"
        if not source.is_file() or not output.is_file():
            self.skipTest("Full evidence output is not available")
        con = duckdb.connect()
        source_count = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(source)]).fetchone()[0]
        rows = con.execute("""SELECT candidate_id,reason_lines_json,limitation,metrics_json
            FROM read_parquet(?)""", [str(output)]).fetchall()
        self.assertEqual(len(rows), source_count)
        self.assertEqual(len({row[0] for row in rows}), source_count)
        for _, reasons, limitation, metrics in rows:
            self.assertTrue(json.loads(reasons))
            self.assertTrue(limitation)
            self.assertIsInstance(json.loads(metrics), dict)

    def test_missing_required_measure_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing required evidence"):
            explain("review_preparation_quantity", {
                "wasted_quantity": None, "accounted_wastage_percentage": 30,
                "movement_class": "slow_moving", "quantity_sold": 10,
            })


if __name__ == "__main__":
    unittest.main()
