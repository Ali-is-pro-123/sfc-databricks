# Step 37 — Recommendation engine

The SRS asks for evidence-based actions covering menu opportunity, wastage, price sensitivity, bundles, persistent Low Performers, peak stock, customer targeting, promotion review and anomalous locations. This step screens verified outputs from Steps 18, 26, 28, 31, 32, 34 and 36. The candidates are for human review; they do not execute any operational change. Step 38 will add a human-facing evidence presentation, and Step 39 will assign priority.

The rules require non-provisional, high-margin, well-rated Hidden Opportunities for promotion review; recorded high waste for preparation review; only Step 26's sufficiently evidenced local high-sensitivity class for pricing review; screened local frequently paired/combo candidates with positive direct contribution; both a mature Step 32 slow-moving class and a non-provisional Step 34 Low Performer class before redesign review; a sufficiently large high-review-priority customer segment for consent-aware outreach; Step 28 potential promotion traps; and at least three Step 31 flagged location days in the latest 90 days. Thresholds are analytic screens, not SRS-mandated cutoffs. Segment output is aggregate; no customer identity is published.

No stock-increase candidate is produced because the project has observed local peak hours and monthly demand forecasts but no validated forecast of upcoming hourly peak periods. No automated repricing, campaign cancellation, stock adjustment or item removal is recommended. Promotion traps and anomalies remain hypotheses, not causal findings. Direct contribution excludes overhead and platform fees; accepted-data and synthetic seasonality limitations remain.

Run from the repository root:

```powershell
uv run python -m python_pipeline.recommendation_engine --parquet-root parquet_data --report-root processed_data --as-of 2026-07-01 --output parquet_data/step37-full --reports processed_data/step37-full
```

The verified output is `parquet_data/step37-full/recommendation_candidates.parquet`, with report hashes and counts in `processed_data/step37-full/recommendation_engine_report.json`. Each row includes a review action, scope, subject, source steps and machine-readable evidence. It contains 1,319 unique candidates: 55 hidden opportunities, 542 preparation reviews, 205 price reviews, 72 bundles, 418 Low Performer reviews, one segment outreach review, 11 promotion reviews and 15 anomaly investigations. These are candidate counts, not expected financial gains.
