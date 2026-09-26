# Step 19: Peak-period analysis

## Plan before implementation

SRS page 15 requires peak hours, days, weekend patterns, monthly and seasonal
trends, location-specific peaks, and dine-in versus delivery peaks. The
analysis uses complete accepted orders before exclusive 2026-07-01 and
restaurant-local timestamps. One order is one visit regardless of lines.

1. Require passed Step 6 integration and Step 17 basket reports, matching
   lineage, source counts, success markers and cutoff. Rebuild Step 17's
   eligible basket population and reconcile its count. Join order lines only
   to determine the one channel per order; reject conflicting/missing channel
   facts and line/basket revenue differences.
2. Classify Dine-in, Takeaway, Website/App, and explicit Third-party
   Delivery separately. Only Dine-in versus Third-party Delivery is called
   the direct dine-in/delivery comparison. Website/App fulfillment is unknown
   in the source and must not silently be called delivery.
3. Aggregate order count and accepted basket revenue for overall and
   location-level local hour, weekday, weekend/weekday, year-month, and
   meteorological season; add channel-hour/weekend cuts. Use a calendar from
   the first observed local date through the day before cutoff for exposure
   days. Publish orders per eligible calendar day alongside raw totals.
4. Identify top hour and weekday at overall/location grain, normalized
   weekend-versus-weekday rate ratios, and separate Dine-in/Delivery peak
   hours. Break ties by earlier hour or weekday. Persist a long-format
   metric table and compact peak summary with clear denominators.
5. Verify each non-overlapping metric grain independently conserves the
   eligible order count and money, that calendar exposure days are correct,
   the local midnight boundary works, and that cancelled/partial/future
   orders do not leak. Run fixture and small/full data.

## Interpretation limits

Seasons use Winter=Dec-Feb, Spring=Mar-May, Summer=Jun-Aug and Autumn=Sep-Nov;
they are descriptive labels, not a claim about every local climate. The
source spans only January 2025 through June 2026, so seasonal comparisons
have unequal year coverage. Daily rates normalize calendar exposure but not
holidays, promotions or operating hours. Peaks are descriptive, not demand
forecasts or staffing prescriptions.

## Run and verified result

```powershell
uv run python -m unittest python_pipeline.test_peak_periods -v
uv run python -m python_pipeline.peak_periods `
  --integration parquet_data/step06-full `
  --integration-report processed_data/step06-full/integration_report.json `
  --basket-report processed_data/step17-full/market_basket_report.json `
  --output parquet_data/new-step19-full `
  --reports processed_data/new-step19-full
```

Use unused paths. Verified full outputs are
`parquet_data/step19-full-verified/period_metrics.parquet`,
`parquet_data/step19-full-verified/monthly_trends.parquet`, and
`processed_data/step19-full-verified/peak_period_report.json`. The small
rehearsal is in matching `step19-small` paths.

The fixture passed local-midnight cutoff, cancelled/partial/future
exclusion, channel separation, and zero-order calendar exposure. Its first
run revealed a missing-weekend numerator edge case in one channel summary;
that was corrected before the verified full run. All 16 metric grains
independently reconcile order count and revenue to the eligible source.

Full results cover 330,922 complete orders across 546 local calendar days
from 2025-01-01 through 2026-06-30. Channels are 96,178 Dine-in, 138,406
explicit Third-party Delivery, 48,156 Takeaway and 48,182 Website/App.
Overall peak hour is 20:00 local (69,250 orders), peak weekday is Sunday
(794.87 orders per Sunday), and highest calendar date is 2026-06-20
(2,132 orders). Both Dine-in and explicit Delivery peak at 20:00. Weekend
rate is 790.73 orders/day versus weekday 532.23, a ratio of 1.486.

Summer has the highest raw normalized seasonal rate (754.34 orders/day),
but June 2026 alone has 38,052 orders and a rate of 1,268.40/day, far
above May 2026's 553.35/day. This spike and unequal seasonal coverage
make a stable seasonal or staffing conclusion unsafe. The output provides
the monthly series and per-location peaks for review, not a forecast.
