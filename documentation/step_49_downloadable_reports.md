# Step 49 — Downloadable reports

The `/reports/` center offers all twelve SRS report families as offline HTML downloads: menu performance, profitability, customer segmentation, market-basket analysis, demand forecast, wastage, promotions, pricing, location performance, anomalies, recommendations, and Spark versus Python comparison. HTML is a self-contained, printable narrative document, intentionally distinct from the CSV/Excel-compatible data export in Step 50. Responses use attachment disposition, private/no-store cache control and a restrictive content-security policy.

Each report is generated on request for the authenticated user's accessible restaurants from passed analytical snapshots. Existing dashboard services supply menu, profitability, customer, forecast, wastage, location and dual-pipeline figures. The promotions, pricing, anomaly and recommendation reports validate their source row counts before querying location-bearing Parquet. Network-only recommendations are omitted, even for a full-network report, to keep every displayed row explicitly location-scoped.

The Step 17 network-wide association rules are used only when the caller has access to every source restaurant. Otherwise the market-basket report recomputes item-presence support, confidence and lift from eligible complete baskets in accessible locations, with the same minimum 30 pair baskets. Customer segmentation likewise uses Step 44's scoped recomputation. Report notes distinguish historical figures, observational associations, heuristic flags and review-only forecasts; none are automatic actions or causal claims.

Verification: `uv run python dine_iq/manage.py test apps.restaurants.test_reports --noinput` and `uv run python dine_iq/manage.py check`.
