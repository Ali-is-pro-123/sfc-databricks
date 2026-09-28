# Step 44 — Customer intelligence dashboard

The read-only `/dashboard/customers/` view covers the SRS customer-dashboard requirements: segment distribution, RFM distribution, high-value and at-risk cohorts, observed promotion-led behavior, and monthly customer trends. The point-in-time cutoff is exclusive `2026-07-01`; trends show January–June 2026.

The full-network view uses the verified Step 15, 16 and 36 Parquet snapshots. It checks their population and classification totals against their passed reports, then reconciles eligible Step 6 visits and revenue against Step 15. It includes registered customers with no eligible purchase.

For a subset of locations, network-wide customer labels would disclose behavior outside the user's access and misstate local cohorts. The view therefore recalculates Step 15 segment precedence and Step 16 RFM rules from eligible Step 6 orders at accessible locations only. Its population consists only of customers with a qualifying visit in those locations, so no-purchase counts are unavailable. The 75th-percentile spend and RFM monetary thresholds are recalculated for that cohort. Step 36 high-review count is intentionally shown only for the full network; it is not filtered from the network-wide risk file. The scoped At-Risk segment is a distinct descriptive measure, not a churn probability.

Eligible orders must be completed, identified, have at least one accepted line and no known rejected lines. The dashboard never displays customer identifiers. Promotion use is observed association, not causal sensitivity. All results remain descriptive and synthetic, requiring human review before outreach.

Verification: `uv run python dine_iq/manage.py test apps.restaurants.test_customer_dashboard --noinput` and `uv run python dine_iq/manage.py check`.
