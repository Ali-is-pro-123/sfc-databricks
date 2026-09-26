# Step 29: Rating and satisfaction analysis

## Plan and implementation

The SRS requires ratings against menu items, locations, profitability,
sales, repeat purchase, time period and promotion status. This step joins
accepted ratings at most once to accepted completed order lines from Step 5.
Unrated lines remain in sales/revenue/contribution and rating-coverage
denominators. A duplicate rating on a line fails the audit instead of
multiplying sales. Direct contribution is revenue after line discount minus
direct item cost, not net accounting profit.

Rating event rows retain both purchase date/month and actual local rating
date/month. Aggregate monthly cohorts use *purchase month* so a rating just
after month end is compared with the sale it describes. The preserved
rating date supports Step 30's anomaly work. Outputs cover item, location,
item/location, purchase month, promotion status and combined
item/location/month/promotion grains. Each grain conserves accepted sale
quantity, money, rating count and eligible repeat outcomes.

Repeat purchase is narrowly defined as an identified rated buyer ordering
the **same item at the same location** again within 90 days of the rating.
It is only evaluated when the full 90-day window is observed; anonymous and
recent ratings have an unknown outcome, not a failed repeat. Ratings dated
after the analysis cutoff do not remove their sale lines from denominators.

## Run

```powershell
uv run python -m unittest python_pipeline.test_rating_satisfaction -v
uv run python -m python_pipeline.rating_satisfaction `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --as-of 2026-07-01 `
  --output parquet_data/step29-verified-full `
  --reports processed_data/step29-verified-full
```

## Verified full result and limits

The accepted completed cohort has 1,010,907 lines and 117,184 matched
ratings. Of the ratings, 90,217 have complete identified-customer 90-day
follow-up and 4,224 show the defined same-item/location repeat. The six
summary grains reconcile sales, direct contribution, ratings and repeat
counts. The report is
`processed_data/step29-verified-full/rating_satisfaction_report.json`.
The earlier `step29-full` run was diagnostic; only the verified output
contains the tested future-rating denominator fix.

Observed ratings are selective and cannot represent all customer
satisfaction. Rating/profit/sales relationships are descriptive, not causal.
