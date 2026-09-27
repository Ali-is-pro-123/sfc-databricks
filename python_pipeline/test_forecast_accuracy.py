"""Metric edge cases and Step 20 reconciliation checks."""

import unittest

from python_pipeline.forecast_accuracy import accuracy, compare_prior


class ForecastAccuracyTests(unittest.TestCase):
    def test_zero_actual_is_excluded_from_mape_only(self):
        result = accuracy([0, 2, 4], [1, 1, 5])
        self.assertEqual(result["zero_actual_rows"], 1)
        self.assertEqual(result["mape_eligible_rows"], 2)
        self.assertAlmostEqual(result["mape_percent_nonzero_actual"], 37.5)
        self.assertAlmostEqual(result["mae"], 1)
        self.assertAlmostEqual(result["wape"], 0.5)

    def test_undefined_mape_and_r2_are_null(self):
        result = accuracy([0, 0], [1, 2])
        self.assertIsNone(result["mape_percent_nonzero_actual"])
        self.assertIsNone(result["wape"])
        self.assertIsNone(result["r2"])

    def test_invalid_inputs_and_prior_mismatch_fail(self):
        with self.assertRaisesRegex(ValueError, "aligned"):
            accuracy([1], [1, 2])
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            accuracy([1], [-1])
        prior = {"rows": 2, "mae": 0, "rmse": 0, "wape": 0,
                 "actual_quantity": 3, "mean_error": 0}
        with self.assertRaisesRegex(ValueError, "held-out mae differs"):
            compare_prior([1, 2], [2, 2], prior)


if __name__ == "__main__":
    unittest.main()
