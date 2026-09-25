# Step 7: Cutoff-aware analytical feature engineering

## Plan

Implement the feature families on SRS page 10, with four persisted snapshot
grains: item/location, customer, order basket, and location. Require a passed
Step 6 report and matching immutable Step 5/6 source snapshots. Do not train
models, produce classifications, or reuse generator evaluation labels.

- Require `--as-of YYYY-MM-DD` (exclusive local date at each restaurant) and
  `--window-days` (positive, default 90). Use only completed orders before the
  cutoff. Window features use local dates in `[as_of - window_days, as_of)`.
- Revenue, historical cost, contribution, margin percentage, order frequency,
  popularity, repeat purchase, rating/trend, wastage, promotion dependency,
  discount percentage, weekend ratio and peak-hour frequency at item/location.
- Price change uses the last two price events strictly before local cutoff;
  no future price is selected. Retain catalog items with observed inventory or
  valid price history even when window sales are zero.
- Customer recency uses known valid visits from available history; frequency,
  monetary value, average basket, channel/category preference and weekend ratio
  use window orders without known line rejections. Preserve customers with zero
  eligible visits. Missing recency remains null. Anonymous IDs are not fabricated.
- Basket features retain coverage flags; location features disclose partial and
  empty baskets. Item sales remain accepted-only subtotals with coverage evidence.
- Ratings are observed by submission date and never included if submitted at or
  after the cutoff, even when the original purchase is older. Rating trend is
  late-half minus early-half mean, null unless both halves have observations.
- Never replace an undefined ratio with fake certainty: zero denominators yield
  null. Waste ratio = accepted waste / (accepted sold + accepted waste), explicitly
  an accounted-portions proxy rather than total preparation wastage percentage.
- Validate cutoff boundaries, future-rating/price isolation, repeated customers,
  zero sales, anonymous/partial basket policy and financial totals with fixtures;
  then run small and full snapshots before marking the step complete.

## Model boundary

Each output describes a known historical snapshot; it is not a trained model or
a target-labelled training set. Future forecasting must build successive cutoff
snapshots and future-only labels, use chronological train/validation/test splits,
and keep preprocessing fits inside the training split. A current snapshot must
not be joined back onto older training rows. Current descriptive dimension names
are not historical slowly changing dimensions. Cohort/latent labels are excluded.
These are Spark-side features. The later independent Python pipeline must
implement the selected task's preprocessing/features independently over the
same underlying records; copying Spark features or predictions is not evidence
of independent analytical verification.

## Definitions

Percentages use 0-100. Ratios/shares use 0-1. Margin percentage uses revenue as
denominator; revenue zero yields null and negative contribution is preserved.
Order frequency is distinct completed accepted baskets containing the item in
the window; orders/day uses calendar window length, not observed nonzero days.
Repeat rate uses non-anonymous item customers with at least two distinct eligible
orders divided by non-anonymous item customers with eligible purchases. Eligibility
means no known rejected lines and at least one accepted line, not proof of complete
source capture. Peak-hour frequency is the busiest local hour's distinct item
orders divided by all item orders; ties choose the earlier hour.

## Run commands

```powershell
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master local[2] /opt/dineiq/spark_jobs/test_features.py
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/features.py --input /opt/dineiq/parquet_data/step06-small --integration-report /opt/dineiq/processed_data/step06-small/integration_report.json --output /opt/dineiq/parquet_data/new-features-small --reports /opt/dineiq/processed_data/new-features-small --as-of 2026-07-01 --window-days 90
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/features.py --input /opt/dineiq/parquet_data/step06-full --integration-report /opt/dineiq/processed_data/step06-full/integration_report.json --output /opt/dineiq/parquet_data/new-features-full --reports /opt/dineiq/processed_data/new-features-full --as-of 2026-07-01 --window-days 90
```

The 90-day example covers 2026-04-02 through 2026-06-30 inclusive in local dates.
Use new output/report paths for every cutoff run. No Windows PySpark install is
required. The job verifies source statuses/counts, report lineage hashes, unique
output grains, Parquet read-back counts, item/location financial conservation,
and eligible customer spend/frequency conservation. Source snapshots must remain
immutable; report hashes do not checksum every source Parquet byte.

## Feature dictionary

| Output | Features and policy |
| --- | --- |
| item_location_features | Historical money, margin, frequency/day, popularity share, eligible repeat rate, observed rating/trend, accounted waste ratio/cost, inventory coverage, promotion dependency, discount percentage, peak hour/frequency, weekend ratio, age, price change |
| customer_features | Available-history recency and frequency, window frequency/monetary value/average order value/basket quantity, preferred channel/category, weekend ratio, promotion dependency; zero-history customers retained |
| order_features | Accepted line count, quantity, distinct item count, basket revenue, date/channel/customer, coverage status and customer-metric eligibility; cancelled/future orders excluded |
| location_features | Accepted revenue/cost/contribution, margin, quantity, order frequency, average order subtotal, weekend ratio, partial/empty baskets and revenue share |

Every row contains `feature_as_of` and `window_days`. Outputs are partitioned by
snapshot `_month`, not purchase month. Item/location keys come from observations
or effective prices before cutoff; locations with no pre-cutoff observations are
not introduced from future sales. Customers must have joined before the cutoff.
Current names/categories are descriptive labels, not temporal model features.

Undefined recency, rating trend and zero-denominator ratios stay null. Later
preprocessing must impute/encode these using training-only fits. Ratios are not
rounded into invented business categories. Item and location revenue includes
accepted portions of partial baskets; customer money excludes those baskets.
Consequently, customer totals are intentionally not equal to total restaurant
revenue. Location average order value is explicitly an accepted-header subtotal
average and includes empty accepted baskets; it is not a reconstructed complete
sales average.

## Execution notes

Docker Desktop was stopped when feature verification started. Its existing local
installation was started and the project containers recovered; no images, volumes
or source datasets were reset. Static compilation caught an unmatched parenthesis
before any feature job could run; it was corrected. All 9 final feature tests
passed in 83.713 seconds, including the exact cutoff date/price boundary checks.

Spark can warn about the location revenue-share global window. That window runs
after aggregation, on one row per location (4 small / 24 full locations), not on
all order lines. Test collection can also print PySpark socket ResourceWarnings.
Neither warning replaces checking the final report status and process exit code.

## Small snapshot evidence

The small run passed in 206.632 seconds, application
`app-20260925180408-0000`. It produced 144 item/location rows, 600 customer rows,
740 completed order-basket rows and 4 location rows. Of those baskets, 717 were
eligible for customer metrics and 23 were excluded by coverage/identity policy.
There were 241 ratings observed within the window and before cutoff. Accepted
window revenue was PKR 1,124,620.33, cost PKR 652,897.77 and contribution
PKR 471,722.56; item/location feature totals and customer eligibility totals
passed independent conservation checks against their corresponding inputs.

## Full snapshot evidence

The full run passed in 194.104 seconds, application
`app-20260925180753-0001`, with the same 2026-07-01 exclusive local cutoff and
90-day window. Results are in `parquet_data/step07-full`; the report is
`processed_data/step07-full/feature_report.json`.

| Snapshot | Rows |
| --- | ---: |
| Item/location features | 4,320 |
| Customer features | 60,000 |
| Completed order-basket features | 73,982 |
| Location features | 24 |

There were 71,871 customer-metric-eligible orders and 2,111 excluded baskets,
plus 26,705 ratings observed within the feature window before the cutoff.
Accepted completed window revenue was PKR 125,910,828.14, cost
PKR 70,612,065.23 and contribution PKR 55,298,762.91. Source-to-feature money
and eligible customer spend/frequency checks passed. All four output success
markers and Parquet read-back counts were verified; the recorded job hash matches
the source file. The original million-line input remains unchanged: feature
snapshots intentionally aggregate or select records rather than pretending to
contain a million distinct customer/item features.

Logs are stored in `processed_data/step07-small-execution.log`,
`processed_data/step07-full-execution.log`, and
`processed_data/step07-feature-tests-final.log`. No model, classification,
forecast, recommendation, dashboard integration or fitted preprocessing object
was produced. EDA and subsequent modelling remain separate steps.
