# Step 47 — Dual-pipeline comparison dashboard

The read-only `/dashboard/dual/` view implements the SRS Spark-versus-Python comparison: paired predictions, match status, numerical difference, agreement percentage and disagreement count. It uses the authoritative Step 14 full verified report and 17,180 held-out record comparisons, not the earlier diagnostic output. Step 12 and 13 report hashes are checked against Step 14 lineage, and paired record counts and unique IDs are reconciled before display.

All summaries, monthly agreement and model errors are recalculated from paired rows after restricting restaurant codes to the authenticated user's accessible locations. A filter cannot broaden that scope. Location, month, status, item code and sort controls narrow only the paginated record table; the cohort summary remains stable. The full-network summary and monthly counts reconcile to the Step 14 report. A mismatch means that the absolute Python-minus-Spark difference exceeds `max(2 portions, 20% of actual quantity)`. The tolerance is a disclosed analysis convention, not exact prediction equality.

The displayed actual-value MAEs are separate from between-model agreement. Diagnostic disagreement codes do not prove causes. June 2026 has the weakest full-network agreement and largest errors. Neither agreement nor a lower MAE establishes deployment readiness.

Verification: `uv run python dine_iq/manage.py test apps.restaurants.test_dual_dashboard --noinput` and `uv run python dine_iq/manage.py check`.
