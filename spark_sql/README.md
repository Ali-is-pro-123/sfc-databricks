# Spark SQL

Versioned queries are executed by `spark_jobs/integrate.py` after loading
validated source tables as temporary views.

- `order_lines.sql`: one accepted line per row with dimensions, time-valid
  prices and timestamped ratings; cancelled lines are retained for audit.
- `item_location_daily.sql`: completed sales, waste, observed ratings and
  inventory integrated only after separate aggregation at item/location/day grain.

See `documentation/step_06_integration.md` for formulas and coverage limitations.

The feature runner registers cutoff-filtered views before executing
`item_features.sql`, `customer_features.sql`, and `location_features.sql`.
Do not execute feature SQL against unfiltered all-time views. See
`documentation/step_07_features.md` for the snapshot and leakage contract.

`eda_*.sql` files build Step 8 item, category, location, channel, line-promotion,
local-hour, weekday, month and daily-location summaries. The EDA runner creates
cutoff-filtered temporary views before executing them. See
`documentation/step_08_eda.md` for group grains and reconciliation rules.
