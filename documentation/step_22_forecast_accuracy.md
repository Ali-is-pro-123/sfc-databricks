# Step 22: Forecast accuracy evaluation

## Plan and implementation

The SRS asks for MAE, RMSE, MAPE and R² where appropriate. Step 20 saved
aggregate MAE/RMSE/WAPE but not row-level held-out predictions. This step
recreates the same frozen train split, preprocessing and Extra Trees settings
from the trusted Step 13 snapshot. It selects the method using validation
only, scores the March–June 2026 unseen target months, and reconciles every
aggregate metric to the Step 20 report. The Step 21 temporal audit and all
source hashes must also pass.

The new report provides selected-method and baseline metrics overall and by
target month for each direct horizon. MAPE excludes zero-actual rows and
reports how many were excluded; those rows still count in MAE, RMSE and
WAPE. R² is null when actual values have no variance. There is no SRS
acceptance threshold, so a passing report means the evaluation is valid,
not that forecast quality is approved. July–September predictions have no
actuals and are not scored.

## Run

```powershell
uv run python -m unittest python_pipeline.test_forecast_accuracy python_pipeline.test_time_validation python_pipeline.test_forecast -v
uv run python -m python_pipeline.forecast_accuracy `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --python-report processed_data/step13-full/python_demand_report.json `
  --snapshot parquet_data/step13-full/supervised_snapshots.parquet `
  --forecast-report processed_data/step20-full/forecast_report.json `
  --time-report processed_data/step21-full/time_validation_report.json `
  --output processed_data/step22-full
```

Use a new output folder on rerun. The full report is
`processed_data/step22-full/forecast_accuracy_report.json`.

## Full-data result and limits

The three selected direct-horizon models improve held-out MAE over the
recent-30-day baseline by 6.76%, 5.65% and 4.61%. Overall held-out MAE is
8.79, 9.08 and 9.39 portions; RMSE is 41.16, 41.47 and 41.67. Nonzero-row
MAPE is 51.36%, 54.14% and 59.45%; R² is 0.301, 0.290 and 0.284. There
are 864, 864 and 863 zero-actual rows respectively, excluded only from MAPE.

June 2026 alone has 142,995 actual accepted portions, versus 60,509,
58,462 and 56,220 predicted across horizons. Its large miss is why this
forecast remains review-only despite modest overall MAE improvements.
The synthetic spike may reflect regime change. Human review and new data
are required before operational decisions.
