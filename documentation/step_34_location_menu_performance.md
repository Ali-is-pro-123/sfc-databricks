# Step 34 — Location-specific menu performance

The SRS requires Profit Driver, Volume Driver, Hidden Opportunity and Low Performer identification for the same item at different locations. Step 10 already assigned these classes independently within each restaurant/category peer group. Step 34 exposes those verified pair classes, compares them with item-wide classes, and summarizes their mix per location. It does not invent a new classifier or prescribe automatic removal or price changes.

Run from the repository root:

```powershell
uv run python -m python_pipeline.location_menu_performance --classes parquet_data/step10-full --class-report processed_data/step10-full --locations parquet_data/step33-verified-full --location-report processed_data/step33-verified-full --as-of 2026-07-01 --output parquet_data/step34-full --reports processed_data/step34-full
```

Outputs:

- `location_menu_items.parquet`: one row per restaurant/item, carrying the local and item-wide classes, evidence, provisional flag, financials and a flag for cross-location variation.
- `location_menu_summary.parquet`: four-class counts and revenue by class for each of 24 restaurants, reconciled to Step 33 location totals.
- `cross_location_item_variation.parquet`: each item's class distribution across restaurants.

All 4,320 local pairs and 180 items are covered. Of the items, 179 have more than one location class; 2,405 pairs differ from their item-wide class. Different peer groups explain why these comparisons are informative, not contradictory. Some local results are provisional; Step 10's classification thresholds and accepted-data limitations still apply. Revenue and direct contribution are descriptive and exclude overhead. The report retains report hashes and SQL lineage, checks unique keys and cutoff, protects loss-making rows from positive classes, and reconciles 90-day revenue, cost, contribution and quantity against verified inputs.
