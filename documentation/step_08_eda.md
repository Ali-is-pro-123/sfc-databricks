# Step 8: Exploratory data analysis

## Plan

SRS page 10 lists top and lowest selling dishes, revenue, profit and margin,
wastage, ratings, menu categories, peak periods, location and channel patterns,
and promotion-linked sales. This step computes those descriptive results from
the verified Step 6 integration. It does not assign performance classes or
make causal promotion claims; those belong to later analysis.

1. Require a passed Step 6 report, the exact input row counts, and unused output
   directories. Keep the source read-only and record report, SQL, and job hashes.
2. Use a configurable exclusive restaurant-local cutoff (default example:
   2026-07-01). Include accepted completed transactions before that date.
   Retain the source's partial-basket coverage flags in the report; subtotals
   describe accepted data only. Rating events must be observed before cutoff.
3. Aggregate sales at item grain before joining independent rating and waste
   aggregates. Include zero-sale catalog items known before cutoff. Preserve
   their introduction date and exposure days so low volume is interpretable.
4. Persist item, category, location, channel, promotion, hourly, weekday,
   monthly, location-hour, and daily-location analysis tables in Parquet.
   Define each table's grain and use distinct orders for order counts.
5. Generate bounded, deterministic rankings. Rank margin only where revenue is
   positive; rank ratings only when the configurable minimum observation count
   is met. Show count and value for each ranked item. Zero sales and unrated
   dishes remain visible, not falsely given zero ratings or margin.
6. Reconcile every financial roll-up to the filtered completed line facts.
   Verify sold quantity, waste count/quantity and observed rating count. Check
   unique output keys, per-order totals where applicable, month/hour/weekday
   coverage, Parquet read-back counts and small/full job success.

## Metrics and grains

| Output | Grain | Main measures |
| --- | --- | --- |
| `items` | item | Quantity, accepted revenue/cost/contribution, margin %, average rating/count, waste quantity/cost, promotion quantities, item age |
| `categories` | category | Quantity, accepted revenue/cost/contribution, distinct orders, item count |
| `locations` | location | Header and sales-bearing order counts, quantity, accepted revenue/cost/contribution, partial/empty baskets, waste |
| `channels` | channel | Header and sales-bearing order counts, accepted revenue/cost/contribution, quantity |
| `promotions` | attributed line campaign or unpromoted | Accepted revenue/cost/contribution, quantity, discount, distinct orders |
| `hours`, `weekdays`, `months` | local hour, local weekday, local month | Distinct orders, quantity, accepted revenue and contribution |
| `location_hours` | location and local hour | Distinct orders, accepted revenue and quantity |
| `location_days` | location and local date | Completed sales, waste, inventory gap and coverage |

Revenue is quantity times line price minus line discount. Cost is quantity
times line cost. Contribution is revenue minus that cost; it is not net profit
after rent, labor, tax or other overhead. `margin_percentage` is
`100 * contribution / revenue` and is null when revenue is zero. High wastage
is ranked by recorded waste quantity; `waste_share_of_accounted_portions` is
shown as a coverage-limited proxy, not the percentage of all prepared food.
Orders with a campaign attached but an unpromoted line contribute that line
only to the unpromoted bucket. Promotion-linked sales are attribution, not a
causal estimate of uplift or effectiveness. A location/item with no inventory
record has unknown stock, not zero stock.

Local weekdays use ISO 1=Monday through 7=Sunday. Hours run 0-23. Month
labels are local `yyyy-MM`. Order frequency in item/category/channel/promotion
tables is distinct within that group and must not be summed across groups to
obtain global distinct orders. Item revenue and cost are source transaction
snapshots. Rating date is submission date, so later observations are excluded.

## Acceptance tests

Use an adversarial small fixture with multiple lines in one basket, mixed
promotion attribution, a cancelled order, an item introduced late, a zero-sale
item, repeated waste events and ratings on different dates. Prove totals do
not multiply through joins, ties rank deterministically, rating count threshold
works, cutoff excludes future records, and reports reject failed upstream
status or reused output directories. Then run the real small and full datasets.

## Run commands

Use PowerShell from the repository root. Spark and PySpark run in the existing
Linux containers; Windows project dependencies remain managed by uv.

```powershell
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master local[2] /opt/dineiq/spark_jobs/test_eda.py
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/eda.py --input /opt/dineiq/parquet_data/step06-small --integration-report /opt/dineiq/processed_data/step06-small/integration_report.json --output /opt/dineiq/parquet_data/new-eda-small --reports /opt/dineiq/processed_data/new-eda-small --as-of 2026-07-01 --min-ratings 10 --top-n 10
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/eda.py --input /opt/dineiq/parquet_data/step06-full --integration-report /opt/dineiq/processed_data/step06-full/integration_report.json --output /opt/dineiq/parquet_data/new-eda-full --reports /opt/dineiq/processed_data/new-eda-full --as-of 2026-07-01 --min-ratings 30 --top-n 10
```

The sample cutoff includes observations through 2026-06-30 in each restaurant's
local time. Paths must be new for each run. `--top-n` is bounded to 1-100 and
`--min-ratings` is a positive count. If no item meets the rating threshold, both
rating rankings are empty; no item is assigned an invented rating. Ranking ties
use item code so the result is reproducible. Every output has `analysis_as_of`.
The `_month` partition is the observation month for monthly and daily location
tables; it is the run's snapshot month for summary tables.

## Interpretation boundaries

- Sales order counts in time bins refer to baskets with accepted sale lines.
  Header counts are also available by location, channel and day, including
  accepted completed orders whose lines were all quarantined.
- Rating counts are observation counts, not a score for unrated items. Their
  submission date can follow purchase date. The configurable minimum count
  prevents a single review from topping the best-rated ranking.
- Lowest selling includes zero-sale known items, and `exposure_days` identifies
  items introduced late. This ranking alone is not a Low Performer class.
- The highest contribution ranking is the available analogue of "highest
  profit" in the SRS. No overhead ledger exists, so net profit is unknown.
- The unpromoted bucket includes lines in mixed baskets whose order had a
  campaign but whose item had no campaign attribution. Order counts across
  campaign buckets can overlap; revenue cannot.
- Every metric is computed from accepted records. Quarantined parents and lines
  can leave coverage gaps. The report and location tables retain known partial
  or empty baskets. A rise in promotion-linked sales is not evidence that the
  promotion increased profit or demand causally.

## Small-run evidence

The small run passed in 146.555 seconds using Spark 3.5.9, application
`app-20260925182728-0002`. It generated 36 item rows, 12 categories,
4 locations, 4 channels, 9 line-promotion buckets, 24 hours, 7 weekdays,
18 months, 96 location-hour rows and 2,184 location-day rows.

All ten quantity/revenue/cost/contribution roll-ups matched the completed
transaction lines: 11,798 sold portions, PKR 4,590,042.50 revenue and
PKR 1,839,637.15 contribution. The job also matched 3,391 completed headers,
1,182 observed ratings, 745 waste records and 1,864 recorded wasted portions.
The entire observed order date span was within the selected cutoff, so completed
totals also matched the Step 6 integration report. Rating rankings used at
least 10 observed scores per dish for this small dataset. All eight targeted
Spark fixture tests passed after correcting a Spark Column predicate check.

## Full-run evidence

The full standalone-cluster run passed in 207.042 seconds with Spark application
`app-20260925183017-0003`. Its report is
`processed_data/step08-full/eda_report.json`; Parquet outputs are in
`parquet_data/step08-full/`. All ten output tables passed read-back, uniqueness,
and monetary/quantity reconciliation checks. Row counts are 180 items,
12 categories, 24 locations, 4 channels, 41 promotion buckets, 24 hours,
7 weekdays, 18 months, 576 location-hour rows and 13,104 location-day rows.

The cutoff includes 339,673 completed headers, of which 339,667 have accepted
sale lines. The reconciled line totals are 1,182,659 portions, PKR
529,382,947.61 revenue, PKR 305,410,197.53 recorded cost and PKR
223,972,750.08 contribution. There are 117,181 observed ratings, 74,244
waste records and 200,208.000 recorded wasted portions. Three accepted ratings
were submitted after the cutoff and are intentionally absent from this snapshot.

Illustrative descriptive findings: Chicken Biryani 2 leads sold quantity at
91,393 portions, while Beef Kebab 2 leads line revenue at PKR 43,174,838.89.
Chicken Biryani 1 ranks third by quantity (38,437) yet has negative contribution
of PKR 962,388.19; popularity alone is not profitability. The busiest local
hour is 20:00 with 71,052 completed orders. The promotion ranking reflects
attributed sales only, not incremental or causal lift. These examples are
observations for investigation, not ML classifications or recommendations.
