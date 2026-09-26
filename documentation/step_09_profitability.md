# Step 9: Menu profitability analysis

## Plan

SRS page 11 requires menu performance to consider quantity, revenue,
ingredient/preparation cost, contribution, profit percentage, rating, repeat
purchase, wastage, promotion dependency, and sales trend together. High sales
volume alone cannot imply success. Step 10 owns final performance classes.

1. Require passed, matching Step 6 integration and Step 7 feature reports, a
   90-day item/location snapshot, unchanged report hashes, and unused output
   directories. Keep generated source datasets read-only.
2. Keep the Step 7 item/location grain and all ten required measures. Its
   accepted transaction revenue/cost are historical line snapshots, and
   contribution is revenue minus direct item cost, not net profit.
3. Independently aggregate the completed Step 6 line facts for the last 30
   local days and the preceding 30 days before the exclusive cutoff. Report
   period quantities and revenue, percentage changes only with nonzero prior
   values, and days of item exposure in each period. Newly introduced items
   must not be treated as declining when prior history is unavailable.
4. Add interpretable signals for negative contribution and missing evidence.
   Keep null rating/repeat/waste ratios and new-item trend explicitly unknown;
   do not impute these as good or bad or assign Step 10 classes.
5. Persist a queryable Parquet item/location performance table. Verify unique
   grain, exact feature money/quantity reconciliation, period-to-source
   reconciliation, trend arithmetic, read-back counts, and a small adversarial
   test fixture before full-data execution.

## Definitions and boundaries

- Window: `[as_of - 90 days, as_of)` in each restaurant's local date. Trend
  periods are `[as_of - 60, as_of - 30)` and `[as_of - 30, as_of)`.
- `profit_percentage` is the direct contribution margin percentage retained
  from Step 7; it is not accounting net profit after overhead.
- `accounted_wastage_percentage` is waste divided by accepted sold plus
  recorded wasted portions. Missing inventory can limit this proxy.
- `repeat_purchase_rate` uses only known-complete, identified customer
  baskets. It is null when no eligible customers bought the item.
- `promotion_dependency` is the fraction of sold portions linked to a line
  campaign, not a causal estimate of promotion benefit.
- Period revenue/quantity and trend use accepted completed lines. Prior-period
  zero revenue or insufficient exposure yields a null growth percentage.
  Both period counts remain visible for interpretation.
- Descriptive diagnostic flags must never be read as final menu classification
  or a recommendation. Step 10 will define and validate data-driven classes.

## Acceptance

Tests cover a high-volume loss maker, a profitable low-volume dish, zero-sales
and newly introduced dishes, trend denominator/age boundaries, conservation,
and rejection of failed upstream reports or reused output paths. The full run
must retain all 4,320 item/location keys from Step 7 and reconcile its
90-day money/quantity totals, while recording exact source/report hashes.

## Run commands

Run from the repository root. Spark stays in Docker; Windows Python stays
managed with uv. Choose new output/report directories for reruns.

```powershell
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master local[2] /opt/dineiq/spark_jobs/test_profitability.py
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/profitability.py --integration /opt/dineiq/parquet_data/step06-full --integration-report /opt/dineiq/processed_data/step06-full/integration_report.json --features /opt/dineiq/parquet_data/step07-full --feature-report /opt/dineiq/processed_data/step07-full/feature_report.json --output /opt/dineiq/parquet_data/new-profitability-full --reports /opt/dineiq/processed_data/new-profitability-full
```

## Verification evidence

Four targeted Spark tests passed, including cancelled/future sale exclusion,
the exact 30-day period boundary, a high-volume loss maker, a zero-sales item,
insufficient history for a newly introduced item, failed report rejection and
reused-output rejection. Standalone-cluster small
and full runs passed in 22.200 and 20.055 seconds respectively. The small
output has 144 item/location rows; the full output has 4,320, matching Step 7.
The verified full files are in `parquet_data/step09-full/` and the report in
`processed_data/step09-full/profitability_report.json`.

Full 90-day totals reconcile to 265,989 sold portions, PKR 125,910,828.14
revenue, PKR 70,612,065.23 direct cost and PKR 55,298,762.91 contribution.
The final 60 days contain 203,372 accepted portions and PKR 97,303,115.46
revenue. Twenty-four item/location rows have negative contribution; 339 have
no defensible quantity trend percentage. These counts are descriptive evidence,
not menu classes. All Parquet rows passed unique-grain and read-back checks.
