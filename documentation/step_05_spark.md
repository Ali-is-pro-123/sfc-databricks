# Step 5: Spark ingestion and data quality

## Plan

Read raw CSVs using an explicit string landing schema so invalid values remain
available for diagnosis. Validate headers, preserve raw JSON and source paths,
cast to the published field types, and record failures as reason arrays.
Demonstrate inferred schema independently; it does not control production casts.
Remove redundant exact copies, quarantine conflicting business keys and broken
references, retain cancelled orders, and permit anonymous customer references
with a warning. Validate campaign dates and line attribution, rating purchase
dates, and quantity bounds. Persist clean and quarantine Parquet with a quality
report and read-back counts. Run targeted checks and the small profile before
processing the full dataset.

## Boundaries

- Only `raw/` input is accepted by the job. Clean reference data and generator
  evaluation labels are not read by cleaning logic.
- Unknown entities are quarantined, never fabricated from a code pattern.
- All redundant exact copies are quarantined with `duplicate_exact`; one copy
  is retained. Different payloads sharing a primary/logical key are all quarantined.
- A rejected parent can cause child rejection, reported as a foreign-key failure.
- Missing customer IDs are valid anonymous orders and receive warnings. They
  cannot be safely recovered without another trusted source.
- Cancelled transactions remain available for audit; completed-sales queries
  must explicitly filter status.
- Model features, domain-wide reconciliation after quarantine, ML training, and
  full multi-table analytical integration belong to later steps.
- Every run uses new output directories and preserves prior results.

## Running on Windows

Keep Django and the generator in the uv environment. Spark jobs use the PySpark
already bundled in the pinned Linux image; no Windows Java or PySpark install
is required. Run from the repository root with Docker services available:

```powershell
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master local[2] /opt/dineiq/spark_jobs/test_quality.py
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/ingest.py --input /opt/dineiq/raw_data/small-seed42/raw --output /opt/dineiq/parquet_data/new-small --reports /opt/dineiq/processed_data/new-small
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/ingest.py --input /opt/dineiq/raw_data/full-seed42/raw --output /opt/dineiq/parquet_data/new-full --reports /opt/dineiq/processed_data/new-full
```

Use different output/report directory names for subsequent runs. These paths
are Docker bind mounts: results immediately appear in the repository folders.
Each transaction table is partitioned by `_month`; order lines inherit their
accepted parent's order month. Timestamps use UTC and monetary values remain
fixed-point decimals. Dimensions are unpartitioned.

## Outputs and interpretation

- `parquet_data/<run>/clean/<table>`: typed accepted records.
- `parquet_data/<run>/quarantine/<table>`: rejected records with original-field
  JSON, source file, malformed CSV payload when present, and reason arrays.
- `processed_data/<run>/quality_report.json`: running/passed/failed status,
  Spark application/version, per-table counts, schema, reasons, and runtime.
- `processed_data/<run>/inferred_orders_schema.json`: inferred schema from the
  first orders CSV, for comparison only; it does not override explicit types.

The job checks that joins do not multiply input rows and reads both Parquet
outputs back to verify `input = accepted + quarantined`. A row may have multiple
reasons, so summed reason counts are not the number of rejected rows. Rejected
parents can also quarantine otherwise valid children. Missing customers remain
anonymous: the cleaner cannot identify which were deliberately corrupted.

Reports are local generated artifacts, excluded from Git. A partial output is
not a successful dataset: consumers must require report status `passed`. A failed
run is preserved for diagnosis, not silently overwritten or used downstream.
Do not modify input CSVs during a run. The job does not ingest clean-reference
files or evaluation labels. Its raw-folder guard is a workflow safeguard, not
a security boundary against someone deliberately replacing the input contents.

## Regression coverage

Tests exercise exact duplicates, conflicting codes and line keys, decimal and
integer precision loss, negative values, invalid prices/dates/units, missing
keys, unknown references, campaign attribution and eligibility, rating bounds
and cancelled/prior purchase checks, impossible wastage, anonymous/cancelled
order retention, malformed-record flags, missing tables, bad headers, and
overwrite refusal. The end-to-end small/full jobs exercise actual CSV parsing,
reference cascades, partitioned writes, and Parquet read-back conservation.

Spark 3.5.9's test collection may print PySpark socket `ResourceWarning` messages
on Python 3.10. Check the final unittest result and exit code; warnings alone are
not a failed test. The ingestion reports do not claim peak-memory measurements,
production hardening, or distributed performance benchmarks.

## Small-run verification

The small run passed on Spark 3.5.9, application
`app-20260925122719-0000`, in 378.991 seconds. Accepted rows include 3,482 orders,
10,374 order lines, 1,182 ratings, 76,560 inventory rows, and 745 wastage rows.
It quarantined 27 orders, 141 lines, 18 ratings, and 5 wastage records. All eight
dimension tables passed without rejected rows. The full-run version additionally
checks pre-join input counts and preserves malformed CSV payloads separately.

All 8 Spark regression tests passed in 49.871 seconds. Existing generator tests
(11) and PostgreSQL-backed account/domain tests (33) also passed after adding
the ingestion modules. Django system checks found no issues.

## Full-run verification

The full run passed on Spark 3.5.9, standalone application
`app-20260925123607-0001`, in approximately 489.43 seconds. Outputs are in
`parquet_data/step05-full` and reports in `processed_data/step05-full`.

| Table | Raw rows | Accepted | Quarantined |
| --- | ---: | ---: | ---: |
| Restaurants | 24 | 24 | 0 |
| Menu categories | 12 | 12 | 0 |
| Menu items | 180 | 180 | 0 |
| Customers | 60,000 | 60,000 | 0 |
| Ordering channels | 4 | 4 | 0 |
| Pricing history | 12,912 | 12,912 | 0 |
| Promotions | 40 | 40 | 0 |
| Promotion-item mappings | 160 | 160 | 0 |
| Orders | 350,871 | 348,295 | 2,576 |
| Order items | 1,051,509 | 1,035,861 | 15,648 |
| Ratings | 120,000 | 117,184 | 2,816 |
| Inventory | 2,346,336 | 2,346,336 | 0 |
| Wastage | 75,000 | 74,244 | 756 |
| **Total** | **4,017,048** | **3,995,252** | **21,796** |

All five transaction tables have 18 month partitions, and all 13 clean table
directories have successful write markers. Both accepted and quarantine counts
were verified by reading Parquet. Order warnings include 930 anonymous customers
and 8,622 retained cancelled orders. There are still over one million accepted
order lines; this does not imply every line represents a completed sale.

The raw dataset's 16,065 injected issues do not equal 21,796 quarantined rows:
anonymous customers are retained, duplicates are removed, and invalid parents
cause dependent rows to be quarantined. Reason counts can overlap. No corrupted
values were secretly restored from the generator's clean reference or ledger.

No Django data import, joined analytical dataset, features, predictions, or
business recommendations were produced in this step. Quarantined sales and
wastage mean source inventory totals need not reconcile with accepted-only
sales; the next integration stage must expose that coverage difference.
