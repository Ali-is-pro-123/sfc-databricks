# Step 46 — Forecast dashboard

The read-only `/dashboard/forecast/` view implements the SRS comparison of historical demand, future forecast demand, actual versus predicted values, forecast errors, and high-risk demand periods. It consumes the passed Step 20 forecast, Step 21 temporal audit, Step 22 accuracy report, and Step 23 accepted-sales monthly summaries. Report hashes and publication status must match; full-network forecast totals and historical accepted quantity reconcile to source reports.

Historical January–June 2026 quantities are all accepted sold portions at accessible locations. Future July–September quantities are Step 20 forecasts for known item/location pairs, with no actuals yet. A planning-review marker means the forecast differs by more than 25% from the preceding three-month actual average. It is a descriptive divergence rule, not a calibrated interval or an SRS-specified threshold.

Only a user with access to the full source network sees the Step 22 March–June held-out actual-versus-predicted rows and three-horizon MAE, RMSE, nonzero-actual MAPE, WAPE and R². The Step 22 report has network-wide backtest aggregates, not location-scoped predictions. Its one-month backtest evaluates 4,295 eligible pairs per month; the historical all-accepted-sales total is a different population (June: 143,687 versus 142,995 evaluated actual portions). A manager therefore never receives network-wide error figures under a local heading.

June's large demand spike was substantially underpredicted in the held-out evaluation. Future forecasts remain review-only and cannot justify automatic inventory or staffing changes. The target is accepted sold portions, not latent demand or unobserved stockouts.

Verification: `uv run python dine_iq/manage.py test apps.restaurants.test_forecast_dashboard --noinput` and `uv run python dine_iq/manage.py check`.
