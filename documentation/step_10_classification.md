# Step 10: Menu performance classification

## Plan

SRS page 11 requires every menu item to be assigned exactly one of Profit
Driver, Volume Driver, Hidden Opportunity, and Low Performer using multiple
dimensions rather than a single hard-coded field. Page 12 lists difficult
cases that should remain visible as evidence, not be masked by sales volume.

1. Read only the passed Step 9 item/location snapshot. Verify its report hash,
   source job hash, cutoff, schema, row count, and successful Parquet marker.
   Refuse existing output paths and keep upstream data immutable.
2. Preserve each item/location row and independently aggregate an item-wide
   view. Additive money, quantity, ratings and waste are summed. Item-wide
   rating is observation-weighted; repeat rate is weighted by location-level
   eligible customer counts, so it is not an exact cross-location unique-
   customer rate. State that explicitly in output and report.
3. Calculate peer-relative demand and profitability ranks within category
   (and location for local rows). Demand combines exposure-adjusted sales
   velocity and distinct order frequency. Profitability combines contribution
   margin and contribution per sold portion. Ratings, repeat purchase, waste,
   promotion dependency and trend provide quality/risk evidence.
4. Assign one of the four SRS classes through documented multi-signal rules.
   Negative contribution cannot be a Profit Driver regardless of sales.
   High-demand, high-profit dishes need acceptable waste and quality. A lower-
   demand dish can be a Hidden Opportunity only with positive economics and
   supporting margin, rating or repeat evidence. Remaining high-demand,
   positive-economics dishes can be Volume Drivers; otherwise Low Performers.
5. Persist both item-wide and item/location classifications, the measured
   inputs, peer scores, risk flags, provisional evidence flag and an auditable
   reason. Verify unique keys, exactly one valid class per row, all-source
   coverage, financial conservation, negative-contribution guard and
   deterministic fixture cases; then run small and full datasets.

## Decision policy

The category-peer ranks are empirical, 0-1 relative positions. Fixed score
weights combine multiple measured dimensions, while no raw sales or margin
cutoff determines a class alone. An item with fewer than 30 exposure days,
fewer than 5 sold portions, or without observed ratings/repeat customers is
flagged `provisional_evidence`; it still receives one required class, which
must not be presented as high confidence. Peer comparisons use the current
snapshot only, never future events. Missing rating/repeat values are unknown,
not zero. A high recorded waste proxy, poor rating, promotion reliance or
falling trend is retained as a visible risk indicator.

These are transparent descriptive business-rule classes, not Spark MLlib
predictions or ground-truth labels. Step 12 must train and evaluate models
separately; reproducing these same rules as target labels would only measure
rule imitation, not predictive validity. The accepted-data and accounted-
wastage coverage limitations from Steps 7-9 still apply.

## Exact scoring and class precedence

For each category peer group (or restaurant/category for local rows), Spark
`percent_rank` gives a 0-1 relative position for sales velocity, order
frequency, contribution margin percentage and contribution per sold portion.
Missing margin or per-portion contribution sorts below observed values.
`demand_score = 0.65 * velocity_rank + 0.35 * frequency_rank` and
`profitability_score = 0.65 * margin_rank + 0.35 * unit_contribution_rank`.
High demand and high profitability mean scores of at least 0.65. Rating and
repeat observations need at least 10 reviews or eligible customers before
being compared with peer quartiles. High recorded wastage and campaign reliance
mean nonzero values at or above their peer upper quartiles. A sales decline
means a known negative 30-day quantity change.

Rules are evaluated in order: high demand + high profitability + positive
contribution + acceptable waste/rating + no combined promotion-decline risk
becomes Profit Driver. Other high-demand, positive-contribution dishes with
acceptable waste/rating become Volume Driver. Positive-contribution dishes
below high demand with high profitability, strong rating or strong repeat,
acceptable waste/rating and no combined promotion-decline risk become Hidden
Opportunity. All remaining dishes become Low Performer, including every
negative-contribution dish. Every row records the input measures, ranks,
flags, `classification_reason` and `provisional_evidence`.

## Run and verification

Run from the repository root. Spark remains in Docker, and Python on Windows
continues to use uv. Reruns require new output/report directories.

```powershell
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master local[2] /opt/dineiq/spark_jobs/test_classify.py
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/classify.py --input /opt/dineiq/parquet_data/step09-full --source-report /opt/dineiq/processed_data/step09-full/profitability_report.json --output /opt/dineiq/parquet_data/new-classification-full --reports /opt/dineiq/processed_data/new-classification-full
```

Four targeted Spark fixture tests passed. Small and full standalone-cluster
runs passed in 24.730 and 26.693 seconds. The full outputs are in
`parquet_data/step10-full/` and the passed report is
`processed_data/step10-full/classification_report.json`.

| Class | Item-wide (180) | Item/location (4,320) |
| --- | ---: | ---: |
| Profit Driver | 16 | 202 |
| Volume Driver | 27 | 810 |
| Hidden Opportunity | 35 | 1,229 |
| Low Performer | 102 | 2,079 |

All input item/location rows and all 180 distinct items are classified exactly
once. The full money/quantity totals at both grains match Step 9: 265,989
portions, PKR 125,910,828.14 revenue, PKR 70,612,065.23 direct cost and
PKR 55,298,762.91 contribution. No negative-contribution row escaped the Low
Performer guard. Four hundred seventy local rows are provisional; no item-wide
row is provisional under the defined minimums. A non-provisional rule result
is still not an independently validated business outcome.
