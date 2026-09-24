# Step 4: Synthetic restaurant data generation

## Accepted plan

Generate linked records with reproducible seeds, three profiles, dated prices,
realistic demand variation, controlled anomalies, and independently verifiable
quality defects. Begin with a small dataset, then medium, then the SRS-scale run.
The initial schema adjustment adds nullable `OrderItem.promotion` for attributing
only eligible discounted lines in a mixed basket.

## Execution

Run from the repository root using Python 3.11 and uv; no additional dependencies
or running database are needed for the generator.

```powershell
uv run python -m data_generator --profile small --seed 42 --output raw_data/my-small-run
uv run python -m data_generator --profile medium --seed 42 --output raw_data/my-medium-run
uv run python -m data_generator --profile full --seed 42 --output raw_data/my-full-run
uv run python -m data_generator --validate-only --output raw_data/my-full-run
uv run python -m data_generator.evidence raw_data/my-full-run
uv run python -m unittest tests.test_generator -v
```

Output directories must not exist. A rerun must use a new name; previous data is
never overwritten. The default date range is 2025-01-01 through 2026-06-30, with
an exclusive end argument of 2026-07-01. Use `--start`, `--end`, and
`--corruption-rate` to configure new runs. Short profiles need at least 120 days;
full SRS validation requires at least a year. A fixed seed, config, generator
version and Python runtime reproduce the CSV bytes; timings are not deterministic.

## Layout

| Path within a run | Meaning |
| --- | --- |
| `raw/` | Corrupted source CSVs for future Spark/Python ingestion |
| `clean_reference/` | Generator correctness oracle; NOT an input shortcut for cleaning |
| `evaluation/corruption.jsonl` | Exact source table, record code, file, data-row number, issue and before/after values |
| `evaluation/customer_scenarios.csv` | Latent customer generation groups; never model features |
| `evaluation/item_scenarios.json` | Controlled item/campaign causes; never classification targets or features |
| `evaluation/business_metrics.json` | Generator counters, not predictions |
| `evaluation/scenario_evidence.json` | Independent CSV-derived verification of controlled patterns |
| `manifest.json` | Configuration, version, row counts, issue totals, CSV checksums and sizes |
| `schemas.json` | Explicit columns, data types, foreign-key targets and units |
| `samples.json` | Three example records per table, for JSON ingestion/schema demonstrations |
| `validation.json` | Independent validation status and results |
| `run_status.json` | Generation time and final run status |

Transaction files are partitioned into month-named CSV files. Order lines follow
their order's UTC month; inventory snapshots use the restaurant local date. Small
JSON schema samples are not a complete relational dataset. Generated data and
evaluation artifacts stay under the ignored `raw_data/` directory.

## Schema contract with Django

- `code` is a stable business identifier; raw foreign keys use `*_code`.
  A future loader resolves these to Django database primary keys.
- `promotion_items` is a separate bridge CSV for the `Promotion.items` relation.
- `order_items.promotion_code` maps to the nullable line-level campaign field.
- `menu_items.introduced_on` is generation/analytical metadata, currently absent
  from the Django MenuItem table; a loader must explicitly retain it for analysis.
- `unit` is an explicit raw validation field with clean value `portion`; the
  current Django tables assume portions and do not have a unit column.
- Snapshot fields match the Django domain. Cost and price remain historical.
- Monetary CSVs are decimal strings; generation computes them using integer paisa
  and half-up discount rounding. The validator avoids binary floating-point
  half-cent disagreements by verifying discounts in integer paisa.
- Identifiers and dates are meaningful independent of scenario metadata.

## Behaviour and deliberate limits

Customers have repeat-propensity, promotion, recency and category preferences.
Demand includes local lunch/dinner peaks, weekend and seasonal effects, location
differences, price response, and paired items. The 2/3/4-line basket distribution
averages exactly three lines per order. Quantities vary by customer behaviour;
four-line baskets are more likely to use delivery.

The generator selects rating-bearing line IDs independently and does not cancel
orders containing those lines. This ensures exactly the requested number of
unique, purchase-valid ratings, but means cancellation rates vary slightly with
basket size. Every generated customer has at least one attempted order; cancelled
orders remain in raw data and are excluded from completed-sales calculations.

Inventory is a daily portion snapshot. Preparation uses recent demand with
overproduction noise; same-day replenishment can meet realized sales. Waste is
recorded for selected daily batches; missing batch records imply zero waste in
this synthetic world. Consumption equals completed sales plus waste and stock
rolls forward. The hidden-opportunity item is made to order and has no waste.
This is not an ingredient procurement simulator or an inventory forecasting model.

Scenario strength is intentionally visible for evaluator demonstrations, but the
final ML models still need unseen-data evaluation. Scenario labels must never
be copied into model features, ground truth, classifications or recommendations.
The generator does not train models, make train/test splits, publish data, load
PostgreSQL, or produce Spark-cleaned/Parquet outputs; those remain later steps.

## Independent checks

Validation loads clean-reference CSVs into a disposable SQLite index on disk,
checks types, primary/foreign keys, prices, campaign eligibility, ratings,
inventory continuity, and sales/waste reconciliation, then proves every raw
difference is explained by the ledger. SQLite is only a verification index;
the application's database remains PostgreSQL. Raw rows are never accepted into
the application's clean database simply because this generator check passes.

Tests cover same-seed checksums, different seeds, corruption independence,
overwrite refusal, invalid configuration, business scenarios, tamper detection,
and broken foreign keys even when a manifest is rehashed. Failed validation
replaces any stale success report. Full runs also require all scenario checks.

## Verified full run

`raw_data/full-seed42` was generated and independently validated:

| Table | Clean count |
| --- | ---: |
| Customers | 60,000 |
| Orders | 350,000 |
| Order items | 1,050,000 |
| Menu items | 180 |
| Menu categories | 12 |
| Restaurants | 24 |
| Ratings | 120,000 |
| Wastage | 75,000 |
| Inventory snapshots | 2,346,336 |
| Pricing history | 12,912 |
| Promotions | 40 |
| Promotion-item mappings | 160 |
| Ordering channels | 4 |

The raw copy has 350,871 order rows and 1,051,509 order-line rows because of
injected duplicates. Exactly 16,065 defects are recorded across 13 issue types.
The run contains 197 CSV files totaling 457,357,672 bytes across both layers.
Generation took 333.271 seconds; independent verification took 490.245 seconds
on this machine before the subsequent path-caching optimization. Peak RAM was
not captured for this run. Transaction rows are streamed; compact numeric arrays
hold daily sales and generation metadata, while validation uses a disk index.

All 12 measured scenario checks passed. Examples include 38,919 sold portions
for the loss-making item with PKR -974,454.70 contribution, 682 portions for a
high-margin item with PKR 124,731.00 contribution, 74,975 paired-item baskets,
and negative contribution under the selected deep-discount campaigns.

Final verification: 11 generator tests and 33 Django account/domain tests passed.
Actual order timestamps span 2025-01-01T04:13:00Z to 2026-06-30T17:58:00Z,
covering all 18 transaction months. Django checks, migration consistency, uv lock
consistency, and generated-data Git exclusion were verified.
