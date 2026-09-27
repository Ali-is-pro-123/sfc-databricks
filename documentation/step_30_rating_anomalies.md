# Step 30: Rating anomaly detection

## Plan and implementation

The SRS asks for sudden rating spikes/drops, excessive identical scores,
many ratings in a short period, and ratings inconsistent with purchasing.
Step 29's verified rating events and purchase-cohort metrics are the only
inputs. Item and location weekly series include **zero-rating calendar
weeks**. Each week is compared only with the preceding eight weeks, never
future observations. Score-shift flags require eight prior weeks, at least
30 prior and eight current ratings, and a mean change of at least one point.
The identical-score flag requires at least 15 current ratings and 90% of
them sharing one score. Volume flags require at least 20 current ratings,
30 ratings in the prior eight weeks, and a count at least twice the prior
weekly mean and two standard deviations above it.

For purchase-pattern checks, item/month rating count and sold-line count
come from the *same purchase-month cohorts*. Three prior months are needed.
One flag catches a rating-coverage jump (at least 10 ratings, 35% coverage,
and twice the prior three-month coverage). Another catches ratings rising
at least 50% while sold lines fall at least 25%, with at least 15 prior
ratings. Small or history-poor groups abstain. Each output row retains
current counts and prior baselines. These thresholds are explicit analytic
choices, not SRS-prescribed statistical significance levels.

The runner verifies Step 29 file identity and row counts, that item-week
and location-week sums each conserve the source rating count, that monthly
ratings and sales reconcile, unique keys, valid score shares, and saved
Parquet read-back. Flags are **review-only**, not fraud findings.

## Run

```powershell
uv run python -m unittest python_pipeline.test_rating_anomalies -v
uv run python -m python_pipeline.rating_anomalies `
  --events parquet_data/step29-verified-full/rating_events.parquet `
  --metrics parquet_data/step29-verified-full/rating_metrics.parquet `
  --rating-report processed_data/step29-verified-full/rating_satisfaction_report.json `
  --output parquet_data/step30-full `
  --reports processed_data/step30-full
```

## Verified full result

Among 117,184 accepted rating events, the rules flag one sudden item-week
spike, zero sudden drops, one excessive-identical item-week, and 163
high-volume item-or-location weeks. The purchase-pattern rules flag zero
item-months. Counts can overlap across different flag types, and a single
synthetic event can affect multiple weeks. The report is
`processed_data/step30-full/rating_anomalies_report.json`.

Observed rating patterns may reflect genuine changes, promotional
selection or synthetic scenario design. No automatic customer or restaurant
penalty should follow a flag.
