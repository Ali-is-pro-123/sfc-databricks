# Step 17: Market-basket analysis

## Plan before implementation

SRS page 15 requires frequently co-purchased menu items and support,
confidence and lift for suitable combinations. This step is descriptive
association analysis at the completed-order grain, not a recommendation
engine. Step 18 will decide whether and how to recommend bundles.

1. Require the passed Step 6 integration report, matching `order_coverage`
   and `order_lines` Parquet counts and successful markers. Use an exclusive
   `2026-07-01` restaurant-local cutoff. Refuse existing output paths.
2. Define an eligible basket as a completed order with at least one accepted
   line, no known rejected line identities, and a local date before cutoff.
   Include anonymous baskets: item association does not need a customer ID.
   Exclude cancelled, empty and known-partial baskets with audited counts.
3. Join eligible coverage to lines and reconcile line count and basket money
   per order. Deduplicate each `(order_code,item_code)` for presence-based
   market-basket math; quantity and duplicate line occurrences must not
   inflate support. Retain single-item baskets in the denominator.
4. Count item-bearing baskets and unordered co-purchase pairs (`item_a <
   item_b`). Check that the sum of pair basket counts equals the combinatorial
   sum of `k*(k-1)/2` for each basket with `k` distinct items. Persist pairs
   at configurable minimum pair-basket count (30 by default; 2 for small
   rehearsal), while retaining pre-filter totals in the report.
5. Emit both directed rules `A -> B` and `B -> A` for each retained pair:
   support = pair baskets / all eligible baskets; confidence = pair baskets /
   antecedent baskets; lift = confidence / consequent support. Keep exact
   numerator/denominator counts beside ratios. Verify range identities,
   direction symmetry of support/lift, unique rule keys, and saved read-back.
6. Report source lineage, population/exclusion counts, pair/rule counts,
   thresholds and strongest examples. Test a hand-calculated fixture with
   duplicate lines, single-item baskets, cancelled/partial/future orders,
   then run small/full real data.

## Interpretation limits

Co-purchase association is not causal lift from a promotion or proof of
incremental revenue. High lift on rare pairs may be unstable; minimum pair
count is an evidence filter, not a statistical significance test. Step 18
must review availability, margin, conflicts and business suitability before
turning a rule into a recommendation.

## Run and verified result

```powershell
uv run python -m unittest python_pipeline.test_market_basket -v
uv run python -m python_pipeline.market_basket `
  --integration parquet_data/step06-full `
  --integration-report processed_data/step06-full/integration_report.json `
  --cutoff 2026-07-01 `
  --min-pair-orders 30 `
  --output parquet_data/new-step17-full `
  --reports processed_data/new-step17-full
```

Use unused output/report paths. The verified full files are
`parquet_data/step17-full/frequent_pairs.parquet`,
`parquet_data/step17-full/association_rules.parquet`, and
`processed_data/step17-full/market_basket_report.json`. The small rehearsal
uses `step17-small` with a two-basket minimum.

The hand-calculated fixture passed: a duplicated A line in one basket counted
once, single-item baskets stayed in the denominator, and cancelled, partial
and future orders were excluded. Small/full real-data runs passed. Full data
has 330,922 eligible baskets, 991,549 distinct item presences, 16,110
unordered item pairs and 1,099,981 pair occurrences; the latter exactly
matches the basket-size combinatorial check. The 30-basket evidence filter
retains 14,870 pairs and 29,740 directed rules. Six empty, 8,622 cancelled
and 8,745 known-partial baskets were excluded.

The strongest full-data pair is Chicken Biryani 2 (`M0000013`) and Beef Kebab
2 (`M0000014`): 72,700 baskets, support 0.2197, confidence about 0.950 in
each direction and lift 4.111. This is synthetic co-occurrence, not evidence
that bundling would cause additional sales. A 71-basket rule has high lift
but very low support, illustrating why lift alone must not drive Step 18.
