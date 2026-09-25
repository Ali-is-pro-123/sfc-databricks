# Step 6: Analytical data integration

## Plan and acceptance criteria

SRS page 9 requires Spark joins across orders, customers, lines, items,
categories, locations, promotions, historical prices, ratings, inventory, and
wastage. Page 29 also requires Spark SQL and partitioned Parquet. This step
implements those relationships without training models or importing Django data.

1. Require a passed ingestion report, matching table counts/types, successful
   source writes, unique identifiers and unique join keys. Reject reused output
   directories and preserve the input. Do not read generator labels/reference.
2. Produce one fact row per accepted order line, including cancelled lines.
   Join prices using half-open effective intervals, never a future/current price.
   Keep original transaction prices/costs authoritative and flag discrepancies.
   Retain order campaign and line campaign separately. Customers are nullable;
   synthetic cohort labels are deliberately excluded from the fact dataset.
3. Keep ratings with their observation timestamps. Daily rating aggregation uses
   rating submission date, not purchase date. Ratings are descriptive, not safe
   training features without a later point-in-time cutoff.
4. Produce one order-coverage row per accepted order, including empty baskets.
   Count known non-duplicate quarantined line identities separately. Never call
   a basket complete merely because there are no known rejected rows.
5. Aggregate completed sales, waste and ratings separately before joining daily
   item/location inventory. Union observed keys to retain waste-only and
   inventory-only days; do not create a huge speculative Cartesian calendar.
   Use each restaurant's local date; inventory dates already represent local days.
6. Report consumed minus accepted sales minus accepted waste. A difference is
   evidence of incomplete coverage or inconsistent source totals, not an automatic
   stock correction. Missing inventory stays null, not a fabricated zero.
7. Verify unique grains, source-to-fact counts and monetary sums, fact-to-daily
   sums, order coverage totals, read-back counts, and small/full execution.

## Output grains

| Dataset | Unique grain | Meaning |
| --- | --- | --- |
| order_lines | line_code | Accepted transaction line plus dimensions/as-of price/rating |
| order_coverage | order_code | Accepted header plus accepted/rejected line coverage |
| item_location_daily | restaurant_code, item_code, date | Independently aggregated sales, ratings, waste and inventory |

Revenue = quantity * historical line price - discount; cost = quantity * line
cost; contribution = revenue - cost. These are PKR contribution amounts, not
net profit. Daily sales exclude cancelled orders. Waste cost is separate and
not silently deducted twice. Daily quantity zeros mean no accepted completed
sales, not proof of zero real demand. Report values use decimal strings.

## Boundaries

Outputs are descriptive integration datasets, not leakage-safe ML features.
Future feature engineering must select information known at prediction time,
handle incomplete baskets and reconcile coverage before claiming full totals.
Inventory opening/closing values must not be summed over dates as stock levels.
Mutable descriptive dimension names are current labels, not SCD history.
Input snapshots must not change while a job runs. Failed outputs remain on disk
for diagnosis; consumers must require an integration report with status passed.

## Running with Docker from PowerShell

```powershell
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master local[2] /opt/dineiq/spark_jobs/test_integration.py
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/integrate.py --input /opt/dineiq/parquet_data/step05-small --quality-report /opt/dineiq/processed_data/step05-small/quality_report.json --output /opt/dineiq/parquet_data/new-integration-small --reports /opt/dineiq/processed_data/new-integration-small
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/integrate.py --input /opt/dineiq/parquet_data/step05-full --quality-report /opt/dineiq/processed_data/step05-full/quality_report.json --output /opt/dineiq/parquet_data/new-integration-full --reports /opt/dineiq/processed_data/new-integration-full
```

Use unused output names for each run. Each output is partitioned by local
`_month`; input Step 5 partitions are UTC for timestamp tables. Jobs run in the
existing Spark container; the Windows uv environment needs no extra packages.
The report includes application IDs, runtimes, SQL/source-report hashes, output
schemas, row counts, monetary totals, price checks, and coverage findings. The
final job also records its Python source hash. Counts/types are checked against
the upstream report; these are not cryptographic checksums of every Parquet byte.

## Coverage semantics

- `no_accepted_lines`: accepted order header, no accepted lines. Retain for audit.
- `partial`: at least one accepted line and one known rejected line identity.
- `no_known_rejections`: no known non-duplicate line rejections, not a guarantee
  that the source captured the complete basket.
- `known_rejected_lines`: distinct original line codes (or payload hash when
  absent) linked to an accepted order. Exact duplicate-only rejections do not
  reduce basket coverage. Unlinkable rejected records remain in Step 5 quarantine.
- `accepted_basket_revenue`: accepted-line subtotal, including cancelled headers
  for audit. Filter completed status for sales, and consider coverage before
  computing basket size, average order value or customer spend.
- `consumption_gap`: recorded inventory consumption minus accepted completed
  portions sold minus accepted waste. Null when inventory is missing. Positive
  gaps can be explained by rejected sales/waste, but causation is not assumed.
- `price_snapshot_mismatch`: historical line price/cost differs from the price
  interval covering purchase time. Null when no applicable price exists. Neither
  flag rewrites transaction money or silently rejects a valid line.
- `order_count`: distinct completed baskets containing that item on that day.
  It must not be summed across items to calculate restaurant order counts.
- `prepared_quantity`: sum of recorded waste-event preparation amounts only;
  it is not a complete restaurant production ledger or a global waste denominator.

## Test design

Adversarial fixtures include two sales lines and two wastage records for the same
item/day, a large cancelled line, a mixed promotion basket, a null customer,
an order with no accepted lines, a duplicate-only rejection, missing/future price
history, an exact price-change boundary, local midnight, delayed rating submission,
inventory-only and waste-only days, duplicate join keys, failed upstream reports,
output overwrite refusal and output/source isolation. Expected decimal totals are
hand-calculated, independent of the generator and the SQL aggregation.

## Small-run and regression evidence

The small standalone run passed in 273.553 seconds, application
`app-20260925131252-0002`. Outputs contain 10,374 lines, 3,482 orders, and 76,560
daily item/location records. There were 76 partial orders, no missing/mismatched
price snapshots, and 125 inventory days with a nonzero consumption gap totaling
158 portions. No negative gaps or missing inventory days were found.

The final integration suite passed all 10 tests in 24.836 seconds. Existing
quality checks (8 tests), generator checks (11 tests), and Django account/domain
checks (33 tests) also passed. Django system checks and uv lock checks passed.
The small run predates the additional output-path isolation guard and Python
source hash field; the full run uses both. Integration SQL is the same in both.

Execution logs are saved locally in `processed_data/step06-small-execution.log`
and `processed_data/step06-full-execution.log`; final Spark test logs are
`processed_data/step06-integration-tests-final.log` and
`processed_data/step06-quality-regression.log`. Like Parquet and reports, logs
are ignored by Git. Spark may log truncated plan-display and Python socket
warnings; check final exit codes and report status, not warnings alone.

## Full-run evidence

The full run passed in 373.466 seconds, application
`app-20260925131750-0003`: 1,035,861 line facts, 348,295 order-coverage rows and
2,346,339 daily rows. No applicable price history was missing or mismatched.
There were 8,939 partial orders, 6 headers without accepted lines and 339,350
orders with no known non-duplicate rejections.

Completed accepted sales total PKR 529,382,947.61 revenue, PKR 305,410,197.53
cost and PKR 223,972,750.08 contribution on 1,182,659 portions. These are
accepted-only subtotals, not reconstructed original sales. Daily totals match.
Inventory reconciliation flags 14,313 nonzero-gap days totaling 18,243 portions,
zero negative-gap days, and 3 observed daily keys without an inventory record.
Missing inventory is retained as null rather than fabricated. The daily key
union includes rating observation dates as well as sales/waste/inventory days.
