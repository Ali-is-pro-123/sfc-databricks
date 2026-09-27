# Step 36 — Customer churn-risk review

The SRS asks for signs of reduced engagement: increasing recency, declining frequency and monetary value, reduced category diversity, and lower visit frequency. This step uses Step 15's known-complete customer visits, Step 16 RFM context and Step 6 accepted line categories. It is a rule-based review signal, not a trained churn model, observed churn label or probability.

At the exclusive 2026-07-01 cutoff, the equal-length prior window is 2026-01-02 through 2026-04-01 and the recent window is 2026-04-02 through 2026-06-30. `recency_days` is Step 15's days since last eligible visit. Frequency decline requires at least two prior visits and recent visits at most half of prior. Monetary decline requires positive prior spend and recent spend at most half. Diversity decline requires at least two prior categories and fewer categories recently. `visit_frequency_ratio` uses these equal 90-day periods; it is the lower-visit-frequency measure, not an extra independent score.

Only customers with at least two lifetime eligible visits and a first visit before the prior-window start have sufficient history. No-purchase customers get `No Purchase History`; other ineligible histories get `Insufficient History`. Among sufficient-history customers, `High Review Priority` means recency over 90 days, or recency over 45 days with both frequency and monetary decline. Otherwise two or more decline signals mean `Watch`, and the remainder get `No Current Decline Signal`. Thresholds are explicit analytic choices, not SRS-specified cutoffs. Seasonal behavior and the synthetic-data June shift may inflate flags, so intervention needs human review.

Run from the repository root:

```powershell
uv run python -m python_pipeline.churn_risk --integration parquet_data/step06-full --integration-report processed_data/step06-full/integration_report.json --segments parquet_data/step15-full/customer_segments.parquet --segment-report processed_data/step15-full/segmentation_report.json --rfm parquet_data/step16-full/rfm_scores.parquet --rfm-report processed_data/step16-full/rfm_report.json --as-of 2026-07-01 --output parquet_data/step36-full --reports processed_data/step36-full
```

The verified result is `parquet_data/step36-full/churn_risk.parquet`, with lineage and checks in `processed_data/step36-full/churn_risk_report.json`. All 60,000 customers are retained, and 122,477 eligible visits reconcile to the two period totals. Counts: 21,391 High Review Priority, 3,611 Watch, 19,913 No Current Decline Signal, 14,725 Insufficient History and 360 No Purchase History. These are review counts, not predicted churn outcomes.
