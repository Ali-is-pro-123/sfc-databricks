# Step 11: Tricky menu performance cases

## Plan

SRS page 12 specifies ten difficult cases. This step audits the verified Step
10 business-rule classifications against each one, without using synthetic
scenario labels, clean-reference answers, or future data to manufacture a
match. Detection and classification are separate: a case may be present even
if its observed class differs from an intuitive label.

1. Require passed Step 6 and Step 10 reports, matching Step 9 lineage hashes,
   unchanged classifier source hash, successful Parquet writes, exact row
   counts and unused output directories. Use accepted completed Step 6 lines
   only for the historical seasonal check.
2. Produce an item-wide audit for the ten cases, retaining Step 10 item code,
   name, class, reason, key economics and evidence flags. Produce a local audit
   for item/location disagreement and weekend-dominant ordering. Do not
   overwrite the classified snapshots.
3. Identify high-sales losses, profitable low-demand dishes, popular high-
   waste dishes, highly rated low-profit dishes, low-rated high-sales dishes,
   and promotion reliance using measured Step 10 peer scores/flags. A
   negative-contribution item must remain Low Performer; high recorded waste
   or poor observed rating cannot become a Profit/Volume Driver under the
   documented policy.
4. Identify cross-location class differences only when at least two locations
   have meaningful sales evidence. For weekend concentration, normalize local
   weekend/weekday order frequencies by the actual numbers of each day in the
   90-day window, rather than comparing raw counts.
5. Test possible seasonality only across two comparable six-month calendar
   windows one year apart. Both windows must have enough accepted portions,
   full item exposure, and the same strongly dominant three-month half. This
   is a limited repeat-pattern screen, not a general seasonal forecast.
6. Retain new items with insufficient history and their provisional class.
   Zero observed cases in a particular dataset is reported honestly, not
   turned into a fabricated example. Fixture tests must exercise all cases;
   the full job must verify 180/4,320 input coverage, unique grains, class
   conservation and semantic safety guards.

## Operational definitions

- High selling means Step 10 peer-high demand. Loss-making means negative
  90-day direct contribution; it is not accounting net loss after overhead.
- Rare but profitable means below peer-high demand, peer-high profitability,
  positive contribution and positive observed sales. Other risks can still
  make the item a Low Performer rather than a Hidden Opportunity.
- High waste, high/poor rating and high promotion reliance use the recorded
  Step 10 peer comparisons. Promotion-dependent additionally requires at
  least a quarter of sold portions to be line-campaign attributed. This is
  exposure, not evidence of causal campaign lift.
- A location difference requires two sold locations with differing classes.
  The local class is preserved; the item-wide class never replaces it.
- Weekend-dominant means at least twenty 90-day item/location orders, at least
  65% on weekends, and a weekend daily order rate at least three times the weekday
  daily rate. It is not a claim of zero weekday sales.
- A possible seasonal pattern needs at least 50 accepted portions in each
  comparable six-month window, item introduction before the older window, and
  the same first or second three-month half having at least 1.5 times the
  other half's per-day portion rate in both years. Only two repeated half-year
  windows are available; this is suggestive, not confirmed seasonality.
- New/insufficient means age under 30 days and no defensible 30+30-day trend.
  The class remains provisional, not a confident recommendation.

## Boundaries

The audit uses accepted data; rejected lines and partial baskets remain
coverage limitations. The wastage denominator is accounted sold plus recorded
wasted portions, not total food prepared. Rating and repeat evidence can be
missing. The synthetic scenario labels are deliberately excluded from audit
logic; later independent evaluation can compare them as an external oracle.

## Run commands

Run from the repository root. Spark stays in Docker, while Windows Python
dependencies continue to use uv. Use fresh output/report directories on rerun.

```powershell
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master local[2] /opt/dineiq/spark_jobs/test_case_audit.py
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.driver.host=spark-master --conf spark.driver.bindAddress=0.0.0.0 /opt/dineiq/spark_jobs/case_audit.py --classification /opt/dineiq/parquet_data/step10-full --classification-report /opt/dineiq/processed_data/step10-full/classification_report.json --profitability-report /opt/dineiq/processed_data/step09-full/profitability_report.json --integration /opt/dineiq/parquet_data/step06-full --integration-report /opt/dineiq/processed_data/step06-full/integration_report.json --output /opt/dineiq/parquet_data/new-case-audit-full --reports /opt/dineiq/processed_data/new-case-audit-full
```

## Verification evidence

Three targeted Spark fixture tests passed, exercising all ten case flags,
cancelled/future-sale isolation for seasonality, class context, and reused-
output rejection. A first real-data pass found the weekend screen too broad;
its order/share/daily-rate minimums were tightened and all tests rerun. The
final small/full standalone runs passed in 24.769/26.389 seconds. The final
full outputs are `parquet_data/step11-full-v2/`, with a passed report at
`processed_data/step11-full-v2/case_audit_report.json`.

| Case | Full-data items |
| --- | ---: |
| High sales, negative direct contribution | 1 |
| Profitable, below peer-high demand | 39 |
| Popular, high recorded waste | 10 |
| Strong rating, lower peer profitability | 35 |
| Poor rating, high sales | 14 |
| Promotion-dependent by peer and portion share | 3 |
| Differing classes across sold locations | 178 |
| Strong weekend concentration at a location | 2 |
| Possible repeated half-year seasonal pattern | 1 |
| New item with insufficient history | 0 |

The high-sales loss case is Chicken Biryani 1, correctly retained as Low
Performer. The single possible seasonal item is Chocolate Cake 1. A zero for
new/insufficient history means the current full snapshot provides no such
example under this definition; it does not mean the case is unsupported.
Item and local audit rows match all 180 and 4,320 Step 10 inputs. Quantity,
revenue, direct cost and contribution reconcile exactly at both grains. The
case audit checks classification safety guards but does not train a model,
claim causal promotion effects or issue final recommendations.
