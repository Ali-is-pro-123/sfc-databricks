# Step 26: Price-sensitivity analysis

## Plan and implementation

The SRS asks for high, moderate and low price-sensitivity classes backed by
historical price and order behavior. Step 25's accepted price epochs and
transitions are the only inputs. Because many synthetic prices changed at
the same time, this analysis does **not** call a simple before/after ratio
causal elasticity. For each transition, it compares the item's log change
in sold portions per exposure day to the median of other items in the same
location, category and transition date. Dividing the peer-adjusted change
by the item's log price increase yields a *descriptive response index*.

A transition is eligible only with a price increase of at least 3%, at
least 30 days and 20 sold portions in both periods, at least five valid
peers, and a discount-share shift no greater than 15 percentage points.
Two eligible transitions are needed per item/location. Both indexes >=1.5
mean high; both <0.5 mean low; indexes >=0.5 and <2.5 mean moderate; other
patterns remain mixed. Missing evidence remains unclassified. A single
item-wide class additionally requires 12 classified locations and at least
60% agreement, otherwise it is insufficient or mixed-location evidence.
These thresholds are explicit analytic rules, not an SRS-specified standard.

The outputs include transition evidence, item/location classes, and
item-wide consensus classes. Source hashes, row/key uniqueness, eligibility,
class validity and Parquet read-back are checked. No source is overwritten.

## Run

```powershell
uv run python -m unittest python_pipeline.test_price_sensitivity -v
uv run python -m python_pipeline.price_sensitivity `
  --epochs parquet_data/step25-full/price_epochs.parquet `
  --transitions parquet_data/step25-full/price_transitions.parquet `
  --price-report processed_data/step25-full/price_intelligence_report.json `
  --output parquet_data/step26-full `
  --reports processed_data/step26-full
```

## Full-data result and limits

Of 8,592 transitions, 6,360 pass the evidence screen. The 4,320
item/location pairs yield 205 high, 65 moderate, 621 low, 1,946 mixed and
1,483 insufficient classes. **No item meets the 12-location minimum for
an item-wide class** (the maximum is 11), so all 180 item-wide results
abstain. This is a valid evidence finding, not a forced classification.

Simultaneous peer price changes, seasonality, promotions and synthetic
demand can still confound the index. Classes are review-only and must not
be used as a causal price recommendation or automated repricing signal.
The report is `processed_data/step26-full/price_sensitivity_report.json`.
