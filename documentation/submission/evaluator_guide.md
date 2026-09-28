# Installation and evaluator guide

Run commands from the repository root in PowerShell. This guide documents the
Windows + uv + Docker workflow used by the project. A clean-machine rehearsal
is still required before claiming a reproducible final release.

## 1. Prerequisites and runtime

- Windows with uv available and Docker Desktop running Linux containers.
- Host Python is pinned to 3.11.9 by `.python-version`; use `uv sync --locked`.
- Docker provides PostgreSQL 17.11, Redis 7.4 and Spark 3.5.9 with Java 17.
- Spark's Linux image contains PySpark and adds NumPy/SciPy through
  `config/spark.Dockerfile`. No separate Windows Java/PySpark install is needed.
- Network access is needed for initial package/image installation and Tailwind CDN styling.
- SRS lists 8/16 GB RAM and 500 GB free disk as environment guidance. This pack
  does not claim measured peak memory or a verified minimum disk requirement.

## 2. First installation

If `.env` does not exist, copy `.env.example` to `.env`. Preserve an existing
configuration. Set a random Django secret and local database credentials; keep
the PostgreSQL password and DATABASE_URL consistent. Never commit `.env`.

```powershell
uv sync --locked
docker compose up -d --build postgres redis spark-master spark-worker
docker compose ps
uv run python dine_iq/manage.py migrate
uv run python dine_iq/manage.py check
uv run python dine_iq/manage.py createsuperuser
```

`uv sync` creates the local `.venv`; activation is unnecessary when using
`uv run`. Choose evaluator credentials during account setup. No universal
username/password is shipped in source. Business-role accounts can be created
through Manage accounts; manager roles also need explicit location grants.

## 3. Existing analytical snapshot

The current populated demo depends on the verified data/report/model directories
listed in the stage documentation. They are ignored by Git, so cloning source
alone does not restore them. Obtain the eventual artifact bundle or regenerate
the stages. Public artifact download instructions are currently pending.

Once Step 5 clean Parquet and its passed quality report are available:

```powershell
uv run python dine_iq/manage.py import_clean_dataset --dry-run
uv run python dine_iq/manage.py import_clean_dataset
uv run python dine_iq/manage.py runserver 127.0.0.1:8000
```

Open `http://127.0.0.1:8000/accounts/login/`. The import command currently reads
the canonical `step05-full` directories. It is not a general configurable hidden
dataset loader. It preserves accounts and refuses partial/differently keyed
tables; it does not overwrite an existing database to accept a new dataset.

## 4. Generate and clean a new dataset

Choose unused output names. The example is a small rehearsal, not a replacement
for the current accepted full snapshot.

```powershell
uv run python -m data_generator --profile small --seed 42 --output raw_data/evaluator-small
uv run python -m data_generator --validate-only --output raw_data/evaluator-small
uv run python -m data_generator.evidence raw_data/evaluator-small
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/ingest.py --input /opt/dineiq/raw_data/evaluator-small/raw --output /opt/dineiq/parquet_data/evaluator-small --reports /opt/dineiq/processed_data/evaluator-small
```

For SRS-scale generation use `--profile full` and a fresh output directory.
Do not use `clean_reference/` or scenario labels as pipeline input. Host paths
under `raw_data/`, `parquet_data/`, `processed_data/` and `models/` appear under
`/opt/dineiq/` inside Spark containers.

## 5. Processing and execution map

Each stage document below describes input, output, tests and commands. Follow
dependency order. Reruns need fresh output/report/model directories and explicit
downstream input updates; there is no claimed one-command full rebuild.

| Task | Instructions |
| --- | --- |
| Raw generation/schema/quality | [Step 4](../step_04_generation.md), [Step 5](../step_05_spark.md) |
| Joins and Spark SQL | [Step 6](../step_06_integration.md), versioned `spark_sql/` queries invoked by jobs |
| Features, EDA, menu economics/classes | [Step 7](../step_07_features.md), [8](../step_08_eda.md), [9](../step_09_profitability.md), [10](../step_10_classification.md), [11](../step_11_tricky_cases.md) |
| Spark model training | [Step 12](../step_12_spark_models.md) |
| Independent Python model | [Step 13](../step_13_python_pipeline.md); `uv run python -m python_pipeline.demand --help` lists required arguments |
| Prediction comparison | [Step 14](../step_14_dual_verification.md) |
| Customer segmentation and RFM | [Step 15](../step_15_customer_segmentation.md), [16](../step_16_rfm_analysis.md) |
| Basket discovery and candidates | [Step 17](../step_17_market_basket.md), [18](../step_18_recommendations.md) |
| Peak periods and forecasts | [Step 19](../step_19_peak_periods.md), [20](../step_20_configurable_forecast.md), [21](../step_21_time_validation.md), [22](../step_22_forecast_accuracy.md) |
| Wastage | [Step 23](../step_23_wastage_analysis.md), [24](../step_24_wastage_risk.md) |
| Price and promotions | [Step 25](../step_25_price_intelligence.md), [26](../step_26_price_sensitivity.md), [27](../step_27_promotion_effectiveness.md), [28](../step_28_promotion_traps.md) |
| Ratings, anomalies, slow movers | [Step 29](../step_29_rating_satisfaction.md), [30](../step_30_rating_anomalies.md), [31](../step_31_sales_anomalies.md), [32](../step_32_slow_moving.md) |
| Locations, channels and churn | [Step 33](../step_33_multi_location.md), [34](../step_34_location_menu_performance.md), [35](../step_35_ordering_channels.md), [36](../step_36_churn_risk.md) |
| Recommendations | [Step 37](../step_37_recommendation_engine.md), [38](../step_38_recommendation_evidence.md), [39](../step_39_recommendation_priority.md) |
| Simulations and impacts | [Step 40](../step_40_what_if_scenarios.md), [41](../step_41_scenario_impact.md) |
| Web dashboards | [Steps 42](../step_42_executive_dashboard.md)-[48](../step_48_search_filtering.md) |
| Reports and exports | [Step 49](../step_49_downloadable_reports.md), [50](../step_50_data_export.md) |

Authoritative variants include `step11-full-v2`, `step14-full-verified`,
`step18-full-verified`, `step19-full-verified`, `step23-accepted-full`,
`step24-verified-full`, `step28-verified-full` and `step35-verified-full`.
Consult each stage and downstream service for the exact required path/hash.

## 6. Browser evaluation

1. Sign in and inspect the grouped sidebar or mobile menu. Confirm role identity.
2. Open Locations and a location detail. Confirm accessible scope.
3. Open Dashboard and compare the 90-day cutoff with stored lifetime counts.
4. Review Menu intelligence, Customer intelligence, Wastage intelligence and Forecast intelligence.
5. Open Spark vs Python; inspect an actual/prediction mismatch and its tolerance.
6. Try Analytics search filters and use the CSV export for all matching rows.
7. Review recommendation evidence and assumptions before using What-if scenarios.
8. Download an HTML report through Reports; open it offline and inspect scope/limits.
9. Repeat appropriate access checks with a manager assigned one location and an
   account with no grants. Use test accounts created for evaluation.

Data changes in the management interface do not automatically regenerate saved
analytics. The current forecast is an archived July-September 2026 snapshot.

## 7. Tests and troubleshooting

```powershell
uv run python dine_iq/manage.py test apps --noinput
uv run python -m unittest discover -s python_pipeline -p 'test_*.py'
uv run python -m unittest tests.test_generator
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master local[2] /opt/dineiq/spark_jobs/test_quality.py
```

Additional Spark fixture scripts and commands are listed in their stage documents.
Django tests create a separate PostgreSQL test database; the database user needs
permission to create it. Do not point a test configuration at a shared production database.

| Symptom | Check |
| --- | --- |
| Database connection refused | Docker Desktop, `docker compose ps`, port and DATABASE_URL consistency |
| Empty location scope | Import clean domain records; check role and location grants |
| Evidence unavailable | Passed source report, expected hashes/paths, Parquet success marker and full artifact bundle |
| Existing output path refused | Choose a new run name and update dependent inputs; preserve old evidence |
| Missing NumPy/SciPy in Spark | Build the project's Spark image for both services |
| Unstyled pages | Tailwind CDN connectivity; local static asset serving |
| Template remains old | Restart a development server started with `--noreload` |
| Spark job failure | Inspect `docker compose logs spark-master spark-worker` and the stage report; do not consume partial output |

Spark master UI: `http://127.0.0.1:18080`; worker UI: `http://127.0.0.1:18081`.
These are infrastructure interfaces, not a Django job-monitoring feature.

## 8. Hidden-data readiness and release rehearsal

Preserve a new, schema-compatible raw dataset with unseen values. Run schema and
quality checks, inspect rejected-parent cascades and exact conservation, then
rebuild features/models with new output paths. Compare key sets and actual labels
before calculating model agreement. Include unknown menu codes, a new location,
price changes, missing values, duplicates and extreme waste. Record pass/fail
without adding the generator's private scenario labels to predictors.

Fixtures cover several of these cases, but a complete unseen dataset rehearsal
has not been certified. The canonical importer/web source-path configuration
needs review for this workflow. Complete the [traceability gaps](requirements_traceability.md)
and release checklist before declaring hidden-data or deployment readiness.
