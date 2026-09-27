# Step 13: Independent Python data-science pipeline

## Plan

SRS page 13 requires a separate Python pipeline that independently processes
the same underlying restaurant records. It must not export and reuse Spark
predictions as Python results. This step independently rebuilds the Step 12
next-calendar-month item/location demand task from the Step 5 accepted clean
Parquet tables using Python, DuckDB and scikit-learn, all managed by uv on
Windows. Step 14 will compare the two pipelines record by record.

1. Require a passed Step 5 quality report, successful clean Parquet for each
   required source table, matching accepted row counts and unused output,
   report and model paths. Read only `orders`, `order_items`, `restaurants`,
   `menu_items`, `ratings` and `wastage` from Step 5 clean data.
2. Recreate completed line sales with restaurant-local dates, quantity,
   revenue, direct cost and contribution. Aggregate sales, rating events by
   their submission date, and recorded waste independently before joining at
   item/location/day grain. Reconcile completed sales money/quantity directly
   to the accepted clean rows. Do not read Step 6 integration or Step 12
   model-generated features, labels or predictions.
3. Independently generate first-of-month cutoff rows and known item/location
   pairs. Calculate exactly the same historical windows and next-calendar-
   month accepted-sales target as Step 12 using SQL written for DuckDB, not
   Spark SQL output. Use train May-Dec 2025, validation Jan-Feb 2026 and
   untouched test Mar-Jun 2026.
4. Fit scikit-learn preprocessing only on training rows. Train at least one
   suitable regression model and compare with the recent-demand baseline on
   validation MAE/RMSE/WAPE. Select before viewing the test. Retain exact
   record keys, actual target and Python prediction in the output for the
   later dual-pipeline comparison.
5. Persist a DuckDB-built supervised snapshot, Python test predictions,
   fitted model and lineage/metric report. Verify unique record keys,
   financial/target conservation, chronological boundaries, no future
   observations in predictors, model reload, and small/full real-data runs.

## Independence and limits

- The shared source is accepted Step 5 clean restaurant data, not the Spark
  integrated daily table or Spark MLlib fitted artifacts. Using the same
  cutoff/target definition is intentional; reusing Spark predictions is not.
- The source is synthetic and cleaned by Step 5; this is independent feature
  construction/model fitting, not independent raw-data quality processing.
- Known-pair eligibility and accepted-sales target represent observed sales,
  not latent demand. New never-sold pairs, rejected lines and stockouts remain
  outside this model's reliable scope.
- Model selection uses validation only; test results are descriptive and do
  not confer deployment approval. Step 14 owns formal Spark/Python agreement
  and disagreement analysis.
