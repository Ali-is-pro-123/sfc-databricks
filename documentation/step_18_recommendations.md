# Step 18: Bundle and cross-sell recommendation candidates

## Plan before implementation

SRS page 15 asks for combo meals, cross-sell opportunities, upsell
combinations and frequently paired dishes, each supported by association
rules. This step creates evidence-backed *review candidates*, not live offers
or claims of incremental revenue. The decision cutoff is 2026-07-01.

1. Require passed Step 17 association, Step 9 profitability, Step 6
   integration and Step 5 quality reports. Check their source hashes,
   cutoffs, row counts and successful Parquet markers. Never read generator
   labels. Refuse existing output paths.
2. Rebuild complete accepted baskets at restaurant grain using Step 17's
   eligibility policy. Compute local basket, item and pair counts. Reconcile
   the local totals to Step 17's global basket/item/pair counts and each
   retained global pair's count to the sum of its local counts.
3. Consider a global Step 17 rule only where the same pair has at least ten
   local baskets and local lift at least 1.05. Retain global support,
   confidence, lift and counts alongside local support/confidence/lift.
   A strong aggregate rule alone must not authorize a location offer.
4. Join both items to the Step 9 local 90-day performance snapshot and
   Step 5 menu availability. Require positive observed direct contribution,
   at least five sold portions, positive latest unit price and catalog
   availability for both. These are safety/evidence filters, not a live
   inventory check. Report how many pairs each guard excludes.
5. Emit four candidate types with reason/evidence: frequently paired dishes
   (top local co-purchases), combo meal pairs (both local directional
   confidences at least 0.15 and lift at least 1.10), cross-sell add-ons
   (directed confidence at least 0.08, consequent price at most 110% of
   antecedent), and higher-value upsell add-ons (same association threshold,
   consequent price above 110%). An upsell add-on means co-purchased higher-
   priced item, never an unsupported substitution claim. Rank and cap per
   restaurant/antecedent to keep output actionable.
6. Persist candidates and an audit of rejected reasons, evidence ranges,
   type/location counts and source lineage. Test directionality, pricing,
   loss-making/unavailable blocks, weak local evidence, and full/small runs.

## Limits

Association and historical contribution do not prove incremental basket
value. A discount could erase margin; no discount price is proposed here.
Stock availability, allergens, preparation capacity, channel fit and human
approval must be checked before publication. A missing or stale signal
causes suppression, not a positive assumption.

## Run and verified result

```powershell
uv run python -m unittest python_pipeline.test_recommendations -v
uv run python -m python_pipeline.recommendations `
  --integration parquet_data/step06-full `
  --integration-report processed_data/step06-full/integration_report.json `
  --baskets parquet_data/step17-full `
  --basket-report processed_data/step17-full/market_basket_report.json `
  --profitability parquet_data/step09-full `
  --profit-report processed_data/step09-full/profitability_report.json `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --output parquet_data/new-step18-full `
  --reports processed_data/new-step18-full
```

Use unused paths. The verified full files are
`parquet_data/step18-full-verified/recommendation_candidates.parquet` and
`processed_data/step18-full-verified/recommendation_report.json`. The small
rehearsal uses `step18-small`.

One fixture test passed. It checked directional pricing (cross-sell versus
higher-priced add-on), a two-way combo, and suppression of negative-margin
or catalog-unavailable items. Small/full real-data runs passed. In full
data, 330,922 baskets, 991,549 item presences and 1,099,981 pair
occurrences reconcile exactly to Step 17; every retained global pair's
count equals the sum of its local counts.

The full report has 1,403 review candidates across all 24 locations: 240
frequently paired, 24 combo meal, 940 cross-sell and 199 higher-priced
add-on candidates. The ordered screen marked 258,692 local pair instances
below ten baskets, 14,349 with weak local lift, 481 with nonpositive direct
contribution, four with low local sales and 2,806 eligible. These are
*first failing guard* counts, not independent risk totals. Ranking/caps
reduce eligible pair instances to the published review candidates.

For example, Chicken Biryani 2 and Beef Kebab 2 appeared together in 4,520
eligible baskets at restaurant `R0000002`; local lift was 3.958 and one
direction's confidence was 0.954. The output intentionally marks
`live_stock_verified=false`, and proposes no discount or auto-published
offer. Operational review is mandatory.
