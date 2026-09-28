# Step 48 — Search and filtering

The read-only `/dashboard/search/` explorer combines the SRS filter dimensions: date range, accessible location, menu item name/code, category, customer segment, ordering channel, promotion, item/location performance class, historical unit-price range, observed line rating, and item/location wastage range. Inputs are bounded and SQL-parameterized. The selected filters apply jointly to eligible line-level sales; summary counts and top item/location rows share one filtered denominator.

The source population is Step 6 identified, completed, known-complete accepted baskets before 1 July 2026. A full-history network query reconciles to Step 15's 988,946 eligible lines. For full-network access, verified Step 15 segment labels are used. For a subset of locations, segment labels are recomputed from eligible visits in only those locations using Step 15 precedence; global customer labels and no-purchase population are not exposed. A requested location outside the user's granted scope is ignored.

Unit price and rating filters refer to each historical line. Rating filters exclude lines without observed ratings. Performance class and waste-range filters refer to the Step 34 fixed 90-day item/location snapshot (2 April–30 June 2026), regardless of the selected sales date range. The displayed pair waste is context, not wastage attributed to the selected customers, channels, promotions or sales dates. Promotion use is observational, not causal sensitivity. The default sales date range matches the 90-day menu window; users may select any date from 1 January 2025 through 30 June 2026.

Verification: `uv run python dine_iq/manage.py test apps.restaurants.test_search_dashboard --noinput` and `uv run python dine_iq/manage.py check`.
