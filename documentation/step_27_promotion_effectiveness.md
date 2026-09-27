# Step 27: Promotion effectiveness analysis

## Plan and implementation

The SRS requires promotion evaluation across order volume, revenue,
contribution margin, customer acquisition, repeat purchases, average order
value, wastage and post-promotion behavior. Accepted Step 5 clean completed
orders and lines are first collapsed to one order-level basket, then joined
to their active campaign. Campaign totals retain full accepted-basket net
revenue, direct contribution and discount, while separately reporting the
line quantity/revenue/contribution actually attributed to that campaign.
No campaign is automatically labeled successful based on sales growth.

Customer acquisition means the first *observed accepted completed order*
for an identified customer, not verified true acquisition. Returning
customers have an earlier observed order. Post-promotion behavior counts
campaign customers with another accepted completed order in the 30 days
after campaign end; the report states whether that full window is observed.
Anonymous customers are excluded from customer denominators, but their
orders remain in economic totals.

Wastage is accepted waste for the campaign's eligible items during its
active interval, compared descriptively with the preceding equal-length
interval. It is not waste attributed to the campaign. Overlapping campaigns
can count the same waste record, so campaign waste must never be summed
as a global total. Direct contribution excludes overhead and is not net
accounting profit. Quarantined lines can leave accepted baskets incomplete.

## Run

```powershell
uv run python -m unittest python_pipeline.test_promotion_effectiveness -v
uv run python -m python_pipeline.promotion_effectiveness `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --as-of 2026-07-01 `
  --output parquet_data/step27-full `
  --reports processed_data/step27-full
```

## Verified full result

All 40 accepted campaigns are represented, with 189,672 tagged completed
orders and PKR 283,158,378.29 accepted-basket net revenue. Their direct
contribution is PKR 114,728,098.44 and discounts total PKR 18,867,408.19.
All 40 have a complete post-30-day observation window at the cutoff. None
has negative aggregate direct contribution, but that alone is not an
effectiveness verdict. The source/order/money and saved Parquet counts pass
reconciliation. The report is
`processed_data/step27-full/promotion_effectiveness_report.json`.
