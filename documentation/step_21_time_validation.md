# Step 21: Time-aware model validation

The SRS requires earlier training periods, later unseen testing periods, and
no future observations in model features. Step 20 already fitted direct
one-, two-, and three-month horizons with chronological target-month splits.
This step independently audits those temporal claims; Step 22 handles the
separate forecast-accuracy assessment.

## Plan and implementation

1. Verify the passed Step 20 report's hashes against the exact Step 5 and
   Step 13 inputs, then rebuild the forecast origin from accepted clean data.
2. For each horizon, join historical feature and target snapshots and check
   pair uniqueness, first-sale eligibility, exact month offset, no target at
   or after the origin, and training/validation/test row counts against the
   Step 20 report. The target-month split is train before January 2026,
   validation January–February, and unseen test March–June.
3. Recreate December 2025, February 2026, and June 2026 features after
   physically withholding all daily observations dated at or after each
   cutoff. Compare every predictor and key to the saved snapshots. Labels in
   these as-of snapshots must all be zero.
4. Save an immutable-style new audit report, refusing to overwrite an
   existing output folder. This is validation of temporal provenance, not
   evidence that forecast error is acceptable or deployment is approved.

## Run

```powershell
uv run python -m unittest python_pipeline.test_time_validation python_pipeline.test_forecast -v
uv run python -m python_pipeline.time_validation `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --python-report processed_data/step13-full/python_demand_report.json `
  --snapshot parquet_data/step13-full/supervised_snapshots.parquet `
  --forecast-report processed_data/step20-full/forecast_report.json `
  --output processed_data/step21-full
```

Use a new output directory for reruns. The full run passed: all three horizon
joins reconciled to Step 20 counts; as-of checks compared 4,294 December,
4,295 February, and 4,295 June pair snapshots with no mismatches. The report
is `processed_data/step21-full/time_validation_report.json`.

This checks selected boundary months rather than every historical cutoff.
It does not re-estimate held-out accuracy, address concept drift after the
June 2026 spike, or authorize inventory and staffing use.
