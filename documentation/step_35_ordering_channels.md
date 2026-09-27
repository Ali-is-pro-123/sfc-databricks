# Step 35 — Ordering-channel analysis

The SRS asks for dine-in, takeaway, restaurant website/app, third-party delivery and any other supported channel to be compared by basket size, average order value, menu preferences, discounts, promotions, peak periods and profitability. The current accepted dataset has the four named channels. The analysis reads channel names from the accepted channel dimension, so an additional supported channel can be included without changing the SQL.

The 90-day cohort is Step 7's completed orders on restaurant-local dates from 2026-04-02 through 2026-06-30. Accepted Step 5 lines supply direct cost, discounts and item preference. Completed headers with no accepted lines stay in the order denominator to preserve Step 7's AOV definition; partial baskets stay visible. Step 27 active campaign order facts provide tagged-campaign counts, not a causal promotion effect. Local peak hours are counts, not exposure-adjusted rates. Direct contribution excludes overhead and platform fees.

Run from the repository root:

```powershell
uv run python -m python_pipeline.ordering_channels --clean parquet_data/step05-full/clean --quality-report processed_data/step05-full/quality_report.json --features parquet_data/step07-full --feature-report processed_data/step07-full/feature_report.json --promotions parquet_data/step27-full --promotion-report processed_data/step27-full/promotion_effectiveness_report.json --location-report processed_data/step33-verified-full/location_intelligence_report.json --as-of 2026-07-01 --output parquet_data/step35-verified-full --reports processed_data/step35-verified-full
```

The verified output has `channel_summary.parquet` (four channels), `location_channel_summary.parquet` (96 location/channel combinations), `channel_menu_preferences.parquet` (720 item/channel combinations with quantity ranks) and `channel_peak_hours.parquet` (36 observed channel/hour combinations). The JSON report records lineage and checks. Completed orders, accepted revenue, direct cost and contribution match Step 7; campaign orders and per-location revenue match Step 33. A first generated `step35-full` draft was retained; `step35-verified-full` is the canonical result.
