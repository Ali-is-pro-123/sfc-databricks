# DineIQ Analytics - Project Report

Version: working draft, 27 September 2026. Authors and human reviewers: pending.
Source requirement: SRS section 1.10.1. This report describes the implementation
and saved evidence currently available, including known gaps.

## 1. Purpose, problem and business necessity

Restaurant managers must balance sales, contribution, customer behavior,
preparation and waste across locations. Sales volume alone can hide loss-making
dishes, and a promotion can increase orders while reducing contribution.
Aggregating all locations can also hide a dish that succeeds in one branch and
fails in another. DineIQ brings these signals together so a reviewer can inspect
the evidence behind menu, customer, forecasting and inventory-related decisions.

This document connects business requirements to the application's design,
analytical methods, tests and limitations. It is intended for evaluators,
developers and team members preparing demonstrations or maintaining the system.

## 2. Proposed solution and scope

DineIQ uses a Django web application, PostgreSQL domain storage, Spark ingestion
and processing, and an independently constructed Python demand pipeline.
Authenticated users inspect scoped dashboards, evidence-based recommendations,
bounded what-if estimates, offline HTML reports and CSV exports.

The implemented analytical scope includes menu economics and classification,
RFM and customer segments, baskets, peak periods, demand forecasts, wastage,
pricing, promotions, ratings, anomalies, location/channel comparisons and churn
review signals. Recommendations require human interpretation. Live POS
integration, payments and delivery-platform integration are outside the SRS
scope. DineIQ does not currently automate purchasing, repricing or outreach.

## 3. Assumptions and constraints

- Data is synthetic, with controlled patterns and quality defects. Results are
  demonstrations of the method and are not observed business outcomes.
- The full generated period is January 2025 through June 2026. Most historical
  web evidence uses an exclusive 1 July 2026 cutoff. A 90-day card is not a
  lifetime total. Saved July-September forecasts remain estimates without later actuals.
- Currency is PKR; quantities are portions. Direct contribution excludes
  overhead and delivery-platform fees and must not be labelled net profit.
- Missing or quarantined records affect coverage. Complete-basket analyses
  exclude known partial baskets, so their counts differ from raw database totals.
- Windows runs Django and the Python pipeline through uv. Java/Spark,
  PostgreSQL and Redis run in Linux Docker containers. Tailwind uses a CDN.
- Redis is provisioned. An application job queue/monitoring service is not
  established by the mere presence of that container.

## 4. Requirements and implementation status

The [traceability matrix](requirements_traceability.md) covers all 66 functional
requirements and the five non-functional requirements. Core analytics and web
surfaces have implementations and evidence. Persistent result/metadata storage,
application-wide audit events, uniform prediction model identifiers and an
in-application Spark job monitor still need completion or explicit verification.

The latest broad QA passed Django and Python tests and confirmed populated
pages. That does not establish five-million-line scalability, 99% uptime, or the
SRS prediction response-time target. The SRS performance sentence refers to
"claim details", which does not match the restaurant domain; its applicable
prediction workflow should be clarified during acceptance review.

## 5. System and Big Data architecture

The [design diagrams](design_diagrams.md) show deployment, data flow, entity
relationships, user interactions and the analytical lifecycle. Django runs on
the host and connects to PostgreSQL. The Spark master and worker share mounted
project folders; Spark jobs read raw data and produce partitioned Parquet and
reports. Python jobs use their own transformations and model training. Django
analytical services read saved, validated evidence, using DuckDB where relevant.

This separates batch processing from web rendering. A dashboard request does
not retrain the models. The application does not yet provide a complete
asynchronous processing-job control plane. PostgreSQL domain edits do not
automatically regenerate analytical snapshots; results must retain their cutoff.

### Module responsibilities

| Module | Responsibility |
| --- | --- |
| `data_generator/` | Seeded synthetic generation, corruption ledger, independent reference validation |
| `spark_jobs/`, `spark_sql/` | Ingestion, quality, joins, features, EDA, menu classification and Spark models |
| `python_pipeline/` | Independent demand model, comparison and downstream intelligence stages |
| `dine_iq/apps/accounts/` | Authentication, business roles and account administration |
| `dine_iq/apps/restaurants/` | Domain records, location scope, analytical services, scenarios, reports and exports |
| `templates/`, `static/` | Tailwind templates, grouped navigation, responsive drawer and static assets |
| `processed_data/`, `parquet_data/`, `models/` | Generated evidence, analytical tables and fitted model artifacts |

## 6. Database and data dictionary

The authoritative schema is in Django models and migrations. The
[data dictionary](../data_dictionary.md) records types, units, relationships and
validation boundaries. Business entities have numeric database IDs and stable
source codes; application users are separate from pseudonymous customers.

Orders reference a location, channel and optional customer/promotion. Lines
retain historical price, cost, quantity, discount and optional campaign. Pricing
history belongs to an item/location/effective-time combination. Ratings link to
purchased order lines. Inventory and wastage are item/location observations.
Promotion membership uses a bridge table. LocationAccess grants scope to
restaurant and regional managers; administrators and analysts can see all
locations under the current policy.

Database constraints enforce row-level bounds and uniqueness. Model validation
also checks cross-record rules, such as campaign timing. Bulk imports rely on
validated sources and their explicit checks; Django model validation is not
automatically invoked for every bulk-written record.

### Verified clean import

The `import_clean_dataset` command loads accepted Step 5 Parquet into PostgreSQL
without modifying accounts. It checks the passed quality report, success markers,
source counts, unique keys and relationship joins. Deterministic IDs permit
resumption of complete tables. Each table imports in its own transaction. The
rerun guard compares counts/keys and promotion links, not every mutable field.

| Entity | Accepted/imported rows |
| --- | ---: |
| Restaurants | 24 |
| Categories / menu items | 12 / 180 |
| Channels / customers | 4 / 60,000 |
| Promotions / promotion-item links | 40 / 160 |
| Pricing history | 12,912 |
| Orders / order lines | 348,295 / 1,035,861 |
| Ratings | 117,184 |
| Inventory / wastage | 2,346,336 / 74,244 |

These total 3,995,252 accepted records across 13 source tables. Analytical
eligibility filters can produce smaller populations.

## 7. Dataset generation and quality methodology

The seeded generator supplies small, medium and full profiles. The verified full
reference contains 350,000 orders, 1,050,000 order lines, 60,000 customers,
120,000 ratings and 75,000 wastage records over 18 months. Raw duplicates increase
the raw order and line counts. Exactly 16,065 injected defects are recorded in
the corruption ledger; this is not the same as the later quarantined row count.

Demand varies with time, location, customer preferences, promotions and selected
item relationships. Difficult scenarios include high-volume losses, low-volume
high-margin items, location differences and unusual demand. Prices and discounts
use integer paisa during generation to avoid ambiguous half-cent rounding.

The generator's clean reference is a validation oracle, not a training shortcut.
An independent disk-backed verifier checks keys, accounting, campaign eligibility,
ratings, inventory and raw corruption. Generation scenario labels are excluded
from model features and targets. See [Step 4](../step_04_generation.md).

Spark ingests the raw layer using explicit schemas. Quality rules inspect
malformed/missing fields, duplicate keys, invalid numbers/dates/units, unknown
references and impossible business relationships. Rejected rows retain original
content and reasons in quarantine. A rejected parent can also reject child rows.
The full Spark quality report records 3,995,252 accepted and 21,796 quarantined
rows; accepted plus quarantine must reconcile to input. Multiple reasons can
apply to one row. See [Step 5](../step_05_spark.md).

## 8. Spark processing, SQL and feature engineering

Transaction Parquet is partitioned by month; small dimensions are unpartitioned.
Spark SQL creates integrated order-line, order-coverage and daily item/location
facts. Measures are aggregated at their proper grain before joining so ratings
or waste records cannot multiply revenue. Source totals and read-back counts
are checked. Saved reports identify application IDs, source hashes and run times
where available; these are batch evidence, not a live Django job monitor.

Features use historical windows ending before each cutoff: demand, order count,
revenue, contribution, ratings, waste, observed sales days and category/location
context. Train-only preprocessing and chronological splits prevent later
information from entering earlier predictions. See Steps 6-9 and 12-13.

## 9. Analytical methods

### Menu economics and classification

Revenue equals quantity times historical price minus discount. Direct cost uses
historical unit cost; direct contribution is revenue minus direct cost. Waste
cost is separately labelled to avoid double counting. Category-peer ranks combine
sales velocity/order frequency and contribution margin/per-portion contribution.
Supporting rating, repeat, waste, promotion and trend evidence informs the four
classes: Profit Driver, Volume Driver, Hidden Opportunity and Low Performer.
Negative contribution cannot become a Profit Driver merely through high volume.
Sparse/new-item evidence is marked provisional. These are business-rule classes,
not a fitted classification model or independent ground truth (Steps 9-11).

### Customers, RFM, baskets and peak periods

Eligible complete baskets support behavioral segmentation and RFM scoring. The
full RFM output covers 60,000 customers; anonymous, cancelled and partial orders
are handled explicitly. Recency and windowed frequency/spend are cutoff-aware.
Market-basket analysis uses item presence per order, with support, confidence
and lift on disclosed denominators. The verified full run has 330,922 eligible
baskets. Co-purchase patterns can suggest review candidates but do not prove
incremental sales from bundling. Local-time peak analysis normalizes calendar
exposure and keeps Website/App separate when fulfillment is unknown (Steps 15-19).

### Forecasts and wastage

Forecasts estimate accepted sold portions at item/location/month grain and roll
up additively to item, category and location totals. Direct horizons cover one
to three future months. Temporal audits, validation-only selection, held-out
metrics and separate operational refits are retained (Steps 20-22).

Historical wastage measures quantity, cost and outflow share from accepted
records. The risk model predicts at least five accepted wasted portions next
month, using prior history. Its held-out ROC-AUC is about 0.547 and average
precision about 0.265: discrimination is weak. July scores cover 4,296 pairs;
24 short-history pairs abstain. Use the verified Step 24 output only (Steps 23-24).

### Prices, promotions, ratings and anomalies

Price transitions compare exposure-adjusted changes and category/location peers;
the result is a descriptive response index, not causal elasticity. Evidence
screens produce 205 high, 65 moderate and 621 low local sensitivity classes,
plus mixed/insufficient cases. All 180 item-wide results abstain because none
meets the required location coverage (Steps 25-26).

Promotion analysis separates eligible discounted lines from other basket items.
Potential traps flag conflicting sales/contribution signals rather than proving
campaign causality. Ratings are linked to purchased lines; anomaly checks use
historical comparisons and coverage thresholds. Sales anomalies, slow movers,
location/channel comparisons and churn risk remain review signals (Steps 27-36).

### Recommendations and simulations

The evidence engine screens upstream signals and retains source steps, subject,
scope and reasons. Step 37 contains 1,319 candidates across menu opportunity,
preparation, pricing, bundles, Low Performer review, customer segments,
promotions and anomaly investigation. Priorities refine review order; counts
are not projected benefits. No stock-increase candidate is emitted without a
validated upcoming-peak demand signal (Steps 37-39).

What-if tools use bounded user assumptions for price, discounts, promotion,
removal, preparation, demand and wastage changes. Results show baseline,
simulated value, change, units and assumptions. Demand responses supplied by
the user are not estimated causal elasticity (Steps 40-41).

## 10. Model design, comparison and evaluation

Spark compares linear regression, decision tree and random forest. Python
independently rebuilds the supervised data from Step 5 clean sources and compares
Ridge and Extra Trees. Python does not train on Spark predictions. Both use
the same prediction task and compatible chronological boundaries.

| Held-out next-month demand measure | Spark linear regression | Python Extra Trees | Recent-demand baseline |
| --- | ---: | ---: | ---: |
| Records | 17,180 | 17,180 | 17,180 |
| MAE, portions | 9.043 | 8.785 | 9.422 |
| RMSE, portions | 41.380 | 41.163 | 41.158 |
| WAPE | 46.67% | 45.34% | 48.62% |

Values come from saved Step 12/13 and verified Step 14 reports. MAE improves,
but RMSE does not beat the baseline. June's demand shift is a material weakness.
The separate direct-horizon forecasts improve held-out MAE by approximately
6.76%, 5.65% and 4.61% for horizons 1-3; they remain review-only.

The [dual-pipeline report](dual_pipeline_report.md) covers 17,180 unseen records,
exceeding the SRS minimum of 100. Under the disclosed tolerance, agreement is
88.70%; it is not accuracy. Regression confidence probabilities are unsupported,
so no fabricated confidence values or classification accuracy are reported.
The SRS accuracy/F1 targets are not demonstrated by these regression metrics.

## 11. Interface and reporting

Role-scoped executive, menu, customer, wastage, forecast and dual-pipeline pages
consume saved evidence. Search supports validated filters. Twelve HTML report
families and six CSV datasets provide offline access; CSV text is escaped against
spreadsheet-formula interpretation. Export queries reapply access scope and
include all matching rows rather than only the displayed preview. The shared
navigation groups modules in a desktop sidebar and a keyboard-accessible mobile
drawer. The Django administration surface retains its separate management layout.

## 12. Testing, security and privacy

See [test evidence](test_evidence.md) for commands, results and scope. Unit and
integration tests cover data invariants, model boundaries, account permissions,
scoped outputs and invalid requests. Historical Spark fixture/run evidence is
separate from the freshly collected local Python and Django results. Hidden-data,
five-million-line and uptime acceptance tests remain open.

Django handles password hashing, sessions and CSRF. Business roles and location
grants are checked server-side. Customer codes are pseudonymous; application
exports avoid customer identity fields. Secrets reside in ignored local `.env`
configuration. Public deployment requires reviewed HTTPS/cookie/DEBUG settings,
strong evaluator credentials and an operational access policy. The current
development configuration produced five deployment warnings during QA.
AI assistance and human review obligations are disclosed in `AI_USAGE.md`.

## 13. Limitations and future work

1. Complete or verify audit trail, model identity propagation, result metadata
   persistence, and user-visible Spark processing status against FR61-65.
2. Validate new/hidden data through fresh output paths and explicit downstream
   configuration; the fixed demonstration snapshot is not an automatic refresh service.
3. Improve forecast response to demand shifts and wastage discrimination using
   additional evidence, without tuning on the held-out test period.
4. Benchmark the five-million-line architecture and a defined prediction response
   workflow. Measure memory, runtime and concurrency rather than inferring scale.
5. Complete release packaging, diagrams in the final document, business report,
   presentation, published blog, MP4 demonstration and human review records.

Detailed methods remain in the linked Step 2-50 documents. Future work listed
here is not evidence that the corresponding SRS requirement has already passed.
