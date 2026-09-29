# AI Tool Usage Declaration

## Submission packaging and Docker/GitHub release assistance (2026-09-29)

- **Tool:** OpenAI Codex.
- **Purpose:** Organize SRS deliverables without moving source files and prepare the Docker Hub/GitHub handoff.
- **Affected files:** `scripts/build_submission_package.ps1`, the ignored `handoff_exports/submission_package/` copy, `compose.yaml`, `README.md`, and this declaration.
- **Changes:** Copied selected source/data/model evidence into 17 SRS-aligned folders, documented pending deliverables honestly, made the Spark image selectable in Compose, and added Docker Hub and GitHub submission instructions.
- **Testing:** Verified 17 folders, copied raw-data and analytical evidence hashes, excluded local secrets/runtime files, and checked Compose configuration. Image build/push and repository push outcomes must be recorded separately after execution.
- **Human verifier:** Pending Ali Raza's independent review and sign-off. Git authorship does not itself prove review or implementation ownership.

## Documentation and submission preparation (2026-09-27)

- **Tool:** OpenAI Codex.
- **Purpose:** Read SRS documentation/deliverable requirements and prepare an
  evidence-based English submission pack.
- **Assistance:** Repository inspection, technical writing, diagram source,
  requirements mapping, evaluator instructions and test evidence collection.
- **Affected files:** `documentation/submission/`, development log, root README
  and this declaration.
- **Changes:** Consolidated the project report; added architecture, data-flow,
  ER, use-case, activity and sequence diagrams; mapped all 66 functional and five
  non-functional requirements; documented model comparison, release gaps,
  evaluator workflow, mandatory video storyboard and a team-review template.
  Corrected the README's outdated statement that clean data was not imported.
- **Testing:** Fresh automated runs passed 86 Django, 60 Python pipeline and
  11 generator tests. Their console output is saved in the submission evidence
  folder. Saved model/quality reports were inspected; no models were retrained.
- **Human verifier:** Pending actual team member name, independent review,
  corrections and sign-off. No published blog, recording, presentation, public
  repository, or final submission approval is claimed by this entry.

## Step 20 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS configurable item/category/location
  demand forecasting for selected future months.
- **Affected modules:** `python_pipeline/forecast.py`, temporal fixture,
  Step 20 documentation, README and generated forecasts/models/reports.
- **Changes:** Built cutoff-safe origin features, direct one-to-three-month
  target models, validation-only method selection, held-out metrics,
  operational refits and additive demand rollups.
- **Testing:** Five relevant tests and small/full/selected-period runs passed.
  Full output has 12,960 item/location/month forecasts with reconciled
  item/category/location totals.
- **Human verifier:** Pending formal Steps 21–22 review. June 2026's
  synthetic spike makes future operational accuracy uncertain.

## Step 19 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS peak-hour/day/weekend/month/season/
  location/channel analysis.
- **Affected modules:** `python_pipeline/peak_periods.py`, DuckDB SQL,
  timezone fixture, Step 19 documentation and generated Parquet/reports.
- **Changes:** Rebuilt one order per complete basket in local time, added
  calendar-exposure-normalized rates, channel separation and monthly trends.
- **Testing:** Fixture and small/full runs passed; all 16 output grains
  reconcile to the 330,922 eligible full-data orders and source revenue.
- **Human verifier:** Pending review. June 2026's spike and incomplete
  seasonal coverage limit operational interpretation.

## Step 18 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS-supported bundle, cross-sell, upsell
  add-on and frequent-pair recommendation candidates.
- **Affected modules:** `python_pipeline/recommendations.py`, DuckDB SQL,
  safety fixture, Step 18 documentation and generated Parquet/report files.
- **Changes:** Joined global rules with independently rebuilt local pair
  evidence and menu/profitability guards; ranked four candidate types while
  explicitly marking live stock and offer economics unverified.
- **Testing:** Safety fixture and small/full runs passed. The verified full
  output contains 1,403 review candidates across 24 locations.
- **Human verifier:** Required before any publication, discount or live
  recommendation. Association does not prove incremental sales.

## Step 17 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS market-basket item association analysis.
- **Affected modules:** `python_pipeline/market_basket.py`, DuckDB SQL,
  hand-calculated fixture test, Step 17 documentation and generated Parquet/
  report files.
- **Changes:** Built complete-order item presence and pair counts; emitted
  directed support, confidence and lift rules with source/metric audits.
- **Testing:** Fixture and small/full runs passed. Full output has 330,922
  eligible baskets, 14,870 retained pairs and 29,740 directed rules.
- **Human verifier:** Pending review. Co-purchase and high lift do not prove
  a commercially suitable or causally effective bundle.

## Step 16 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS RFM analysis for every accepted customer.
- **Affected modules:** `python_pipeline/rfm.py`, RFM DuckDB SQL, fixture test,
  Step 16 documentation, README and generated Parquet/report files.
- **Changes:** Scored point-in-time recency, 180-day visit frequency and spend
  using explicit bands and active-customer monetary quantiles; published RFM
  codes, tiers and a cross-tab with existing behavior segments.
- **Testing:** Boundary/tie test and small/full runs passed. Full read-back
  contains 60,000 unique customers and reconciles source visits/spend.
- **Human verifier:** Pending review of score thresholds and tier labels.
  Scores are descriptive, not churn or value predictions.

## Step 15 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS behavioral customer segmentation.
- **Affected modules:** `python_pipeline/customer_segments.py`, DuckDB SQL,
  fixture tests, Step 15 documentation, README and generated Parquet/report.
- **Changes:** Built cutoff-aware eligible visits and customer behavioral
  features, then assigned explainable, precedence-based segment labels.
  Cancelled, anonymous, empty and known-partial orders are audited separately.
- **Testing:** Four focused tests and small/full runs passed. Full output
  includes 60,000 customers; 330,045 visit money/order totals reconcile.
- **Human verifier:** Pending review of thresholds and segment meanings.
  Synthetic promotion-use patterns do not prove causal sensitivity.

## Step 14 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS dual-pipeline demand-result verification.
- **Affected modules:** `python_pipeline/compare_demand.py`, comparison
  fixtures, Step 14 documentation, README and generated comparison reports.
- **Changes:** Audited saved Spark/Python snapshot parity, joined record-level
  held-out predictions, classified numerical disagreements under a disclosed
  tolerance, and summarized agreement, model errors, and monthly behavior.
- **Testing:** Four comparison fixture tests, small/full comparisons, and
  saved-report metric reconciliation passed. Full output has 17,180 records
  and 88.70% tolerance-based agreement.
- **Human verifier:** Pending independent review. Diagnostic explanations
  are not causal proof; agreement does not establish forecasting accuracy.

## Step 13 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement the SRS-required independent Python
  data-science pipeline for the shared next-month demand task.
- **Affected modules:** `python_pipeline/demand.py`, independent DuckDB SQL,
  fixture tests, `pyproject.toml`, `uv.lock`, documentation and generated
  snapshots, reports, predictions and fitted model files.
- **Changes:** Rebuilt facts from Step 5 accepted clean records without using
  Spark output as training input, trained Ridge and Extra Trees, selected on
  validation, and saved record-keyed held-out predictions.
- **Testing:** Three focused tests and small/full real-data runs passed, with
  source-sales and target reconciliation and fitted-model reload checks.
- **Human verifier:** Pending independent review. Synthetic test metrics and
  close comparison with a baseline are not deployment approval.

## Step 12 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement Spark MLlib model development for one
  chronology-safe predictive task.
- **Affected modules:** `spark_jobs/train_demand.py`, fixture tests,
  `config/spark.Dockerfile`, `compose.yaml`, Step 12 documentation, generated
  supervised Parquet, held-out predictions and fitted model artifacts.
- **Changes:** Built historical monthly snapshots with future-only accepted
  demand targets, train-only encoding/scaling, three algorithms, baseline
  comparison and untouched chronological test evaluation. No Step 10 rule
  class or generator scenario label was used as a target.
- **Testing:** Three targeted Spark tests and small/full standalone training
  runs passed. Full output has 60,105 snapshots and 17,180 test predictions;
  the selected linear pipeline was saved and loaded successfully.
- **Human verifier:** Pending independent review and sign-off. Synthetic-data
  metrics do not prove live forecasting accuracy or deployment readiness.

## Step 11 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS difficult menu-case audits.
- **Affected modules:** `spark_jobs/case_audit.py`, targeted tests, Step 11
  documentation, README, and generated Parquet/reports.
- **Changes:** Ten case indicators with classification context, normalized
  weekend ordering and two-window seasonal evidence. Synthetic scenario
  labels were not used by the audit logic. The weekend threshold was tightened
  after examining a broad initial real-data screen.
- **Testing:** Three targeted Spark tests and final small/full standalone runs
  passed. Full outputs preserve 180 item and 4,320 local rows with exact
  monetary/quantity reconciliation and safety guards.
- **Human verifier:** Pending independent review and sign-off. Seasonal and
  promotion findings are descriptive, not forecasts or causal conclusions.

## Step 10 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS menu performance classification.
- **Affected modules:** `spark_jobs/classify.py`, `spark_jobs/test_classify.py`,
  Step 10 documentation, README, generated Parquet and reports.
- **Changes:** Peer-relative multi-signal business rules classify item-wide and
  item/location rows, retaining scores, flags, reasons and provisional evidence.
  Negative contribution cannot be promoted by sales volume alone.
- **Testing:** Four targeted Spark tests and small/full standalone runs passed;
  all 180 items and 4,320 item/location rows received one valid class, with
  exact quantity/monetary reconciliation.
- **Human verifier:** Pending independent review and sign-off. These classes
  are not ML predictions, ground-truth labels or validated recommendations.

## Step 9 assistance (2026-09-26)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS menu profitability analysis.
- **Affected modules:** `spark_jobs/profitability.py`, focused tests, Step 9
  documentation, README and generated Parquet/report snapshots.
- **Changes:** Combined verified 90-day item/location features with independent
  30+30-day completed-sale trends, exposure boundaries and missing-evidence
  flags. No menu performance class or recommendation was generated.
- **Testing:** Four Spark fixture tests and small/full standalone runs passed;
  full output has 4,320 rows and reconciles 90-day monetary/quantity totals.
- **Human verifier:** Pending independent review and sign-off. Contribution is
  not net profit; accepted sales and inventory coverage retain known limits.

## Step 8 assistance (2026-09-25)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS exploratory data analysis.
- **Affected modules:** `spark_jobs/eda.py`, `spark_jobs/test_eda.py`, ten
  `spark_sql/eda_*.sql` files, documentation, generated Parquet and reports.
- **Changes:** Cutoff-aware descriptive roll-ups and rankings for dishes,
  categories, locations, channels, campaigns, hours, weekdays and months,
  with source checks and financial/quantity conservation. No generator labels
  or model predictions were used.
- **Testing:** Eight targeted Spark tests and small/full standalone-cluster runs
  passed. Full run reconciled 1,182,659 portions and PKR 529,382,947.61 revenue
  across all ten output tables.
- **Human verifier:** Pending independent review and sign-off. Rankings are
  descriptive; campaign attribution is not causal and contribution is not net
  profit.

## Step 7 assistance (2026-09-25)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS analytical feature families with cutoff guards.
- **Affected modules:** `spark_jobs/features.py`, `spark_jobs/test_features.py`,
  item/customer/location feature SQL, documentation, generated snapshots/reports.
- **Changes:** Windowed money and operational features, observed ratings and prices,
  eligible-customer RFM, repeat purchases, basket coverage, local temporal features,
  zero-history retention and explicit null ratios. No generator labels were reused.
- **Testing:** 9 feature tests passed, then small/full Spark snapshots passed with
  financial/customer conservation and read-back checks. Static compilation caught
  and resolved a syntax error. Docker Desktop was restarted without data reset.
- **Human verifier:** Pending independent review and sign-off. These are descriptive
  snapshots, not fitted models or proof of forecast accuracy; chronological model
  validation and independent Python implementation remain required.

## Step 6 assistance (2026-09-25)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement SRS multi-table analytical integration.
- **Affected modules:** `spark_jobs/integrate.py`, integration tests, `spark_sql`,
  README and step documentation; generated Parquet, reports and execution logs.
- **Changes:** As-of prices, safe fact grains, local dates, order coverage,
  daily operational joins and monetary/quantity conservation checks.
- **Testing:** Small/full Spark runs and 10 integration, 8 quality, 11 generator,
  33 Django tests passed. Full integration retained 1,035,861 line facts.
- **Human verifier:** Pending independent review and sign-off.

## OpenAI Codex

- **Purpose of use:** Requirements analysis, architecture planning, implementation assistance, and test guidance.
- **Type of assistance:** Reviewed the SRS, proposed the staged architecture, and prepared the initial project foundation.
- **Files or modules affected:** Project configuration, Docker Compose configuration, environment template, repository layout, and documentation.
- **Modifications performed:** The generated suggestions are reviewed and adjusted to match the DineIQ SRS, Windows development environment, Docker services, Django, Tailwind CDN, and uv dependency management.
- **Testing completed:** Dependency resolution, Django system checks, Docker Compose validation, and service health checks are recorded in the development log.
- **Verified by:** A team member must add their name here after independently reviewing, understanding, and testing the work.

AI tools are not used to produce the final restaurant classifications,
predictions, forecasts, or recommendations. Those outputs will be generated by
the project's own Spark, Python, Data Science, and Machine Learning logic.

## Step 2 assistance (2026-09-25)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement custom accounts and authentication.
- **Affected modules:** `apps.accounts`, Django settings/URLs, initial migration,
  shared/account templates, local environment setup, README, and documentation.
- **Changes:** Added four business roles, administrator-managed registration,
  login/logout, server-side authorization, and account tests.
- **Testing:** 13 PostgreSQL-backed tests passed; Django system checks,
  migration consistency, uv lock consistency, and secret-file ignore checks passed.
- **Human verifier:** Pending independent team-member review and sign-off.

## Step 5 assistance (2026-09-25)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement independent Spark ingestion and data quality.
- **Affected modules:** `spark_jobs`, documentation, and generated Parquet/reports.
- **Changes:** Explicit schemas, raw-only cleaning, quarantine, reference checks,
  monthly partitions, inferred-schema evidence, and read-back verification.
- **Testing:** Small and full standalone Spark runs passed; 8 Spark, 11 generator,
  and 33 Django tests passed. Full output has 3,995,252 accepted records and
  21,796 quarantined records. Django checks and uv lock checks passed.
- **Human verifier:** Pending independent review. Accepted rows are not proof
  of exhaustive business reconciliation; feature and analytical integration
  are not part of this step.

## Step 4 assistance (2026-09-25)

- **Tool:** OpenAI Codex.
- **Purpose:** Implement the accepted synthetic generation plan and verification.
- **Affected modules:** `data_generator`, generator tests, restaurant promotion
  attribution field/admin/migration/tests, documentation, and generated datasets.
- **Changes:** Seeded profiles, linked generation, controlled defects, independent
  quality verification, and CSV-derived scenario checks.
- **Testing:** Full SRS-scale data passed structural/accounting/ledger checks;
  12 scenario checks and 33 Django tests passed; generator tests cover reproducibility,
  tampering, corruption isolation, and boundary failures.
- **Human verifier:** Pending independent review. Latent generation labels are
  evaluation-only and cannot be used as final analytical outputs or ML features.

## Step 3 assistance (2026-09-25)

- **Tool:** OpenAI Codex.
- **Purpose:** Plan and implement restaurant domain records and location access.
- **Affected modules:** `apps.restaurants`, its migration/tests, project settings
  and URLs, shared/location templates, README, and domain documentation.
- **Changes:** Eleven SRS entities, ordering channels, location grants,
  historical prices/costs, validated amounts, administrator management, scoped pages.
- **Testing:** 32 PostgreSQL-backed domain/account tests passed; Django checks and
  migration consistency passed. Visual browser review remains pending.
- **Human verifier:** Pending independent team-member review and sign-off.
