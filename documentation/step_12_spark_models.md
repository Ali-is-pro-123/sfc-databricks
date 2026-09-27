# Step 12: Spark MLlib model development

## Plan

SRS page 12 requires at least three suitable Spark MLlib algorithms to be
trained, compared and selected with evaluation metrics. This step chooses a
bounded predictive task: next-calendar-month sold portions for a restaurant
and menu-item pair with at least one prior accepted sale. This is a model
comparison exercise, not the final configurable demand-forecast workflow of
SRS Step 20. Do not use Step 10 rule classes or generator evaluation labels as
training targets.

1. Require a passed Step 6 integration report and matching quality report,
   immutable integrated daily Parquet, a complete observation horizon and
   unused output/model/report directories. Record source/job hashes.
2. At each first-of-month cutoff, include only item/location pairs with a
   completed sale before that cutoff. Derive past 30-day, prior 30-day and
   past 90-day demand, orders, money, waste, rating observations and sales-day
   measures strictly before cutoff. The label is accepted sold portions in
   `[cutoff, add_months(cutoff, 1))`; it is never an input feature.
3. Use monthly cutoffs from 2025-05-01 through 2026-06-01. Train on May-Dec
   2025, validate on Jan-Feb 2026, and hold out Mar-Jun 2026. Label windows
   do not overlap across these split boundaries. Fit category/location
   encoders and any scaling only on training rows.
4. Train regularized linear regression, decision-tree regression and random-
   forest regression with fixed seeds/configurations. Compare clipped-to-zero
   demand predictions with a seasonal-length-adjusted recent-30-day baseline
   on validation MAE, RMSE and WAPE. Select by validation MAE then RMSE;
   inspect the untouched test period once for the selected candidate.
5. Persist the supervised snapshot (with visibly separate future target),
   holdout predictions, fitted winning pipeline and a report with split
   counts, periods, metrics and lineage. Verify unique row grain, target
   conservation against the source, no date leakage, reproducible test fixture
   behavior and model/read-back success.

## Important boundaries

- This predicts only pairs already observed before each cutoff. New, never-
  sold pairs are outside the model's scope and need a cold-start strategy.
- Source targets describe accepted sales, not latent unconstrained demand;
  stockouts and quarantined sales can cause undercounting.
- Last-90-day ratings are grouped by observation day in Step 6, so ratings
  submitted after a cutoff are excluded. Missing ratings retain an indicator
  rather than being misread as a literal zero-star score.
- The dataset is synthetic. Temporal holdout scores do not prove production
  accuracy. If the naive baseline outperforms all trained models, the best
  candidate is recorded but must not be called deployment-ready.
- The later independent Python pipeline must construct its own features from
  the same underlying records, not import these fitted Spark predictions.

## Runtime and commands

The original pinned Spark image lacked NumPy/SciPy required by PySpark MLlib.
`config/spark.Dockerfile` extends it with Ubuntu's Python 3.10 NumPy/SciPy
packages, and both master and worker use that same image. The first pip-wheel
build timed out on a slow download; the OS-package build succeeded. Existing
bind-mounted data and PostgreSQL/Redis volumes were preserved. Host Django
dependencies remain managed by uv; PySpark is not installed into the Windows
uv environment.

```powershell
docker compose build spark-master
docker compose up -d --no-build --no-deps spark-master spark-worker
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master local[2] /opt/dineiq/spark_jobs/test_train_demand.py
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/train_demand.py --input /opt/dineiq/parquet_data/step06-full --integration-report /opt/dineiq/processed_data/step06-full/integration_report.json --output /opt/dineiq/parquet_data/new-demand-full --reports /opt/dineiq/processed_data/new-demand-full --model /opt/dineiq/models/new-demand-full
```

Every rerun must use new output/report/model paths. The report distinguishes
training, validation and test results and explicitly states whether the
recent-30-day baseline beat the selected model on validation.

## Verification evidence

Three targeted Spark fixture tests passed, including a counterfactual future
sales spike that changed the label but left pre-cutoff features unchanged.
Docker Desktop was restarted using its existing installation when the engine
was initially stopped. The extended Spark image was built and both services
recreated without resetting source data, output directories, or other volumes.

The small run passed in 179.238 seconds: 1,948 supervised rows (1,108 train,
280 validation, 560 test). Random forest had the lowest small-validation MAE
(1.954 portions). Its test MAE was 3.425 versus the baseline's 3.946. This
small run is a pipeline rehearsal; it does not choose the full-data model.

The full run passed in 191.930 seconds. Outputs are
`parquet_data/step12-full/supervised_snapshots/` (60,105 rows) and
`parquet_data/step12-full/heldout_predictions/` (17,180 rows). The fitted
winner is in `models/step12-full/`, with read-back verified. The report is
`processed_data/step12-full/demand_model_report.json`.

| Full-data validation candidate | Rows | MAE | RMSE | WAPE |
| --- | ---: | ---: | ---: | ---: |
| Linear regression | 8,589 | 4.289 | 6.858 | 31.66% |
| Decision tree | 8,589 | 4.779 | 12.251 | 35.27% |
| Random forest | 8,589 | 4.834 | 12.495 | 35.68% |
| Recent-30-day baseline | 8,589 | 4.360 | 6.902 | 32.18% |

Linear regression was selected on validation MAE before viewing the held-out
test metrics. On 17,180 test rows its MAE was 9.043 versus baseline 9.422,
and WAPE was 46.67% versus baseline 48.62%. Its test RMSE was 41.380,
slightly worse than baseline 41.158, indicating large-error cases remain.
The report retains the 34,336/8,589/17,180 chronological train/validation/
test row counts, all candidate metrics, baseline metrics and selected-model
test predictions. The total future labels (944,315 portions over all
snapshots) reconcile to accepted source daily sales for eligible known pairs.

This outcome supports a working SRS model comparison, not deployment readiness.
The saved model was fitted on training rows only; future retraining must use
a newly defined cutoff and keep an untouched later evaluation period.
