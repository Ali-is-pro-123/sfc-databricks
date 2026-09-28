# Non-functional requirements: audit and acceptance plan

Audit date: 28 September 2026. Source: SRS section 1.7, read alongside sections 1.6 and 1.8. This is an evidence audit and test plan, not a claim that the planned benchmarks have passed.

## Current status

| SRS requirement | Current evidence | Status / missing proof |
| --- | --- | --- |
| NFR01 - Both-model prediction within five seconds in normal conditions | Independent Spark and Python demand pipelines and saved paired predictions exist. `/dashboard/dual/` reads verified outputs. | **Unverified.** A dashboard response is not new inference by both models. No defined interactive dual-inference transaction, workload, or latency run is recorded. |
| NFR02 - At least five million order-line records without redesign | The verified full reference has 1,050,000 clean order items (1,051,509 raw rows). Spark ingestion and partitioned Parquet are implemented. | **Unverified.** The reference is below five million and architecture alone is not a capacity test. Peak memory for the full generator run was not captured. |
| NFR03 - Usable for four roles | Login, role grants, responsive navigation, and role-scoped dashboards have automated and local browser checks. | **Partial.** No structured task-completion study, accessibility audit, or cross-browser/mobile-device matrix is signed off. |
| NFR04 - Classification accuracy or macro-F1 target where appropriate; forecast improves over a simple baseline | The selected Spark/Python next-month demand regressors improve held-out MAE versus the recent-demand baseline (9.043/8.785 versus 9.422 portions). Direct-horizon forecasts improve held-out MAE by 6.76%, 5.65%, and 4.61%. The held-out wastage-risk classifier has average precision 0.265 and ROC-AUC 0.547 over 17,184 rows. | **Partial.** Demand RMSE does not improve over baseline, June is a large miss, and wastage discrimination is modest. Menu classes are rules, not a tested ML classifier; regression agreement is not classification accuracy. The wastage classifier has no held-out accuracy/macro-F1 acceptance result, so the SRS classification target is not demonstrated. |
| NFR05 - At least 99% uptime during the required evaluation period | A local development server and Docker services can run. | **Unverified.** Neither the evaluation interval nor a health-check/uptime record has been agreed and captured. |

Evidence: `documentation/step_04_generation.md`, `documentation/step_12_spark_models.md`, `documentation/step_22_forecast_accuracy.md`, `processed_data/step24-verified-full/wastage_risk_report.json`, `documentation/submission/project_report.md`, and `documentation/submission/test_evidence.md`. Existing test-suite totals are functional evidence, not latency, load, or uptime results.

## NFR01 - Dual-prediction response-time test

1. **Clarify the transaction before measuring.** Agree with the evaluator what input is submitted, which two models must run, whether model loading/Spark startup is inside the five seconds, and what constitutes a successful response. The current web page only displays precomputed paired results; it must not be substituted for inference.
2. Define a reproducible normal environment: machine/CPU/RAM, Docker worker cores and memory, model versions, dataset snapshot, warm/cold state, and concurrency. Record the start/end boundary from accepted request to both validated model results returned.
3. Once a real dual-inference path exists, use a representative set of eligible and edge-case item/location inputs. Run a warm-up separately, then at least 100 measured requests at the agreed normal concurrency. Record each model duration, total duration, failures, p50, p95, maximum, and any timeout. Repeat after a service restart to expose cold-start cost.
4. Do not call the SRS passed unless successful requests return **both independent predictions within five seconds** under the agreed conditions. Report any misses instead of hiding them behind a mean. Preserve the command, machine configuration, raw timings, model identifiers, and summary in a dated evidence folder.

If the intended requirement is a batch Spark job rather than request-time inference, obtain written clarification; a multi-million-row batch job cannot be assumed to share the five-second response boundary.

## NFR02 - Five-million-order-line scale test

1. Extend the generator with a configurable scale/profile in a separate change; its current `full` profile produces about 1.05 million clean lines. Preserve seed reproducibility, referential integrity, and all documented defect scenarios. Create new output directories; do not overwrite `raw_data/full-seed42` or verified reports.
2. Generate **at least 5,000,000 clean order-line records** plus proportionate orders, customers, locations, dates, and related records. Independently validate row counts, keys, duplicate handling, file manifests, and quality outcomes before processing.
3. Run the normal Spark ingestion, schema checks, cleaning, integration, feature engineering, and the required analytical/model stages against that isolated dataset. Record wall time, peak memory, CPU, disk usage, partition sizes, failure/retry behavior, and output row-count reconciliation on the documented Docker hardware profile.
4. Pass only if the required pipeline finishes correctly without a structural redesign. Resource tuning, partition sizing, or adding workers can be documented; code paths that only work for the 1.05-million reference, hard-coded counts, or manual result substitutions fail the intent.
5. Retain the generated manifest, quality reports, logs, monitoring screenshots/metrics, hardware specification, exact commands, and a clean rerun result. Capacity evidence must be reproducible by a teammate.

## Remaining acceptance checks

- **NFR03:** Have a representative user for each role complete login, navigation, scoped analytics, filters, reports, and sign-out tasks. Record completion, errors, keyboard use, responsive layouts, and any accessibility defects.
- **NFR04:** Keep chronological held-out splits and baseline comparisons. Report MAE/RMSE/WAPE and failure slices for forecasts; for every genuine classifier, report confusion matrix, accuracy, macro-F1, support, and class balance. Do not present rule-based menu labels or Spark/Python agreement as accuracy.
- **NFR05:** Agree on the evaluation window and service boundary, add a health check, and sample it continuously. Calculate `available_minutes / scheduled_minutes * 100`; document allowed maintenance and every outage. A local server simply being open during a demo is not 99% uptime evidence.

## SRS wording ambiguity

NFR01 says "uploaded claim details", while the domain, dataset tables, functional requirements, and hidden evaluation data are restaurant-related. This appears to be residual wording from another specification, but the team must not silently rewrite the SRS. Record it as an unresolved clarification for the evaluator: **Does the five-second target apply to interactive restaurant prediction from newly submitted data, to a preloaded model inference call, or to another workflow?** The phrase does not by itself mandate a live restaurant-data upload page or real-time streaming. Sections 1.6 and 1.8 do require Spark ingestion and hidden-dataset robustness, which should be tested separately from NFR01 latency.
