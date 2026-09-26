# Step 15: Customer segmentation

## Plan before implementation

SRS page 14 asks for behavioral customer groups considering recency,
frequency, monetary value, average order value, visit frequency, favorite
category, promotion sensitivity, ordering channel, time-of-day preference and
repeat behavior. This step builds a point-in-time descriptive snapshot at
`2026-07-01` from Step 6 accepted order coverage/lines plus the Step 5 clean
customer dimension. Step 16 will separately formalize RFM scoring; Step 15
includes the underlying R/F/M measures because they are required here.

1. Require passed Step 5 quality and Step 6 integration reports, successful
   source Parquet markers and matching row counts. Include all accepted
   registered customers, including those with no eligible purchases. Exclude
   anonymous identities from customer-level segmentation.
2. Eligible visits are completed orders before the cutoff with accepted lines
   and no known rejected line identities. Cancelled, empty and known-partial
   baskets remain visible in the exclusion audit, not silently counted as
   zero-spend visits. Build one order-level fact from eligible lines to avoid
   line-count inflation and reconcile its order count/revenue to sources.
3. Compute lifetime and last-180-day order counts/spend, last-90-day activity,
   recency, average order value, normalized visit frequency, first/last visit,
   repeat indicator and promotion-order share. Determine favorite category
   by purchased quantity; dominant channel and local time-of-day by order
   frequency. Break ties deterministically by code/name.
4. Assign exactly one transparent segment with documented precedence: New
   (first visit or enrollment in last 60 days), At-Risk (at least two past
   visits and none in 90 days), Promotion-Driven (three recent visits and at
   least half promoted), High-Value Loyal (six recent visits and recent spend
   at/above the active-customer 75th percentile), Frequent (six recent
   visits), Occasional (remaining purchasers), and No Purchase Yet (remaining
   registered non-purchasers). At-Risk precedes promotion/loyalty and New
   precedes all existing-customer labels.
5. Persist one row per customer with numeric features, preferences, segment,
   reason and quality flags, plus a JSON report with source lineage, segment
   counts, excluded-order counts and reconciliation. Test boundaries, tie
   handling, no future leakage and small/full runs.

## Interpretation limits

Thresholds are explicit operational heuristics, not ML-discovered natural
clusters or causal measures. Promotion sensitivity is observed promotion-use
share, not proof that a promotion caused purchases. Channel/time/category
preferences reflect eligible accepted orders only. Customers with no
eligible orders are retained but have null recency and preferences. The
synthetic dataset is not evidence of live customer behavior.

## Run and verification

```powershell
uv run python -m unittest python_pipeline.test_customer_segments -v
uv run python -m python_pipeline.customer_segments `
  --integration parquet_data/step06-full `
  --integration-report processed_data/step06-full/integration_report.json `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --as-of 2026-07-01 `
  --output parquet_data/new-step15-full `
  --reports processed_data/new-step15-full
```

Use unused output/report paths. Verified outputs are
`parquet_data/step15-full/customer_segments.parquet` and
`processed_data/step15-full/segmentation_report.json`. The small rehearsal
uses matching `step15-small` paths.

Four focused tests passed, including a future-order counterexample and a
multi-line order counted once. The full run assigned all 60,000 accepted
customers exactly one segment. Its 330,045 eligible visits and PKR
517,880,620.35 revenue reconcile to accepted complete basket coverage.
Excluded coverage headers are reported separately: 8,622 cancelled, 903
anonymous, 8,719 known-partial and 6 empty baskets. The active-customer
last-180-day spend 75th percentile was PKR 6,172.20.

Full segment counts: 19,568 At-Risk, 19,374 Occasional, 10,320 New, 9,692
Promotion-Driven, 806 High-Value Loyal, 239 No Purchase Yet, and 1 Frequent.
The lone Frequent classification follows the explicit precedence: most
high-frequency customers were assigned to Promotion-Driven or High-Value
Loyal first. This illustrates that the labels are rule-based and their
prevalence is sensitive to thresholds; human review is needed. Promotion
share uses the last 180 days when available, otherwise lifetime visits.
