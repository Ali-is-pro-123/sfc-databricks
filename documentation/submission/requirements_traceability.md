# SRS requirements traceability

Baseline: 27 September 2026. Functional IDs correspond to the ordered Roman
numerals in SRS section 1.6 (PDF pages 28-34). The references below identify
implementation/evidence, not an independent certification of every behavior.
Stage documents are under `documentation/`; implementation paths are relative
to the repository root. Short `apps/` and `restaurants/` code references are
within `dine_iq/` and `dine_iq/apps/`, respectively.

**Implemented:** code and local evidence exist. **Partial:** a material part is
absent or not verified. **Unverified:** acceptance evidence has not been produced.
Human review and the final evaluator test remain required for every row.

| ID | Requirement | Status | Evidence / remaining boundary |
| --- | --- | --- | --- |
| FR01 | Registration and authentication | Implemented | `apps/accounts`; administrator-managed registration, no public signup |
| FR02 | Role-based access | Implemented | Account permissions, `restaurants/access.py`, account/domain tests |
| FR03 | Location management | Implemented | Restaurant model, management site, location pages |
| FR04 | Menu management | Implemented | Category/item models and dated prices |
| FR05 | Pricing history | Implemented | PricingHistory model, Step 25 |
| FR06 | Customer data | Implemented | Pseudonymous Customer model, Steps 15-16 |
| FR07 | Orders and lines | Implemented | Order/OrderItem models, clean importer |
| FR08 | Promotions | Implemented | Promotion model and item bridge; Step 27 |
| FR09 | Ratings | Implemented | Purchase-line rating model, Step 29 |
| FR10 | Inventory | Implemented | Daily Inventory model and constraints |
| FR11 | Wastage records | Implemented | Wastage model, quantity/cost/date/reason fields |
| FR12 | Spark ingestion | Implemented | `spark_jobs/ingest.py`, Step 5 full report |
| FR13 | Schema validation | Implemented | Explicit schemas and Step 5 fixtures |
| FR14 | Quality analysis | Implemented | Step 5 quality reasons and quarantine |
| FR15 | Cleaning | Implemented | Documented acceptance/quarantine policies |
| FR16 | Spark SQL | Implemented | `spark_sql/`, Steps 6-12 |
| FR17 | Partitioning | Implemented | Monthly transaction Parquet partitions |
| FR18 | Parquet storage | Implemented | `parquet_data/step05-full/` and downstream outputs |
| FR19 | Feature engineering | Implemented | Steps 7, 12, 13, 20; temporal fixtures |
| FR20 | Profitability | Implemented | Step 9; direct contribution excludes overhead |
| FR21 | Menu classes | Implemented | Step 10; four rule-based classes with provisional flags |
| FR22 | Peak periods | Implemented | Step 19 verified full output; limited seasonal history |
| FR23 | Customer segments | Implemented | Step 15 descriptive rules |
| FR24 | RFM | Implemented | Step 16; explicit windows and score thresholds |
| FR25 | Basket discovery | Implemented | Step 17 complete-basket associations |
| FR26 | Support/confidence/lift | Implemented | Step 17 metrics and fixtures |
| FR27 | Bundles/cross-selling | Implemented | Step 18 screened review candidates |
| FR28 | Demand forecasting | Implemented | Steps 12, 13, 20 |
| FR29 | Forecast evaluation | Implemented | Steps 21-22; held-out errors and baseline comparison |
| FR30 | Waste analysis | Implemented | Step 23 accepted output |
| FR31 | Wastage prediction | Partial | Step 24 model exists; weak discrimination, operational quality not approved |
| FR32 | Price sensitivity | Implemented | Step 26 local classes; all item-wide classes abstain |
| FR33 | Promotion effectiveness | Implemented | Step 27 descriptive attribution; no causal lift claim |
| FR34 | Promotion traps | Implemented | Verified Step 28 flags, review only |
| FR35 | Rating/performance relationships | Implemented | Step 29 coverage-aware analysis |
| FR36 | Rating anomalies | Implemented | Step 30 historical anomaly screens |
| FR37 | Sales anomalies | Implemented | Step 31 flags and baselines |
| FR38 | Location comparison | Implemented | Step 33 and executive dashboard |
| FR39 | Local menu intelligence | Implemented | Step 34 location-specific comparisons |
| FR40 | Channel comparisons | Implemented | Verified Step 35; Website/App remains separate |
| FR41 | Customer churn risk | Implemented | Step 36 declining-engagement review signals |
| FR42 | At least three Spark models | Implemented | Step 12 linear regression, decision tree, random forest |
| FR43 | Independent Python models | Implemented | Step 13 Ridge/Extra Trees; independent features |
| FR44 | Dual prediction comparison | Implemented | Verified Step 14, 17,180 paired unseen rows |
| FR45 | Agreement/disagreement | Implemented | Step 14 tolerance, reason codes and error metrics |
| FR46 | Model evaluation | Implemented | Regression and risk metrics; no fabricated classification accuracy |
| FR47 | Recommendation engine | Implemented | Steps 37-39, evidence and review priority |
| FR48 | Menu optimization advice | Implemented | Screened opportunity/price/bundle/redesign reviews |
| FR49 | Inventory recommendations | Partial | Preparation reviews and forecasts exist; future peak-stock advice intentionally abstains |
| FR50 | Customer targeting | Implemented | Aggregate, review-only segment strategy |
| FR51 | What-if | Implemented | Steps 40-41 bounded simulations, no operational mutation |
| FR52 | Executive dashboard | Implemented | Step 42, `/dashboard/` |
| FR53 | Menu dashboard | Implemented | Step 43, `/dashboard/menu/` |
| FR54 | Customer dashboard | Implemented | Step 44, `/dashboard/customers/` |
| FR55 | Wastage dashboard | Implemented | Step 45 summaries; detailed source records remain in management |
| FR56 | Forecast dashboard | Implemented | Step 46 historical/future labels and scope |
| FR57 | Dual dashboard | Implemented | Step 47 scoped paired results |
| FR58 | Search/filtering | Implemented | Step 48 validation, fixed context caveats |
| FR59 | Downloadable reports | Implemented | Step 49, twelve offline HTML report families |
| FR60 | Data export | Implemented | Step 50, six CSV datasets, formula escaping and permissions |
| FR61 | Store config/metadata/users/results/recommendations | Partial | Users/domain in PostgreSQL, analytical outputs on disk; complete database-backed metadata/results contract unverified |
| FR62 | Prediction model version | Partial | Batch hashes/model paths exist; uniform immutable version IDs on all predictions unverified |
| FR63 | Audit trail | Partial | Batch reports and Django admin logging exist; unified job/prediction/export/admin event trail incomplete |
| FR64 | Understandable failures | Partial | Several verified-source error paths exist; full database/Spark/model failure acceptance coverage unverified |
| FR65 | Spark job status in application | Partial | Spark native UI and report statuses exist; Django monitoring page/control plane absent |
| FR66 | Responsive interface | Partial | Responsive templates/sidebar/drawer exist; full mobile/cross-browser acceptance matrix pending |

## Non-functional requirements

| ID | SRS acceptance expectation | Evidence and status |
| --- | --- | --- |
| NFR01 | Both-model prediction workflow within five seconds under normal load | Unverified. Saved dashboard reads are not a benchmark of dual inference. Workload, ambiguity, and acceptance test are documented in the [NFR plan](../nfr_acceptance_plan.md). |
| NFR02 | At least five million order lines without redesign | Unverified. Current reference has 1.05 million lines; Spark/Parquet architecture alone is not a load test. See the [NFR plan](../nfr_acceptance_plan.md). |
| NFR03 | Usable for four business roles | Partial. Role tests and local browser QA pass; formal task-based user acceptance remains. |
| NFR04 | Classification accuracy >=85% or macro-F1 >=0.80 where appropriate; forecast beats baseline | Partial. Demand MAE improves, RMSE does not; menu rules are not an ML classification evaluation. Wastage risk is weak. |
| NFR05 | 99% uptime during required evaluation periods | Unverified. No defined measurement interval or uptime record. |

## Integrity and release acceptance

- Inspect the actual commit history; the earlier QA found no commits. Do not
  backdate activity or create misleading contribution claims.
- Keep the independent Spark/Python generation path demonstrable; exclude
  generator scenario labels and clean-reference shortcuts.
- Run unseen schema-compatible data in new directories, including unknown keys,
  new locations, missing fields and extreme values. Fixtures do not substitute
  for the evaluator's hidden dataset.
- Complete human explanation/review of AI-assisted code and documents. Current
  AI declaration entries with pending reviewers are not signed off.
- Follow the [deliverable register](README.md) for recordings, blog, presentation,
  public URLs, dataset distribution and final document formatting.
