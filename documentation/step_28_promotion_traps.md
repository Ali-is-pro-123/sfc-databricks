# Step 28: Promotion trap detection

## Plan and implementation

The SRS lists five misleading-promotion patterns. This step creates five
separate **potential-trap review flags**, not a campaign success/failure
verdict. It first checks Step 27 report/source lineage, rebuilds accepted
campaign order facts, and reconciles the saved campaign totals. For each
campaign, accepted sales of its eligible items in the active window are
compared with the immediately preceding equal-length window.

- `sales_up_contribution_down`: prior eligible sales >=50 portions, active
  quantity >=20% higher, but direct contribution >=10% lower.
- `customers_up_margin_down`: prior identified eligible-item customers >=20,
  active count >=10% higher, but direct contribution margin rate falls by
  at least 10 percentage points.
- `eligible_waste_up`: prior eligible-item waste >=10 portions, active waste
  >=20% and >=10 portions higher. The same waste can appear under overlapping
  campaigns; it is not campaign-attributed waste.
- `low_post_discount_repeat`: complete 30-day follow-up, >=30 identified
  campaign customers, >=20% of campaign-basket portions attributed to
  discounted lines, and <=5% observed post-campaign repeat rate.
- `possible_high_margin_cannibalization`: within the same location/category,
  an eligible item's sales rise >=20%, a noneligible peer's sales fall >=20%,
  each has >=20 prior portions, and the peer's prior contribution per portion
  exceeds the promoted item's active contribution per portion. Candidate
  item pairs are saved separately for human review.

These rule thresholds are explicit analytic choices, not SRS-prescribed
cutoffs. Before/active windows can differ in seasonality, campaigns can
overlap, and co-movement does not prove customer substitution. Direct
contribution excludes overhead. Low 30-day repeat does not prove that a
customer buys *only* with discounts. Flags should not trigger automated
campaign cancellation or repricing.

## Run

```powershell
uv run python -m unittest python_pipeline.test_promotion_traps -v
uv run python -m python_pipeline.promotion_traps `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --effectiveness parquet_data/step27-full/promotion_effectiveness.parquet `
  --effectiveness-report processed_data/step27-full/promotion_effectiveness_report.json `
  --as-of 2026-07-01 `
  --output parquet_data/step28-verified-full `
  --reports processed_data/step28-verified-full
```

## Verified full result

All 40 campaigns reconcile to Step 27. The review flags find one
sales-up/contribution-down campaign, one customers-up/margin-down campaign,
eight eligible-waste-up campaigns, zero low-post-discount-repeat campaigns,
and six campaigns with seven possible high-margin cannibalization item pairs.
One campaign can carry multiple flags. The authoritative report is
`processed_data/step28-verified-full/promotion_traps_report.json`.
The earlier `step28-full` run had a flag-count reporting error and must not
be used downstream; its underlying campaign rows were not the issue.
