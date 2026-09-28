# Spark Jobs

Run these modules through `spark-submit` inside the pinned Spark container.
Do not install PySpark into the Windows Django environment.

- `ingest.py`: raw CSV ingestion, header validation, typed cleaning, partitioned
  Parquet output, quarantine, and persisted quality reports.
- `quality.py`: reusable Spark SQL expression-based validation rules.
- `test_quality.py`: regression tests runnable with `--master local[2]`.
- `integrate.py`: verified line, order-coverage, and daily operational grains.
- `test_integration.py`: adversarial joins, money, time and coverage tests.
- `features.py`: cutoff/window-aware item, customer, basket and location features.
- `test_features.py`: hand-calculated temporal, RFM, ratio and coverage checks.
- `eda.py`: full-period descriptive tables, ranked findings and reconciliation.
- `test_eda.py`: basket, promotion, rating, waste, time-bin and cutoff checks.
- `profitability.py`: multi-dimensional item/location profitability and
  exposure-aware 30-day sales trends.
- `test_profitability.py`: period, loss-making volume and missing-evidence checks.
- `classify.py`: peer-relative item-wide and item/location business-rule classes.
- `test_classify.py`: class precedence, tricky cases and aggregate-grain tests.
- `case_audit.py`: evidence audit for all ten SRS difficult menu cases.
- `test_case_audit.py`: adversarial case, seasonality and cutoff tests.
- `train_demand.py`: chronology-safe Spark MLlib next-month demand comparison.
- `test_train_demand.py`: temporal leakage, metric and candidate checks.

See `documentation/step_05_spark.md` for exact PowerShell commands, output
contracts, verification evidence, and remaining boundaries. The standalone
cluster run uses a master and worker; local mode is only used for fast tests.
Integration commands and policies are in `documentation/step_06_integration.md`.
Feature definitions and snapshot commands are in `documentation/step_07_features.md`.
EDA definitions, rankings and run commands are in `documentation/step_08_eda.md`.
Profitability definitions and verification are in `documentation/step_09_profitability.md`.
Classification rules and evidence are in `documentation/step_10_classification.md`.
Tricky-case audit policy and verification are in `documentation/step_11_tricky_cases.md`.
MLlib model design, metrics and commands are in `documentation/step_12_spark_models.md`.
