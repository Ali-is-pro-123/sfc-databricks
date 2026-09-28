# Development Log

## Step 1 - Foundation and architecture

### Work completed

- Reviewed the complete DineIQ SRS and its sample architecture.
- Confirmed the local uv, Python, Docker Engine, and Docker Compose installations.
- Defined the Windows host and Docker service boundary.
- Added PostgreSQL, Redis, Spark master, and Spark worker services.
- Added environment-based Django settings and PostgreSQL support.
- Created the SRS-aligned repository layout and architecture documentation.
- Added the mandatory AI usage declaration.

### Decisions

- Django development runs on Windows through uv.
- Linux-oriented infrastructure runs in Docker.
- PostgreSQL is the project database; SQLite remains a no-environment fallback
  only for early configuration checks.
- Spark 3.5.9 with Java 17 is pinned for repeatable development.
- Custom Django users will be created before the first database migration.

### Tests performed

- `uv sync --frozen` completed from the committed lockfile.
- `uv run python dine_iq/manage.py check` reported no issues.
- `docker compose config --quiet` accepted the Compose configuration.
- PostgreSQL accepted a Django connection and returned `1` for `SELECT 1`.
- Redis returned `PONG` through `redis-cli`.
- The Spark master reported `ALIVE` with one registered worker, two cores, and
  2 GiB worker memory.
- The official PySpark Pi example completed on the standalone cluster and
  returned an estimate of `3.141520`.

### Issues and follow-up

- Host ports 7077, 8080, and 8081 were already used by another local Spark
  project. DineIQ uses 17077, 18080, and 18081 without changing the standard
  ports inside its Docker network.
- Service URLs use the explicit `127.0.0.1` loopback address because the
  containers are intentionally not published on IPv6 or external interfaces.
- The custom user model was deferred to Step 2 and is now implemented below.
- Spark processing jobs are added in later Big Data steps.

## Step 2 - PostgreSQL and authentication (2026-09-25)

### Plan

- Inspect database state before defining the first custom user migration.
- Define four roles, protected pages, and administrator-managed registration.
- Implement English Django templates using Tailwind CDN.
- Validate authentication, role checks, CSRF, and privilege boundaries.

### Work completed

- Confirmed the application database had no existing tables.
- Added `accounts.User` before applying initial PostgreSQL migrations.
- Added login, POST logout, protected home, paginated account list, and creation.
- Restricted account management to active administrators or superusers.
- Restricted Django user administration to superusers.
- Created an ignored `.env` with a random Django secret and PostgreSQL URL.
- Documented setup, access policy, and the first administrator creation command.

### Verification

- All 13 account tests passed against a separate PostgreSQL test database.
- Django system check reported zero issues.
- Migration consistency check reported no pending model changes.
- uv lock consistency passed; `.env` was confirmed ignored by Git.
- Templates were exercised by Django HTTP tests; visual browser QA is pending.

### Boundaries

- No application user or default password was seeded; use `createsuperuser`.
- Location scoping will be implemented with restaurant domain models.
- Step 2 includes the authentication work originally listed as Step 3.

## Step 3 - Restaurant domain (2026-09-25)

### Plan and decisions

- Recorded the implementation plan in `step_03_domain.md` before creating models.
- Model eleven SRS entities plus ordering channels and location access grants.
- Keep historical monetary snapshots, unique import codes, decimal amounts,
  database constraints, and explicit manager location scopes.
- Deliver administrator management and scoped read pages before data generation.

### Work completed

- Created the restaurants application and applied its initial PostgreSQL migration.
- Added domain administration at `/management/` with business-role login.
- Added location directory/details and current effective price selection.
- Defined the data dictionary, calculation formulas, and bulk import boundaries.
- Added 19 domain regression tests alongside the existing 13 account tests.

### Verification and limits

- All 32 tests pass on a separate PostgreSQL test database.
- Django system checks and migration consistency checks pass.
- No application dataset was seeded or existing user accounts modified.
- Manager write workflows, pipeline checks, and analytics remain later work.
- Visual browser verification is pending; templates and admin forms are HTTP-tested.

## Step 4 - Synthetic generation (2026-09-25)

### Work and decisions

- Implemented configurable seeded profiles, stable codes, streaming CSV output,
  monthly transaction files, schema/type metadata, checksums, and JSON samples.
- Added line-level promotion attribution and its PostgreSQL migration.
- Generated linked customers/orders, dated prices, valid ratings, portion-based
  inventory/wastage, bundles, and controlled contradictory restaurant cases.
- Isolated latent labels and the exact corruption ledger in evaluation files.
- Added an independent disk-index validator and CSV-derived scenario evidence.

### Verification

- Small and medium datasets passed relationship, numeric, temporal, stock and
  corruption checks before the full run.
- Full run: 1,050,000 clean lines, 350,000 orders, 60,000 customers, 18 months,
  120,000 ratings, 75,000 wastage records; all SRS dataset size minima met.
- 16,065 injected defects reconcile exactly to the raw files and ledger.
- All 12 full-scale scenario evidence checks passed.
- 33 account/domain tests passed, including new promotion eligibility checks.
- Generator tests cover reproducibility, corruption independence, tampering,
  invalid FKs, configurations, counts, overwrite refusal, and scenario evidence.

### Issues and fixes

- Fixed validator half-cent discrepancies with integer paisa rounding; an
  independent Decimal comparison confirmed generated discounts were correct.
- Initial timing included a long verification run. Profiling identified repeated
  Windows path parsing per row; paths are now cached once per file/bucket.
- Full generation took 333.271 seconds and validation 490.245 seconds before that
  optimization. Timing is workload-specific; peak RAM was not recorded.
- Full data is on disk, ignored by Git, and not yet ingested into Spark or Django.

## Step 5 - Spark ingestion and quality (2026-09-25)

### Work and decisions

- Added raw CSV header checks, explicit landing/typed schemas, and separate
  schema-inference evidence using the pinned Linux Spark image.
- Implemented auditable duplicate, key, type, numeric, temporal, campaign,
  rating, unit, inventory, and wastage rules with cascading reference checks.
- Kept anonymous/cancelled orders and quarantined invalid rows without reading
  clean-reference data or evaluation labels.
- Added monthly clean Parquet, quarantine payloads/reasons, persisted status
  reports, join row-count guards, and read-back conservation checks.
- Used new output directories; no existing dataset or application rows changed.

### Verification and limits

- Small standalone-cluster run passed across all 13 tables in 378.991 seconds.
- Full standalone-cluster run passed in approximately 489.43 seconds:
  4,017,048 input rows = 3,995,252 accepted + 21,796 quarantined.
- Accepted order lines total 1,035,861. All five transaction tables have 18
  monthly partitions. All output table writes and read-back counts passed.
- 8 Spark regression tests, 11 generator tests, and 33 Django tests passed;
  Django system checks and uv lock consistency passed.
- PySpark test collection emitted socket ResourceWarnings, but tests exited 0.
- Spark remains in Docker; no new Windows Python packages were needed.
- Joined analytics, reconciliation/coverage reporting, features, ML training,
  and Django result integration remain later steps.

## Step 6 - Analytical integration (2026-09-25)

- Planned against SRS integration relationships and implemented versioned SQL
  for line facts and independently aggregated daily operational records.
- Added historical price intervals, local dates, timestamped ratings, order
  coverage, cancelled-sale exclusion and explicit inventory differences.
- Small and full standalone runs passed. Full: 1,035,861 lines, 348,295 order
  headers and 2,346,339 daily records; runtime 373.466 seconds.
- All source/fact/daily money and quantity conservation checks passed. Found
  8,939 partial orders, 6 empty accepted baskets and 18,243 portions of net
  inventory coverage difference; these were not automatically corrected.
- 10 integration, 8 quality, 11 generator and 33 Django tests passed.
- Saved execution logs and report/SQL/job hashes. Windows uv dependencies unchanged.
- No Django import or ML training. Human review is still required.

## Step 7 - Feature engineering (2026-09-25)

- Planned the SRS feature families with explicit exclusive local cutoff and
  configurable analysis windows. Documented undefined ratios and partial coverage.
- Added item/location money, popularity, repeat/rating, waste, campaign, price and
  temporal features; customer RFM/preferences; basket and location summaries.
- Excluded cancelled/future orders and future rating/price events. Customer spend
  excludes anonymous, partial and empty baskets; cohort labels are not features.
- Recovered stopped Docker Desktop using its existing installation. Fixed a syntax
  error caught by static compilation before Spark execution; no source reset.
- All 9 feature tests passed. Small/full runs passed in 206.632/194.104 seconds.
- Full snapshots: 4,320 item/location, 60,000 customer, 73,982 basket and 24
  location rows. Financial and eligible-customer conservation checks passed.
- Full window includes 71,871 customer-eligible baskets and 2,111 exclusions;
  observed rating count is 26,705. Recorded job hash matches the source.
- Django and uv lock checks passed; no Windows dependency changes, fitted models,
  analytical dashboard, predictions or recommendations were introduced.

## Step 8 - Exploratory data analysis (2026-09-25)

- Planned the SRS EDA views, their grains, cutoff, minimum-rating threshold,
  ranking tie-breaks, and interpretation limits before implementation.
- Added ten Spark SQL views and a report-driven job for item, category,
  location, channel, promotion, hourly, weekday, monthly, location-hour and
  location-day exploration. No generator labels or model outputs were read.
- Corrected a Spark Column predicate check found by the fixture tests. All
  eight targeted tests then passed; small and full standalone-cluster runs
  passed in 146.555 and 207.042 seconds, respectively.
- Full outputs contain 180 items and 18 months. All ten table totals reconcile
  to 1,182,659 completed-sale portions, PKR 529,382,947.61 revenue, PKR
  305,410,197.53 cost and PKR 223,972,750.08 contribution.
- Completed headers number 339,673; 339,667 bear accepted sale lines. The
  cutoff retains 117,181 ratings and 74,244 waste records; three otherwise
  accepted ratings arrived after the cutoff and were excluded.
- Observed Chicken Biryani 1 as third in quantity but negative in contribution,
  reinforcing that popularity and profitability require separate analysis.
  No causal campaign lift, net profit, ML classification, or Django dashboard
  was claimed. Generated outputs are ignored by Git; human review is pending.

## Step 9 - Menu profitability analysis (2026-09-26)

- Planned against all ten SRS page 11 dimensions, retaining Step 7's 90-day
  item/location grain and adding independently aggregated prior/recent 30-day
  sales periods from verified Step 6 accepted transactions.
- Preserved direct contribution rather than claiming accounting net profit;
  excluded cancelled/future lines, suppressed undefined or insufficient-history
  trends, and retained negative contribution and missing-evidence flags.
- Four targeted Spark tests passed. Small/full standalone runs passed in
  22.200/20.055 seconds, yielding 144/4,320 item/location rows.
- Full 90-day output reconciles 265,989 portions, PKR 125,910,828.14 revenue,
  PKR 70,612,065.23 cost and PKR 55,298,762.91 contribution. Twenty-four rows
  have negative contribution; 339 have no defensible quantity trend percentage.
- No Step 10 menu classes, fitted model, dashboard or recommendation was made.
  Generated outputs remain outside Git and await independent human review.

## Step 10 - Menu performance classification (2026-09-26)

- Planned against SRS page 11's four exact classes and page 12's tricky-case
  risks. Used Step 9's verified 90-day item/location snapshot as sole data
  input; upstream report/job hashes, row counts and successful Parquet marker
  are checked before classification.
- Added item-wide additive aggregation and location/category peer rankings for
  exposure-adjusted demand and direct profitability. Ratings, repeat purchase,
  waste, promotion dependency and trend remain auditable evidence/risks.
- Applied multi-signal class precedence with a negative-contribution guard,
  reason and provisional-evidence flags. These are business rules, not models.
- Four targeted Spark tests passed. Small/full standalone runs passed in
  24.730/26.693 seconds, yielding 36/180 item-wide and 144/4,320 local rows.
- Full item classes: 16 Profit Drivers, 27 Volume Drivers, 35 Hidden
  Opportunities, 102 Low Performers. All rows have one valid class and all
  quantity/revenue/cost/contribution totals match Step 9 at both grains.
- No Step 11 case audit, trained ML model, Django dashboard or final business
  recommendation was created. Generated outputs remain outside Git.

## Step 11 - Tricky menu performance cases (2026-09-26)

- Planned ten SRS page 12 case definitions before implementation. Kept the
  passed Step 10 item/local classes and accepted Step 6 line facts separate
  from synthetic scenario labels and future observations.
- Added item and location audits with specific evidence flags, source/report
  lineage checks, normalized weekend rates, and comparable two-year half-year
  seasonal windows. Kept detection distinct from recommendations.
- Three fixture tests passed, covering all ten case flags and cancelled/future
  seasonal isolation. The first real-data weekend screen was too broad;
  tightened its minimum order count/share/daily-rate and reran tests and jobs.
- Final small/full standalone runs passed in 24.769/26.389 seconds. Full
  outputs retain 180 item and 4,320 local rows; financial/quantity totals
  reconcile with Step 10. Chicken Biryani 1 remained Low Performer despite
  high sales and negative contribution.
- Full case counts are in `documentation/step_11_tricky_cases.md` and the
  passed report. No new/insufficient-history item matched the current full
  snapshot, while the fixture exercised that case. No ML model or Django
  dashboard was introduced; human review remains pending.

## Step 12 - Spark MLlib demand models (2026-09-26)

- Planned next-calendar-month item/location accepted-demand prediction from
  historical Step 6 daily records. Set non-overlapping monthly label windows,
  chronological train/validation/test cutoffs, and train-only preprocessing.
- The pinned base Spark image lacked NumPy. A pip-wheel Docker build timed out;
  extended the image with Ubuntu NumPy/SciPy packages instead and recreated
  Spark master/worker while preserving data mounts and other service volumes.
- Three temporal/metric tests passed. Small/full standalone runs passed in
  179.238/191.930 seconds, generating 1,948/60,105 supervised rows.
- Compared linear regression, decision tree and random forest against a
  recent-demand baseline. Full validation MAEs: 4.289, 4.779 and 4.834
  portions respectively; baseline 4.360. Selected linear regression before
  viewing held-out test metrics.
- Full test has 17,180 predictions; selected model MAE 9.043 versus baseline
  9.422, but RMSE 41.380 versus baseline 41.158. Saved pipeline load and
  prediction read-back passed. Source target conservation passed.
- No generator label or Step 10 class was trained as ground truth. The
  independent Python pipeline, dual-pipeline comparison, configurable demand
  forecasts and deployment decision remain future work.

## Step 13 - Independent Python demand pipeline (2026-09-26)

- Planned against SRS page 13's separate-pipeline requirement. Read Step 5
  accepted clean orders, lines, restaurants, menu, ratings and wastage only;
  independently rebuilt restaurant-local daily facts and chronology-safe
  monthly features using DuckDB, then fitted scikit-learn models with uv.
- Input counts were checked against the passed Step 5 quality report. Direct
  completed-line quantity/revenue/cost reconciled with rebuilt daily facts;
  labels reconciled with source sales. Snapshot keys, chronology and model
  reload were checked. Three focused Python tests passed, including timezone
  conversion and a changed future label leaving history unchanged.
- Small/full runs passed with 1,948/60,105 supervised snapshots. The full
  source reconciled 1,182,659 portions, PKR 529,382,947.61 revenue and PKR
  305,410,197.53 direct cost; monthly labels total 944,315 portions.
- Full validation MAE was 4.289 for Ridge, 3.941 for Extra Trees and 4.360
  for the baseline. Extra Trees was selected before test inspection. Full
  17,180-row test MAE was 8.785 versus baseline 9.422; RMSE was 41.163
  versus baseline 41.158. This does not establish deployment readiness.
- Python held-out predictions retain record keys for Step 14. No Spark
  integrated daily facts, snapshots, predictions, or fitted pipeline were used
  in this training. Formal agreement/disagreement analysis and dashboards
  remain pending; generated outputs are outside Git.
- A final CSV uniqueness check exposed a wrong restaurant-column index in
  export code. Corrected the exporter, rebuilt both CSVs from saved Python
  snapshots/models, and verified all 17,180 full keys are unique and the
  recomputed test MAE exactly matches the JSON report.

## Step 14 - Dual-pipeline result verification (2026-09-26)

- Planned SRS page 13's required record-level comparison before coding. The
  shared task is Step 12/13 next-month accepted sold portions. Comparison
  consumes saved outputs only; it does not retrain either pipeline.
- Added report/source guards, unique-key checks, full snapshot key/label/
  feature parity, held-out actual/baseline parity, per-record numerical
  differences and diagnostic disagreement codes. The disclosed agreement
  tolerance is the larger of two portions or 20% of actual.
- Four comparison fixture tests passed, along with three Step 13 tests.
  Small and full comparisons passed. Full snapshots: 60,105 on each side,
  zero unmatched keys, zero actual/split differences and zero compared
  feature differences. Full test: 17,180 paired unique predictions.
- Full agreement: 15,239/17,180 = 88.70% within tolerance; no exactly equal
  model outputs. Spark/Python test MAE: 9.043/8.785. Recomputed MAE, RMSE,
  WAPE, actual totals and row counts match each model's saved report.
- June 2026 is a notable weakness: 85.19% agreement and respective monthly
  MAEs of 24.52/24.07. Independent models are not thereby validated for
  deployment. Human review of disagreement cases remains pending.

## Step 15 - Customer segmentation (2026-09-26)

- Planned all ten SRS page 14 behavioral dimensions and one transparent
  segment per accepted customer at an exclusive 2026-07-01 cutoff. Used
  passed Step 6 order coverage/lines and Step 5 clean customers; no Spark
  predictions or generator cohort labels entered classification.
- Excluded cancelled, anonymous, empty and known-partial baskets from
  behavioral features, with counts retained. Aggregated accepted lines to
  one visit before customer rollup and reconciled money, lines and visits at
  order and customer grains. Stored recency, frequency, spend, AOV, visit
  rate, favorite category/channel/daypart, promotion share and repeat flag.
- Four tests passed, including future-order exclusion and a two-line visit
  counted once. Small/full runs passed; full output has one segment for each
  of 60,000 customers, based on 330,045 eligible visits and PKR
  517,880,620.35 reconciled revenue.
- Full segment counts: 19,568 At-Risk, 19,374 Occasional, 10,320 New, 9,692
  Promotion-Driven, 806 High-Value Loyal, 239 No Purchase Yet and 1 Frequent.
  Threshold precedence explains the rare Frequent label. Rules are not
  unsupervised clusters or causal promotion sensitivity; human review and
  Step 16 formal RFM scoring remain pending.

## Step 16 - RFM analysis (2026-09-26)

- Planned an independent, point-in-time RFM score from Step 15's verified
  customer features, preserving its segment labels as context rather than
  changing them. R is days since last eligible visit; F is visits in the
  prior 180 days; M is accepted spend in the same period.
- Added explicit recency/frequency score bands and positive-active-customer
  monetary quantiles. Zero-purchase customers retain null recency and `000`
  scores. Combined code, total, tier, and Step 15 segment cross-tab are
  persisted; ties retain the same score.
- A boundary/tie fixture test and small/full runs passed. The full read-back
  has 60,000 unique customers, 330,045 lifetime visits and PKR
  517,880,620.35 lifetime spend, matching the Step 15 report. All 360
  no-purchase customers have `000`.
- Full tiers: 8,173 Top, 2,664 High, 23,837 Medium, 24,966 Low and 360 No
  Purchase History. Synthetic quantiles and descriptive tier names do not
  predict churn or lifetime value. Human review is pending.

## Step 17 - Market-basket analysis (2026-09-26)

- Planned SRS page 15 support/confidence/lift analysis at the complete-order
  basket grain. Included anonymous orders but excluded cancelled, empty,
  known-partial and post-cutoff baskets with explicit counts.
- Deduplicated repeated item lines within each basket, kept one-item baskets
  in the denominator, and generated unordered pair counts plus both rule
  directions. Per-order line/money and global pair-combination identities
  reconcile; formula/range and unique-key guards passed.
- One hand-calculated fixture test passed. Small/full runs passed. Full data
  has 330,922 eligible baskets, 991,549 distinct item presences, 16,110
  unordered pairs and 1,099,981 pair occurrences. A 30-basket evidence
  threshold retained 14,870 pairs and 29,740 directed rules.
- Chicken Biryani 2 and Beef Kebab 2 co-occurred in 72,700 baskets with
  support 0.2197 and lift 4.111. Association is not causal bundle uplift;
  Step 18 recommendations require separate suitability rules and review.

## Step 18 - Bundle and cross-sell recommendation candidates (2026-09-26)

- Planned SRS page 15's four recommendation forms as review-only candidates,
  keeping Step 17 rule evidence and Step 9 profitability at the same cutoff.
  Rebuilt local complete-basket counts instead of applying global association
  blindly to every restaurant. Global/local basket, item and pair totals
  reconcile, including each retained pair's sum across locations.
- Screened each local pair for at least ten local co-purchases, lift >=1.05,
  positive observed direct contribution, five sold portions, positive price
  and catalog availability on both sides. Directed add-ons require local
  confidence >=0.08. Higher-priced co-purchased add-ons are not presented as
  substitution recommendations. Ranked/capped review output per location.
- A fixture test passed for directional pricing, combo evidence, and
  negative-margin/unavailable suppression. Small and verified full runs
  passed. Full output has 1,403 candidates across 24 locations: 240
  frequently paired, 24 combo meal, 940 cross-sell and 199 upsell add-ons.
- The report records first-failing guard counts, source hashes, evidence
  examples and `review_only_live_stock_and_offer_economics_unverified`.
  No offer or discount was published. Human merchandising/stock review is
  required before live use.

## Step 19 - Peak-period analysis (2026-09-26)

- Planned all SRS page 15 peak dimensions at one complete-order grain with
  restaurant-local time and full calendar-day exposure. Explicit Third-party
  Delivery is compared with Dine-in; Website/App remains separate because
  fulfillment is unknown.
- Built overall/location hour, weekday, weekend, year-month, season and
  calendar-date metrics plus channel-hour/weekend cuts and month-over-month
  daily-rate trends. All 16 metric grains conserve eligible order count and
  accepted revenue. Source baskets reconcile with Step 17.
- A timezone/cutoff/zero-exposure fixture exposed a null weekend numerator
  in one channel's ratio; corrected before the verified full run. Small and
  full runs passed. Full data has 330,922 eligible orders across 546 days;
  overall peak is 20:00 local and Sunday. Weekend rate is 1.486 times the
  weekday rate.
- June 2026's 1,268.40 orders/day strongly exceeds May's 553.35/day and
  influences the summer peak. These descriptive patterns are not staffing
  instructions or stable seasonal forecasts. Human review remains pending.

## Step 20 - Configurable demand forecasting (2026-09-26)

- Planned one-to-three month direct forecasts from the independent Python
  demand foundation rather than recursively inventing future observations.
  Rebuilt origin features from Step 5 clean records and checked prior-month
  feature/label parity with Step 13; historical direct-horizon targets were
  split by target month to avoid overlap across train/validation/test.
- Per horizon, fitted Extra Trees with train-only preprocessing, selected
  against a recent-demand baseline on validation, examined held-out test,
  then refit the selected specification on all now-observed labels solely
  for future inference. Outputs cover item/location and additive item,
  category, category/location and location grains.
- Two focused Step 20 tests and three Step 13 tests passed. Small, full and
  small August–September selection runs passed. Full July origin has 4,320
  known pairs; 4,295 June snapshot rows match the earlier pipeline. Full
  July–September output has 12,960 rows and reconciled rollups.
- Full selected test MAE by horizon: 8.785, 9.081 and 9.386 portions.
  July/August/September forecast totals are 133,225.32/143,987.80/
  129,348.88 accepted portions. June actual quantity was 332,920, so the
  persistence of its spike is a major uncertainty. Forecasts remain
  review-only pending Steps 21–22 and human approval.

## 2026-09-27 - Submission documentation foundation

- Read SRS section 1.10 and prepared nine English source documents under
  `documentation/submission/`: register, project report, diagram source,
  requirements matrix, evaluator guide, test evidence, dual comparison,
  video storyboard and a team contribution/review template.
- Mapped all 66 functional and five non-functional requirements. Explicitly
  recorded partial/unverified job monitoring, audit, model identity,
  deployment, hidden-data and scale acceptance work.
- Verified selected model metrics against saved JSON reports and captured an
  11-file SHA-256 source manifest. Preserved actual console output from fresh
  runs: 86 Django, 60 Python pipeline and 11 generator tests passed.
- Checked local Markdown links in all nine documents. No model retraining,
  publication, recording, human sign-off or deployment was performed.
- Corrected the root README's stale claim that clean data was not imported.
- Evidence clarification for the historical Step 20 entry above: 332,920 is
  the March-June held-out actual total, not June alone. Step 22's horizon-1
  month breakdown gives June actual quantity as 142,995 portions. The June
  spike remains a limitation; the earlier numerical label should not be reused.
- Remaining preparation includes the consolidated business report, sample/
  artifact bundle, final rendered diagrams/report, blog, presentation, MP4,
  public access instructions and real contributor/reviewer information.
