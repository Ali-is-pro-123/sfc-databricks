# Step 25: Price intelligence

## Plan and implementation

The SRS asks for relationships between price, demand, revenue, contribution
margin, discount, rating and repeat purchase, and for items whose demand
changes materially after price changes. Step 25 uses accepted Step 5 clean
records, not raw or quarantined rows. Each price-history record becomes an
item/location period in restaurant-local dates, bounded by the next price
change or the exclusive analysis cutoff. The introduced date trims exposure.
Completed order lines are matched to exactly one price period. A failed
price/cost match or multiplied sale line stops the run.

Per-period outputs include sold portions and sold portions per exposure day,
net revenue, direct cost/contribution, discount and promoted quantity,
observed rating, and the share of identified purchase lines from customers
who previously bought that item at that location. Missing ratings/repeat
denominators remain null. The transition output compares consecutive
periods and flags a notable change only when price changed, each period
has at least 30 exposure days and 20 sold portions, and the absolute
exposure-adjusted demand-rate change is at least 20%.

These are associations, not price elasticity or causal effects. Season,
promotions, item age and synthetic scenario changes can confound the
before/after comparison. Step 26 owns formal sensitivity classes.

## Run

```powershell
uv run python -m unittest python_pipeline.test_price_intelligence -v
uv run python -m python_pipeline.price_intelligence `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --as-of 2026-07-01 `
  --output parquet_data/step25-full `
  --reports processed_data/step25-full
```

The full run passed with 12,912 price periods and 8,592 transitions. Of
those transitions, 2,786 meet the descriptive notable-change threshold.
Accepted completed lines (1,010,907), sold portions (1,182,659), net
revenue, cost and discount reconcile exactly to the period outputs. The
report is `processed_data/step25-full/price_intelligence_report.json`;
period and transition Parquet files are in `parquet_data/step25-full/`.
