# Step 38 — Recommendation evidence

The SRS requires every recommendation to display analytical evidence, not an unexplained action. This step renders every passed Step 37 candidate into a human-readable action, measured reasons, source steps and a type-specific caveat. Numeric reasons are taken from Step 37's structured metrics; the renderer rejects missing required values and inconsistent class evidence. A stable candidate ID links the explanation to its original recommendation. No priority or execution is added here; priority belongs to Step 39.

Run from the repository root:

```powershell
uv run python -m python_pipeline.recommendation_evidence --input parquet_data/step37-full/recommendation_candidates.parquet --source-report processed_data/step37-full/recommendation_engine_report.json --output parquet_data/step38-full --reports processed_data/step38-full
```

The verified output is `parquet_data/step38-full/recommendation_evidence.parquet` and `processed_data/step38-full/recommendation_evidence_report.json`. All 1,319 Step 37 candidates have exactly one evidence row and a nonempty caveat. The report records input/report and renderer hashes.

The login-required Django page is `/locations/recommendations/`. It uses the existing Tailwind CDN base template and paginates 20 candidates per page. Location-scoped users see only recommendations for their granted restaurant codes. Analysts and administrators can also see global promotion and customer-segment candidates. The UI shows reasons and caveats, not raw JSON or automatic buttons. If the evidence Parquet is absent, it returns an explicit unavailable state instead of silently showing an empty success page.

These explanations support human review; they do not establish causal uplift, true churn probability, forecasted hourly stock need, or net accounting profit. Do not present the rule screens as measured intervention outcomes. Test with `uv run python -m unittest python_pipeline.test_recommendation_evidence -v` and `uv run python dine_iq/manage.py test apps.restaurants.test_recommendations`.
