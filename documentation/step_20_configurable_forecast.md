# Step 20: Configurable demand forecasting

## Plan before implementation

SRS page 15 requires future forecasts for menu items, categories and
restaurant locations over selected periods. Step 13 already established an
independent Python next-month item/location demand task. This step extends
that foundation to a bounded, configurable 1–3 calendar-month horizon. It
does not claim deployment approval; formal validation and accuracy review
remain Steps 21–22.

1. Require a passed Step 13 full Python report/snapshot and passed Step 5
   clean-source quality report, with matching source counts and record keys.
   Rebuild inference history from Step 5 accepted clean records using the
   independent Python/DuckDB daily and feature SQL. The forecast origin must
   be the first day after the latest observed local month, so no partial
   future month is silently treated as complete.
2. At origin 2026-07-01, produce features only from records dated before
   origin for previously sold item/location pairs. Verify July features
   against the same SQL applied at prior historical cutoffs. Exclude
   never-sold pairs as explicit cold starts, not zero forecasts.
3. Construct direct horizon targets from the Step 13 supervised snapshot:
   horizon 1 uses its next-month label; horizon 2 uses the same pair's label
   at the following cutoff; horizon 3 uses the label two cutoffs later.
   Split by *target month*: train targets before Jan 2026, validate Jan–Feb,
   hold out Mar–Jun. No training target extends into validation/test, and
   preprocessing fits training rows only.
4. Fit an Extra Trees pipeline per horizon with the Step 13 feature list and
   fixed hyperparameters. Compare validation MAE with a horizon-length-
   adjusted recent-30-day baseline. Select model or baseline before looking
   at each horizon's test. Record test MAE/RMSE/WAPE. For a selected model,
   refit the same specification on all now-observed targets through June
   solely for future inference; never report those refitted predictions as
   held-out test results.
5. Forecast the requested 1–3 future months directly from the same July
   feature snapshot. Each horizon-specific model learns the target month's
   seasonal offset from the origin month; the baseline alone adjusts to
   each target month's length. Do not recursively invent future order, revenue, rating or
   waste observations. Persist item/location forecasts and additive item,
   category, category/location and location rollups. Verify every period's
   total at each grain, nonnegative finite values, model reload, unique keys
   and source/period lineage. Test temporal boundaries and full/small runs.

## Limits

The target is accepted sold portions, not unconstrained latent demand.
Stockouts, rejected lines and never-sold pairs are not recovered. A direct
2–3-month model uses older observed features and may miss sharp regime
changes; June 2026's synthetic spike makes uncertainty material. No
inventory/preparation decision should rely on these forecasts without human
review and Steps 21–22 validation.

## Run and verified result

```powershell
uv run python -m unittest python_pipeline.test_forecast python_pipeline.test_demand -v
uv run python -m python_pipeline.forecast `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --python-report processed_data/step13-full/python_demand_report.json `
  --snapshot parquet_data/step13-full/supervised_snapshots.parquet `
  --start-month 2026-07-01 `
  --months 3 `
  --output parquet_data/new-step20-full `
  --reports processed_data/new-step20-full `
  --models models/new-step20-full
```

Use unused output/report/model paths. `--start-month` may select July,
August or September 2026, while `--months` chooses one to three contiguous
months within that three-month horizon. The origin follows the latest
observed month automatically. A separate small run selected only August
and September, verifying that period selection does not require July output.

The verified full files are in `parquet_data/step20-full/`, with
`processed_data/step20-full/forecast_report.json` and refitted operational
models in `models/step20-full/`. Two Step 20 and three Step 13 tests passed.
Small and full runs passed. Full origin is 2026-07-01: 4,295 rebuilt June
rows matched Step 13 features/labels, and 4,320 previously sold pairs were
eligible in July. The current synthetic catalog has no never-sold pair at
this origin; the pipeline still reports cold starts explicitly.

Full July/August/September item-location forecasts have 12,960 rows. Their
summed expected sold portions are 133,225.32, 143,987.80 and 129,348.88.
Each month's totals agree across item, category, category/location and
location Parquet rollups. Validation chose Extra Trees for all three direct
horizons. Held-out MAE before operational refit was 8.785, 9.081 and 9.386
portions for horizons one, two and three. Each operational model was then
refit on all labels available through June and reload-checked. The held-out
metrics belong to the earlier validation-selected fit, not the refitted
operational artifact.

March–June 2026 held-out actual accepted quantity totaled 332,920; June alone
was 142,995, far above the prior monthly pattern. Whether that spike persists
is unknown. This is a review-only forecast,
not an approved inventory or staffing instruction.
