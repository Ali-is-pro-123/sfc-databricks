# Step 33 — Multi-location intelligence

This step combines verified outputs from Steps 7, 9, 23, 27, 29 and 32 into one 90-day row per restaurant. It does not define a composite “best location” score or Step 34's location-specific menu classes.

Run from the repository root:

```powershell
uv run python -m python_pipeline.location_intelligence --parquet-root parquet_data --report-root processed_data --as-of 2026-07-01 --output parquet_data/step33-verified-full --reports processed_data/step33-verified-full
```

The analysis window is 2026-04-02 inclusive through 2026-07-01 exclusive. Revenue, cost, direct contribution, quantity, completed orders and average order value retain Step 7's completed-basket definitions. The AOV denominator includes completed headers with empty accepted baskets. Direct contribution excludes overhead. The report provides revenue and contribution ranks, but no overall rank.

Customer count uses distinct identified customers with eligible, known-complete orders at each location in the window. A repeat customer has at least two such orders at the same location. Customers visiting two different locations once each are not local repeat customers. The denominator is eligible customers, not all diners.

Wastage uses accepted Step 23 daily records on local business dates. `accounted_waste_share = wasted_quantity / (accepted_sold_quantity + wasted_quantity)` is an operational proxy, not a full inventory reconciliation rate. Ratings are selected by local submission date, which differs from the sales order-date cohort. Promotion metrics cover Step 27 tagged campaign orders joined to Step 7 window orders. `promo_order_share` divides tagged campaign orders by nonempty completed orders. Promotion contribution and discount are descriptive, not causal lift or campaign success labels. `slow_moving_items` and `watchlist_items` carry Step 32 pair classifications for menu context.

The script requires passed upstream reports, matching cutoffs, expected source row counts and matching location, order and menu financial totals. It refuses to overwrite an existing output. The verified result is `parquet_data/step33-verified-full/location_intelligence.parquet` with its lineage and checks in `processed_data/step33-verified-full/location_intelligence_report.json`. A previous `step33-full` draft was retained because generated outputs were not removed.
