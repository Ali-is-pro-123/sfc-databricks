# Step 45 — Wastage dashboard

The read-only `/dashboard/wastage/` view implements the SRS requirements for total wastage, recorded cost, high-wastage items and locations, monthly trends, and wastage-risk predictions. The historical source is the authoritative Step 23 accepted-data output, not its diagnostic runs. July 2026 risk scores come only from the verified Step 24 output.

All queries first restrict restaurant codes to the authenticated user's visible locations. Additive item/location facts yield historical totals and item rankings; the location summary yields location rankings; category/location/month facts yield January–June trends. Whole-network quantity, cost and sold quantity reconcile to the passed Step 23 report. Risk score coverage reconciles to item/location pairs and the passed Step 24 report. A query-string location value cannot expand scope.

The historical waste share denominator is accepted sold plus wasted portions. Preparation logs are incomplete and inventory consumption has an unresolved 18,243-portion full-network gap; neither is presented as a clean operational waste rate. Risk scores concern at least five accepted wasted portions in July, not exact quantity. Held-out ROC-AUC 0.547 indicates modest discrimination. Risk is labelled review-only and must not automate preparation or inventory decisions.

Verification: `uv run python dine_iq/manage.py test apps.restaurants.test_wastage_dashboard --noinput` and `uv run python dine_iq/manage.py check`.
