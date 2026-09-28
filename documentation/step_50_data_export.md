# Step 50 — CSV data export

Authenticated users with at least one visible restaurant can export selected analytical results as UTF-8 BOM CSV, suitable for common Windows spreadsheet applications. The six whitelisted datasets are filtered menu item/location evidence, filtered accepted-sales search results, filtered Spark/Python paired predictions, customer segment and RFM counts, historical/future demand, and wastage summaries. Download links are placed on the corresponding dashboards. These tabular files are distinct from the offline narrative HTML reports in Step 49.

Every export request obtains location grants again and runs the same verified dashboard service with the same validated filters. Menu, search and dual-pipeline exports include **all** matching rows rather than just the first displayed page/top 25. They do not expose customer identifiers. An ungranted location in the query string is ignored, and a user with no visible location receives HTTP 403. Unknown dataset names return 404. Files have attachment disposition and `private, no-store` cache control.

Text values beginning with spreadsheet formula markers (after whitespace) are prefixed with an apostrophe before CSV writing. Numeric values remain numeric. CSV column names carry units and contextual date fields; demand rows distinguish historical actuals from unobserved future forecasts. Search exports preserve the fixed 90-day class/wastage context caveat documented in Step 48. Exports are analytical evidence, not operational approvals.

Verification: `uv run python dine_iq/manage.py test apps.restaurants.test_exports --noinput` and `uv run python dine_iq/manage.py check`.
