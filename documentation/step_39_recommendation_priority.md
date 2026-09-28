# Step 39 — Recommendation priority

The SRS asks for Low, Medium, High and Critical review priorities based on potential business impact. This step preserves all Step 38 explanations and adds a type-specific **current exposure** measure, its unit and basis, the priority label, and a plain-language reason. Exposure is existing sales, recorded waste cost, pair baskets or customers under review. It is not predicted uplift, recoverable loss or expected savings. Measures with different units must never be summed or compared directly.

The explicit review policy is:

| Candidate | Exposure basis | High review threshold | Critical gate |
| --- | --- | --- | --- |
| Hidden Opportunity | Local 90-day direct contribution | >= PKR 20,000 | None; uplift unproven |
| Preparation/waste | Accepted 90-day item-location waste cost | >= PKR 5,000 and accounted waste >=25% | >= PKR 10,000 and waste >=40% |
| Price sensitivity | Local 90-day accepted revenue | >= PKR 50,000 | None; response not causal |
| Bundle | Local co-purchase baskets | >=40 baskets and lift >=1.5 | None; bundle uplift unproven |
| Low Performer | 90-day negative direct contribution, floored at zero | >= PKR 1,000 direct loss | None; removal is unsafe to automate |
| Segment outreach | High-review-signal customers | >=10,000 customers | None; churn is not calibrated |
| Promotion review | Tagged campaign revenue and trap count | >= PKR 1 million and >=2 flags | None; flags are observational |
| Location anomaly | Revenue on flagged days; count controls label | >=10 flagged days | None; anomaly is not proven loss |

Medium thresholds are in the code and are also deterministic: PKR 10,000 contribution, PKR 2,000 waste cost, PKR 20,000 price-exposed revenue, 20 pair baskets, PKR 500 direct loss, 1,000 high-review customers, PKR 500,000 campaign revenue, or five flagged days respectively. Below those thresholds is Low. These are analytic review thresholds, not SRS-prescribed cutoffs. Critical is deliberately narrow; no current candidate meets its combined waste gate, so no Critical label is forced. High does not authorize action.

Run from the repository root:

```powershell
uv run python -m python_pipeline.recommendation_priority --evidence parquet_data/step38-full/recommendation_evidence.parquet --evidence-report processed_data/step38-full/recommendation_evidence_report.json --menu parquet_data/step34-full/location_menu_items.parquet --menu-report processed_data/step34-full/location_menu_performance_report.json --waste parquet_data/step23-accepted-full/wastage_daily.parquet --waste-report processed_data/step23-accepted-full/wastage_report.json --promotions parquet_data/step28-verified-full/promotion_traps.parquet --promotion-report processed_data/step28-verified-full/promotion_traps_report.json --anomalies parquet_data/step31-full/location_day_anomalies.parquet --anomaly-report processed_data/step31-full/sales_anomalies_report.json --as-of 2026-07-01 --output parquet_data/step39-full --reports processed_data/step39-full
```

The verified output is `parquet_data/step39-full/prioritized_recommendations.parquet` with report `processed_data/step39-full/recommendation_priority_report.json`. All 1,319 candidates are present: 189 High, 467 Medium, 663 Low and zero Critical. The existing `/locations/recommendations/` Django page now sorts by review priority and shows/filter labels, exposure and reasons while preserving location-based access. Tests verify priority boundaries, one-to-one coverage, Django role scope and filters.
