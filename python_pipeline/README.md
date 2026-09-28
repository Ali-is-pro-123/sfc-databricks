# Independent Python demand pipeline

This Step 13 runner reads only the accepted Step 5 clean Parquet tables. It
rebuilds local-day facts and monthly supervised features with DuckDB and fits
scikit-learn models in the Windows `uv` environment. It never reads Step 6
integrated facts or Step 12 Spark predictions as model inputs.

```powershell
uv sync
uv run python -m unittest python_pipeline.test_demand -v
uv run python -m python_pipeline.demand `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --output parquet_data/step13-full `
  --reports processed_data/step13-full `
  --model models/step13-full
```

Use new paths for a rerun; the runner refuses to overwrite existing results.
For a quick check, use `step05-small` and matching `step13-small` paths instead.
Outputs include a supervised Parquet snapshot, test prediction CSV, fitted
joblib pipeline and JSON lineage/metrics report. The predictions have stable
`restaurant_code`, `item_code`, `cutoff` keys for Step 14 comparison.

If only the prediction CSV needs to be rebuilt from this run's trusted local
snapshot and model, use:

```powershell
uv run python -m python_pipeline.export_predictions `
  --snapshot parquet_data/step13-full/supervised_snapshots.parquet `
  --model models/step13-full/python_demand.joblib `
  --output processed_data/step13-full/python_predictions.csv
```

The label is next-calendar-month accepted sold quantity for a previously sold
item/location. Train cutoffs are May–December 2025, validation January–February
2026, test March–June 2026. Feature windows stop strictly before each cutoff.
Validation chooses the model by MAE, then RMSE. Test remains untouched until
selection. This re-export overwrites the named CSV. Joblib files should only
be loaded from trusted local runs.
