# Step 14: Dual-pipeline demand verification

## Plan before implementation

SRS page 13 requires a report for at least one major task implemented
independently in Spark MLlib and Python Data Science. Step 12 and Step 13 both
predict accepted sold portions in the next calendar month for a previously
sold restaurant/item pair, with the same chronological cutoffs. This step
compares their saved outputs only; it must not retrain or feed one pipeline's
predictions into the other.

1. Require passed Step 12/13 reports, successful Spark Parquet markers,
   existing Python CSV/snapshot, matching cutoff and split definitions, and
   unused output paths. Check reported counts against actual files.
2. Audit the full supervised snapshot population by `(restaurant_code,
   item_code, cutoff)`: unique keys on both sides, no missing/extra rows,
   exact accepted-sales labels, and comparable historical features. Fail the
   comparison if keys or actual labels diverge; report feature differences.
3. Join held-out predictions on the same record ID. Check 17,180 expected
   rows (or the report's count), no duplicate/missing IDs, equal actuals and
   baselines, finite and nonnegative predictions, and reported model names.
4. For each record, emit actual quantity, Spark and Python results, signed and
   absolute numerical difference, match/mismatch and an honest explanation
   code. Numerical agreement means absolute difference at most the larger of
   **2 portions or 20% of the actual quantity**. This is a disclosed analysis
   tolerance, not a requirement that independent models be exactly equal.
   Separately report exact equality and tolerance-based agreement.
5. Summarize agreement percentage, per-month metrics, each pipeline's
   held-out MAE/RMSE/WAPE, disagreement reasons, largest differences and
   source/model lineage. Compare recomputed metrics to the respective model
   reports. Save record-level CSV and JSON summary. Test mismatch, tolerance,
   and duplicate-key edge cases with fixtures; run small and full data.

## Interpretation boundary

A mismatch is expected for independently trained model families. Explanations
are diagnostic categories based on observed features and forecast behavior,
not causal claims. Agreement does not establish accuracy or deployability;
actual-value errors must be shown alongside agreement. The comparison does
not alter Step 12 or 13 models, features or predictions.

## Run and verified result

```powershell
uv run python -m unittest python_pipeline.test_compare_demand -v
uv run python -m python_pipeline.compare_demand `
  --spark parquet_data/step12-full `
  --spark-report processed_data/step12-full/demand_model_report.json `
  --python parquet_data/step13-full `
  --python-csv processed_data/step13-full/python_predictions.csv `
  --python-report processed_data/step13-full/python_demand_report.json `
  --output processed_data/new-step14-full
```

The output path must not exist. The verified full report is
`processed_data/step14-full-verified/comparison_report.json`; its row-level
companion is `record_comparison.csv`. The small rehearsal is in
`processed_data/step14-small/`.

All 60,105 supervised keys, actual labels, splits, and the compared historical
features agreed between Spark and Python. The full held-out set has 17,180
unique paired records. Under the disclosed tolerance, 15,239 records match:
**88.70% agreement**. Exact model prediction equality is zero, as expected
for independently fitted models. Mean absolute prediction difference is
1.569 portions. Spark MAE is 9.043 and Python MAE is 8.785; both recompute
from the saved predictions and agree with their training reports. These
metrics are not an assertion that the Python model is ready for deployment.

Among 1,941 numerical mismatches, 1,432 are general model sensitivity, 464
coincide with a sharp change from the recent-demand baseline, 32 have sparse
historical sales days, and 13 are high-volume records. These codes are
diagnostic descriptions, not proven causes. June 2026 has the lowest monthly
agreement (85.19%) and both models' highest monthly MAE (Spark 24.52, Python
24.07). This is a material forecasting limitation for later work.
