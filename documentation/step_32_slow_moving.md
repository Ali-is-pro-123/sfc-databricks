# Step 32: Slow-moving dish detection

## Plan and implementation

The SRS requires seven combined signals: low sales volume, low purchase
frequency, long gaps between purchases, low repeat purchase, high wastage,
weak profitability and poor trend. This step reads the verified Step 9
90-day item/location performance snapshot and independently rebuilds
accepted completed sales from Step 5 clean orders/lines. Every pair's
90-day quantity, distinct order count, revenue and direct cost must match
the Step 9 record before classification.

Accepted purchase dates provide days since last sale and the longest
no-sale gap, including the opening/closing window boundaries. No-sale
items receive a 90-day gap; they are not lost in an inner join. Low volume
and low order frequency use the bottom quartile among the same category
and location (at least eight peers). A long gap is >=21 days. Low repeat
is <=5% with at least 20 eligible customers; high accounted wastage is
>=25% with at least five recorded wasted portions; weak direct margin is
<=20%; poor quantity trend is <=-25% with adequate prior/recent exposure.
Percentages here are on the Step 9 0–100 scale.

An item/location is `slow_moving` when at least two of the three activity
signals and a nonrepeat health signal are present, or all three activity
signals are present. An established item with zero sales for at least 60
days also qualifies. A lower-evidence combination is `watchlist`.
Items under 60 days old, with fewer than eight peers, or too little health
evidence abstain unless the established zero-sale rule applies. A dish-wide
summary distinguishes widespread from location-specific cases; it needs
at least 12 non-insufficient location results.

These thresholds are explicit analytic choices, not SRS-mandated cutoffs.
Missing repeat/trend/waste evidence stays unknown rather than becoming a
bad score. Step 23's accepted inventory gap and the synthetic June demand
shift limit operational interpretation. Direct contribution excludes overhead.

## Run

```powershell
uv run python -m unittest python_pipeline.test_slow_moving -v
uv run python -m python_pipeline.slow_moving `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --performance parquet_data/step09-full/item_location_performance `
  --performance-report processed_data/step09-full/profitability_report.json `
  --as-of 2026-07-01 `
  --output parquet_data/step32-full `
  --reports processed_data/step32-full
```

## Verified full result

The 4,320 item/location pairs reconcile to 265,989 sold portions,
PKR 125,910,828.14 revenue and PKR 70,612,065.23 direct cost over the
last 90 days. The combined rules classify 853 pairs as slow-moving, 503
as watchlist, 2,940 as not slow-moving and 24 as insufficient evidence.
At dish level, two are widespread slow-moving, 165 are location-specific,
two watchlist, ten not slow-moving and one insufficient. A location-specific
label can reflect as little as one slow location and must not be generalized
to all branches. The report is
`processed_data/step32-full/slow_moving_report.json`.
