# Mandatory MP4 demonstration storyboard

Status: recording preparation only. No MP4 has been created or submitted.
Suggested duration: approximately 15-20 minutes; this is a planning estimate,
not an SRS duration requirement. Record real execution and explain the scope of
every result. Any time-compressed batch execution should be visibly identified.

## Before recording

- Confirm Docker services and the local web application are running.
- Prepare evaluator accounts and location grants. Keep secrets and `.env` off screen.
- Open a clean terminal at the repository root and use a new small-run output
  directory for demonstrations. Retain full-run reports for the scale evidence.
- Prepare a visible code/report pair for each method. Do not substitute generator
  scenario labels for analytical conclusions.
- Review the [project report](project_report.md), [comparison report](dual_pipeline_report.md)
  and [requirements gaps](requirements_traceability.md) before narrating.

## Recording sequence

| Segment | Show | Explanation / SRS coverage |
| --- | --- | --- |
| 1. Introduction and login | Problem statement, login and four roles | Restaurant intelligence goal; administrator-managed accounts; scope |
| 2. Dataset generation | Small seeded command, manifest/schema, full-run counts | Linked tables, reproducibility, intentional defects, anonymized customers |
| 3. Big Data ingestion | Actual Spark ingestion command and native Spark UI | Raw inputs, explicit schema, master/worker execution, batch status |
| 4. Data quality and cleaning | Accepted/quarantine output and reasons, passed quality report | Input conservation, unknown references, duplicates and rejected-parent cascades |
| 5. Spark SQL and features | One join/aggregation SQL file and cutoff feature example | Grain, avoiding row multiplication, historical windows and leakage guards |
| 6. Menu profitability/classification | Menu dashboard and source classifications | Revenue/direct cost/contribution; four classes and provisional evidence |
| 7. Contradictory business case | A verified high-volume loss-making case from Step 11 | Why volume does not imply profit; trace its numbers to accepted data |
| 8. Customer analytics | Customer dashboard, RFM and segment evidence | Recency/frequency/spend, complete-basket population, scoped access |
| 9. Baskets and peak periods | Basket report, support/confidence/lift, local-time peak report | Association versus causal uplift; exposure normalization |
| 10. Spark model | Step 12 candidates, validation selection, saved held-out prediction | Three MLlib algorithms; training/validation/test distinction |
| 11. Python model | Independent source-building code, fitted model and prediction | Separate construction; no Spark prediction reuse |
| 12. Dual comparison | Spark vs Python page and verified CSV mismatch | At least 100 unseen records; actuals, tolerance, difference, agreement and error |
| 13. Forecasts | Historical/future series and horizon evaluation | MAE/RMSE/baseline, June failure, unobserved forecast months |
| 14. Wastage | Historical waste/cost and review-only risk model | Coverage, weak discrimination, abstention for short history |
| 15. Prices and promotions | Pricing report and potential promotion trap | Local price evidence, item-wide abstention, sales/profit conflict |
| 16. Anomalies and locations | Rating/sales flags and local comparisons | Signals require investigation; a location can differ from the network |
| 17. Recommendation engine | Evidence, action scope and priority | Review candidates with source measures; no promised financial uplift |
| 18. What-if scenario | Select item/location, enter a bounded change, review impacts | Assumed response, baseline versus estimate, no automatic data change |
| 19. Dashboard and reports | Executive overview, filtered CSV, downloaded HTML report | Cutoffs, scope, offline report and export content |
| 20. Closing evidence | Test results, limitations and deliverable checklist | Honest implementation gaps; human review and next work |

Use [Step 11](../step_11_tricky_cases.md) to select an actual accepted-data case.
The generator's reference-case totals and accepted-data totals can differ after
quarantine; do not narrate one while displaying the other. For disagreement,
the comparison report provides an exact record to inspect.

## Review before delivery

- Every required topic above is visible or explicitly explained with evidence.
- Text and terminal output remain readable; sensitive values are not visible.
- Runtime, dataset scale and model metrics are correctly labelled.
- The final file is MP4 and plays from beginning to end on another device.
- The submitted link permits evaluator access and is recorded in the deliverable register.
- Actual presenters are recorded in the team contribution record. Do not claim a
  recording or public link exists until it has been produced and verified.
