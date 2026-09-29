# DineIQ Analytics

DineIQ is a Big Data and Data Science powered restaurant intelligence platform.
It combines a Django web application with PostgreSQL, Redis, Apache Spark,
PySpark, Spark SQL, Spark MLlib, and an independent Python machine-learning
pipeline.

## Current status

Steps 1–50 are implemented: infrastructure, PostgreSQL migrations, accounts, four
business roles, restaurant domain models, scoped location pages, and domain
management, a validated SRS-scale synthetic dataset, and verified Spark
ingestion/quality processing with clean and quarantine Parquet outputs.
Analytical integration, cutoff-aware feature engineering, descriptive EDA,
multi-dimensional menu profitability analysis, and auditable peer-relative
menu classification, tricky-case audits, and a chronologically validated
three-model Spark MLlib comparison, an independently constructed Python
demand pipeline, record-level dual-pipeline verification, rule-based
customer segmentation, formal RFM scoring, support/confidence/lift-based
market-basket analysis, review-only bundle/cross-sell candidates,
local-time peak-period analysis, bounded configurable monthly forecasting,
formal time-aware forecast validation, held-out forecast accuracy evaluation,
descriptive wastage analysis, exploratory monthly wastage-risk prediction,
descriptive price intelligence, and evidence-gated item/location price-
sensitivity classes are implemented. The risk model's held-out discrimination
is weak; no item-wide price-sensitivity class had sufficient evidence.
These results are review-only. Promotion-effectiveness measures and
evidence-gated potential-trap flags are now available without an automatic
success label. Rating/satisfaction relationships and review-only rating
anomaly flags are now available with explicit coverage and historical
baselines. Sales/order/demand anomaly checks are also available as review
signals. Multi-signal slow-moving dish detection is also available with
new-item abstention. Reconciled 90-day multi-location intelligence is also
available. Location-specific menu class comparisons are also available;
ordering-channel comparisons and review-only customer churn-risk signals are
also available. Review-only recommendation candidates and a scoped Django
evidence page with review priorities, read-only what-if impact analysis and a
role-scoped executive, menu, customer and wastage dashboards are also available.
CSV/Excel-compatible analytical data export is available for selected dashboards.
The verified Step 5 clean dataset can now be imported into the Django
PostgreSQL domain tables without changing accounts or passwords. See
`documentation/django_clean_import.md` for validation and rerun behavior.

## Development architecture

- Django runs on Windows through `uv`.
- PostgreSQL, Redis, and the Spark standalone cluster run through Docker Compose.
- Tailwind CSS is loaded through its CDN in Django templates.
- Large generated datasets, Parquet files, and trained models stay outside Git.
- Windows/Django Python dependencies are managed through `pyproject.toml` and
  `uv.lock`; Spark-container scientific packages are defined in its Dockerfile.
- The Docker Hub image is the **Spark runtime only**. It does not contain the
  Django web server, PostgreSQL, Redis, or generated data/model artifacts.

See `documentation/architecture.md` for the full architecture and folder map.

## First-time setup

1. Create the local environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Install the locked Python environment:

   ```powershell
   uv sync
   ```

3. Start the infrastructure services:

   ```powershell
   docker compose up -d postgres redis spark-master spark-worker
   ```

4. Check the Django configuration:

   ```powershell
   uv run python dine_iq/manage.py check
   ```

5. View the Spark interfaces:

   - Master: http://localhost:18080
   - Worker: http://localhost:18081

6. Apply migrations and create your first administrator (once):

   ```powershell
   uv run python dine_iq/manage.py migrate
   uv run python dine_iq/manage.py createsuperuser
   ```

   Choose your own username and password when prompted. The superuser receives
   the Administrator business role automatically. No default account is shipped.

   After the Step 5 clean Parquet and passed quality report exist, populate
   the Django domain database (this does not alter user accounts):

   ```powershell
   uv run python dine_iq/manage.py import_clean_dataset --dry-run
   uv run python dine_iq/manage.py import_clean_dataset
   ```

7. Start the application on a port separate from the other local project:

   ```powershell
   uv run python dine_iq/manage.py runserver 127.0.0.1:8001
   ```

   Open http://127.0.0.1:8001/accounts/login/ and sign in. Use **Manage accounts**
   to create users with one of the four business roles. Superusers can use
   http://127.0.0.1:8001/admin/ to edit accounts, deactivate them, or reset passwords.

The `.env` file is local and ignored by Git. Keep your existing `.env` when
repeating setup; do not overwrite its generated secret key with the example.

## Account tests

```powershell
uv run python dine_iq/manage.py test apps.accounts
uv run python dine_iq/manage.py makemigrations --check --dry-run
```

See `documentation/step_02_accounts.md` for the role matrix and boundaries.

## Restaurant management

Open http://127.0.0.1:8001/management/ as an Administrator. This business panel
does not require the Django staff flag and does not expose account privilege flags.

Create records in this order:

1. Restaurants, menu categories, menu items, ordering channels, and customers.
2. Pricing history events for each location/item and promotion campaigns.
3. Orders, followed by their order lines and ratings.
4. Inventory snapshots and wastage records.
5. Location access grants for Restaurant Managers and Regional Managers.

Open http://127.0.0.1:8001/locations/ to view accessible locations and current
menu prices. Administrators and Analysts can read all locations; manager roles
see only explicitly assigned locations. No demo records are seeded automatically.

```powershell
uv run python dine_iq/manage.py test apps.accounts apps.restaurants
```

See `documentation/step_03_domain.md` and `documentation/data_dictionary.md`
for planning, units, relationships, and validation boundaries.

## Synthetic data

The verified full run is in `raw_data/full-seed42/`. Use only its `raw/` layer for
future ingestion. The clean reference and evaluation labels are test oracles,
not substitutes for independent cleaning or model outputs.

```powershell
uv run python -m data_generator --profile small --output raw_data/new-small-run
uv run python -m data_generator --profile full --output raw_data/new-full-run
uv run python -m data_generator --validate-only --output raw_data/full-seed42
uv run python -m unittest tests.test_generator -v
```

Existing output directories are refused. See `documentation/step_04_generation.md`
for configuration, schemas, counts, known assumptions, and verification results.

## Spark ingestion and quality

The full raw dataset has been processed independently by Spark. The verified
outputs are `parquet_data/step05-full/clean/` and `parquet_data/step05-full/quarantine/`.
The report at `processed_data/step05-full/quality_report.json` has status `passed`:
3,995,252 accepted and 21,796 quarantined records across 13 tables, including
1,035,861 accepted order lines. All five transaction tables cover 18 monthly
partitions. The accepted outputs are now imported into Django PostgreSQL through
`import_clean_dataset`; the import preserves existing accounts.

```powershell
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master local[2] /opt/dineiq/spark_jobs/test_quality.py
```

See `documentation/step_05_spark.md` for full job commands, cleaning policy,
verification counts, and limitations. Jobs refuse existing output directories.

## Analytical integration

Verified Step 6 outputs are in `parquet_data/step06-full/`: `order_lines`,
`order_coverage`, and `item_location_daily`. The integration report is in
`processed_data/step06-full/integration_report.json`. Source-to-fact and daily
monetary totals match; partial orders and inventory coverage gaps remain visible.
See `documentation/step_06_integration.md` for commands, grains and limitations.

## Feature snapshots

Verified features are in `parquet_data/step07-full/`, using an exclusive local
cutoff of 2026-07-01 and a 90-day analysis window. Outputs contain 4,320
item/location rows, 60,000 customers, 73,982 completed baskets and 24 locations.
The passed report is `processed_data/step07-full/feature_report.json`.
See `documentation/step_07_features.md` for feature definitions, temporal and
coverage policies, tests and rerun commands. These are not model predictions.

## Exploratory data analysis

Verified Step 8 outputs are in `parquet_data/step08-full/`, with ten
reconciled item, category, location, channel, promotion, and time-grain tables.
The passed report is `processed_data/step08-full/eda_report.json`. It covers
180 items and 18 months through the exclusive local cutoff of 2026-07-01.
See `documentation/step_08_eda.md` for the plan, definitions, tests, full-run
evidence, and rerun commands. Contribution is not net profit, and promotion
attribution is not causal lift.

## Menu profitability analysis

The verified Step 9 item/location snapshot is in `parquet_data/step09-full/`.
Its passed report is `processed_data/step09-full/profitability_report.json`.
It combines the 90-day sales/cost, rating, repeat, waste and promotion features
with exposure-aware 30-day sales trends for 4,320 item/location pairs.
See `documentation/step_09_profitability.md` for planning, measures, limitations,
tests and rerun commands. Step 9 itself does not assign menu classes.

## Menu performance classification

Step 10 classifies all 180 menu items and 4,320 item/location rows into the
four SRS categories. Verified Parquet is in `parquet_data/step10-full/`, and
the passed report is `processed_data/step10-full/classification_report.json`.
The peer-relative rules retain reasons, risk flags and provisional evidence;
they are not fitted ML predictions. See `documentation/step_10_classification.md`
for the decision policy, tests, class counts and rerun command.

## Tricky-case audit

Step 11 checks all ten SRS difficult menu cases against the classified data.
The verified full audit is in `parquet_data/step11-full-v2/`, with its passed
report at `processed_data/step11-full-v2/case_audit_report.json`. It retains
180 item-wide and 4,320 location-level rows, flags evidence, and checks that
loss-making/high-risk cases are not promoted by sales volume. One case has no
current full-data match; fixtures still verify its handling. See
`documentation/step_11_tricky_cases.md` for definitions, counts and commands.

## Spark MLlib demand models

Step 12 compares linear regression, decision tree and random forest for
next-calendar-month item/location accepted sales. The 60,105-row supervised
snapshot and 17,180 held-out predictions are in `parquet_data/step12-full/`;
the selected fitted pipeline is in `models/step12-full/`. The passed report is
`processed_data/step12-full/demand_model_report.json`. Linear regression won
on chronological validation MAE, but held-out large-error behavior still
needs improvement before deployment. See `documentation/step_12_spark_models.md`
for the plan, leakage policy, metrics, caveats and rerun commands.

## Customer analytics

Step 15 assigns behavioral segments from eligible completed baskets. Step 16
adds point-in-time RFM measures, 0–5 scores and independent RFM tiers for all
60,000 registered customers. Verified files are in `parquet_data/step15-full/`
and `parquet_data/step16-full/`; reports are in matching `processed_data/`
folders. See `documentation/step_15_customer_segmentation.md` and
`documentation/step_16_rfm_analysis.md` for methods, exclusions and commands.

## Market-basket analysis

Step 17 derives frequent item pairs and both directions of association rules
from complete accepted baskets. Verified pair/rule Parquet is in
`parquet_data/step17-full/`, with its source and metric audit in
`processed_data/step17-full/market_basket_report.json`. See
`documentation/step_17_market_basket.md` for denominator policy, formulas,
minimum evidence and rerun commands. These rules are not yet recommendations.

## Menu recommendation candidates

Step 18 screens Step 17 rules against local co-purchase evidence, observed
direct contribution, price and catalog availability. The verified full
candidate Parquet and audit are in `parquet_data/step18-full-verified/` and
`processed_data/step18-full-verified/`. All 1,403 results are review-only;
live stock and offer economics are not verified. See
`documentation/step_18_recommendations.md` for guards and commands.

## Peak-period analysis

Step 19 publishes local-hour, weekday, weekend, monthly, seasonal, location
and explicit dine-in/delivery patterns in `parquet_data/step19-full-verified/`.
Its report in `processed_data/step19-full-verified/` includes peak summaries
and a per-grain conservation audit. Website/App remains a separate channel
because fulfillment mode is not known. See
`documentation/step_19_peak_periods.md` for definitions and caveats.

## Configurable demand forecasting

Step 20 produces review-only accepted-sales forecasts for one to three
future calendar months. The verified July–September item/location output and
item, category and location rollups are in `parquet_data/step20-full/`;
the report and fitted models are in matching `processed_data/` and `models/`
folders. See `documentation/step_20_configurable_forecast.md` for period
selection, temporal policy, error metrics and limitations.

## Customer intelligence dashboard

Step 44 adds a customer intelligence dashboard at `/dashboard/customers/`. Its network-wide and location-scoped calculation rules and caveats are in `documentation/step_44_customer_dashboard.md`.

## Wastage dashboard

Step 45 adds historical accepted wastage and review-only July risk scores at `/dashboard/wastage/`. Source reconciliation, scope and model caveats are in `documentation/step_45_wastage_dashboard.md`.

## Forecast dashboard

Step 46 adds historical versus future accepted-demand comparisons and full-network held-out errors at `/dashboard/forecast/`. Scope, denominators and caveats are in `documentation/step_46_forecast_dashboard.md`.

## Dual-pipeline dashboard

Step 47 adds access-scoped Spark/Python paired prediction comparisons at `/dashboard/dual/`. Agreement rules, filters and limitations are in `documentation/step_47_dual_dashboard.md`.

## Analytics search and filtering

Step 48 adds a cross-dimensional accepted-sales explorer at `/dashboard/search/`, covering the SRS filter list. Its population, scope and fixed-snapshot caveats are in `documentation/step_48_search_filtering.md`.

## Downloadable reports

Step 49 adds twelve access-scoped, offline HTML report families at `/reports/`. Source checks and interpretation boundaries are in `documentation/step_49_downloadable_reports.md`.

## Data export

Step 50 adds six access-scoped, Excel-compatible CSV exports linked from their dashboards. Full matching-row behavior, formula safety and permission rules are in `documentation/step_50_data_export.md`.

## Infrastructure commands

```powershell
docker compose ps
docker compose logs -f spark-master spark-worker
docker compose stop
uv run python dine_iq/manage.py check
```

## Docker Hub Spark image

The Spark master and worker use the same image, built from
`config/spark.Dockerfile`. The published Linux/amd64 image is
[`alirazazulfiqar/sfc-databricks:latest`](https://hub.docker.com/r/alirazazulfiqar/sfc-databricks).
The verified registry digest for the 29 September 2026 push is
`sha256:727c3a55ede62a3080672efb79c8e2e7df1e7b1bf13a52e5297ec4bd6741317d`.
The `latest` tag is mutable; pin that digest for a reproducible handoff.

Build and publish the Spark runtime from the project root after signing in to
Docker Hub as an account allowed to push to `alirazazulfiqar`:

```powershell
docker login
docker build -f config/spark.Dockerfile -t alirazazulfiqar/sfc-databricks:latest .
docker push alirazazulfiqar/sfc-databricks:latest
```

To use the published image on another machine, clone this GitHub repository
first so the Spark jobs and SQL files are available as bind mounts. Set the
image override before starting Compose; Django still runs through `uv` using
the first-time setup steps above:

```powershell
$env:DINEIQ_SPARK_IMAGE = 'alirazazulfiqar/sfc-databricks:latest'
docker compose pull spark-master spark-worker
docker compose up -d --no-build postgres redis spark-master spark-worker
```

Without `DINEIQ_SPARK_IMAGE`, Compose keeps the original local
`dineiq-spark-ml:3.5.9` build. The published image does not include the
ignored full dataset, Parquet outputs, or model files. Generate them using
the commands in this README, or obtain the separately reviewed data bundle.

## GitHub submission status

Public repository: [Ali-is-pro-123/sfc-databricks](https://github.com/Ali-is-pro-123/sfc-databricks).
The SRS requires genuine team commits, complete source and generation scripts,
Spark/SQL and independent Python pipelines, sample data, screenshots, test
results, assumptions, limitations, evaluator instructions, and links to the
final report, blog, and demonstration video. The source, technical documents,
small synthetic schema samples, and report drafts are organized here; see the
[submission register](documentation/submission/README.md). Full generated
artifacts are ignored by Git and require a separate accessible handoff with
checksums. A public blog URL, video URL, and final human approval are still
pending and must not be represented as complete. Do not commit real passwords
or private `.env` values; distribute evaluator credentials securely.

## Project documentation

- [Word project report with six diagrams](documentation/submission/DineIQ_Project_Report.docx): reviewable SRS deliverable draft.
- [Submission preparation pack](documentation/submission/README.md): consolidated
  project report, diagrams, SRS traceability, evaluator guide, comparison report,
  captured test results, video storyboard and pending deliverables
- `documentation/architecture.md`: technical architecture and folder ownership
- `documentation/development_log.md`: work, issues, tests, and decisions by step
- `AI_USAGE.md`: required declaration of AI-assisted development
