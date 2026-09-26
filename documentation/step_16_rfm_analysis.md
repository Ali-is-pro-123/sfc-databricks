# Step 16: RFM analysis

## Plan before implementation

SRS page 15 requires recency, frequency and monetary value for every customer,
with RFM used independently or as a segmentation input. This step uses the
verified Step 15 customer snapshot as its source and publishes independent RFM
scores/tiers. It does not rewrite Step 15's behavior-based segments or reuse
synthetic cohort labels.

1. Require a passed Step 15 report, its exact customer snapshot, matching
   count/cutoff and reconciliation of visits/spend. Refuse existing output
   paths. Retain all accepted customers, including those without purchases.
2. At exclusive `2026-07-01`, define R as days since last eligible completed
   visit; F as eligible visit count in the preceding 180 days; M as accepted
   spend in that same 180-day window. Keep lifetime visits/spend for context.
   No-purchase R is null, not fabricated as zero days; its scores are 0.
3. Assign transparent 0–5 scores. R: 5 for <=30 days, 4 for <=60, 3 for
   <=90, 2 for <=180, otherwise 1. F: 5 for >=6 recent visits, 4 for >=4,
   3 for >=2, 2 for >=1, otherwise 1 for past purchasers. M: among active
   customers with positive recent spend, use p25/p50/p75/p90 cutoffs;
   scores 1/2/3/4/5 respectively. Past purchasers with zero recent spend
   receive M=1. Ties receive the same score; no forced equal-size bins.
4. Publish `RFM` code, summed 0–15 score and descriptive tier: No Purchase
   History, Top RFM (all three scores >=4), High (sum >=12), Medium (>=8),
   Low otherwise. Include the Step 15 behavior segment for cross-analysis,
   not as a scoring input. Summarize score/tier counts and a cross-tab.
5. Test score boundaries, zero-history handling, monetary ties, source
   conservation, unique customer grain and small/full runs. Re-read saved
   Parquet and report exact source lineage and thresholds.

## Limits

These scores are descriptive ranks at a particular cutoff, not predictions
of churn, lifetime value or causal response. Monetary cutoffs are derived
from this synthetic population and must be reviewed for live use. Excluded
partial/cancelled baskets inherit Step 15's audited eligibility policy.

## Run and verified result

```powershell
uv run python -m unittest python_pipeline.test_rfm -v
uv run python -m python_pipeline.rfm `
  --input parquet_data/step15-full/customer_segments.parquet `
  --source-report processed_data/step15-full/segmentation_report.json `
  --output parquet_data/new-step16-full `
  --reports processed_data/new-step16-full
```

Use unused output/report paths. Verified results are
`parquet_data/step16-full/rfm_scores.parquet` and
`processed_data/step16-full/rfm_report.json`; small rehearsal results use
`step16-small`. One boundary/tie fixture test passed. Small and full runs
passed with exact source population and money/visit reconciliation.

The full population is 60,000 unique customers, including 360 with no
eligible purchase (`000` RFM code). Its lifetime source totals are 330,045
visits and PKR 517,880,620.35. Positive active-customer spend cutoffs are
PKR 2,436.48 (p25), 4,111.56 (p50), 6,172.20 (p75) and 8,334.54 (p90).
Tier counts are 8,173 Top RFM, 2,664 High, 23,837 Medium, 24,966 Low and
360 No Purchase History. The report also includes every RFM code count and
the cross-tab against the existing Step 15 behavior segments.
