# Independent Spark/Python demand comparison

Prepared 27 September 2026 from existing verified artifacts. This documentation
pass did not retrain either model. SRS section 1.10.7 requires at least 100 unseen
records; the verified comparison covers 17,180 unique held-out records.

## Task, independence and population

Both pipelines predict next-calendar-month accepted sold portions for a known
restaurant/menu-item pair. Training targets cover May-December 2025, validation
January-February 2026, and held-out targets March-June 2026. Spark selects linear
regression from three MLlib candidates. Python selects Extra Trees after building
its own features from the Step 5 accepted source tables. Python does not consume
the Spark model, feature snapshot or predictions to produce its result.

The shared quality-cleaned source and task definition are intentional. This is
independent feature construction and fitting, not two separate raw-cleaning
pipelines. All 60,105 supervised keys, labels, splits and compared historical
features reconcile before the held-out predictions are compared.

## Record-level contract and saved files

- Summary: `processed_data/step14-full-verified/comparison_report.json`.
- Complete row evidence: `processed_data/step14-full-verified/record_comparison.csv`.
- Model reports: `processed_data/step12-full/demand_model_report.json` and
  `processed_data/step13-full/python_demand_report.json`.

The CSV contains record/entity identity, actual value, Spark result, Python result,
signed/absolute difference, tolerance, match status, absolute errors and diagnostic
disagreement explanation. A match requires absolute difference no greater than
`max(2 portions, 20% of actual quantity)`. Exact equality is reported separately.
The regressors do not emit calibrated class probabilities; confidence is not
invented. The complete CSV is a generated local artifact and needs distribution
with the final evidence bundle.

## Overall held-out result

| Measure | Value |
| --- | ---: |
| Paired records | 17,180 |
| Within tolerance | 15,239 |
| Outside tolerance | 1,941 |
| Tolerance-based agreement | 88.701979% |
| Exactly equal predictions | 0 |
| Mean absolute prediction difference | 1.568837 portions |
| Spark MAE / RMSE | 9.042945 / 41.379900 portions |
| Python MAE / RMSE | 8.785365 / 41.162550 portions |
| Baseline MAE / RMSE | 9.422072 / 41.157837 portions |

Agreement is not accuracy. Both models improve aggregate MAE over the same
baseline but slightly worsen RMSE. This prevents a claim of uniform superiority.

## Monthly behavior

| Target month | Records | Matched | Agreement | Spark MAE | Python MAE |
| --- | ---: | ---: | ---: | ---: | ---: |
| March 2026 | 4,295 | 3,839 | 89.3830% | 4.0369 | 3.8204 |
| April 2026 | 4,295 | 3,855 | 89.7555% | 3.5730 | 3.3384 |
| May 2026 | 4,295 | 3,886 | 90.4773% | 4.0411 | 3.9097 |
| June 2026 | 4,295 | 3,659 | 85.1921% | 24.5207 | 24.0730 |

June's demand shift increases both models' errors. Aggregate agreement should
not hide that deterioration.

## Example of a major disagreement

Record `R0000007|M0000009|2026-06-01` has actual demand 176 portions. Spark predicts
91.5665 and Python 138.3818. Their difference is 46.8153, exceeding the 35.2-portion
tolerance; the status is mismatch. The recent-demand baseline is 149. The report
labels this `high_volume_model_sensitivity`. This is a diagnostic description of
different fitted responses, not proof of a causal mechanism.

The 1,941 mismatches comprise 1,432 general model-sensitivity cases, 464 coincident
demand-shift cases, 32 sparse-history cases and 13 high-volume cases. Do not sum
these into business-loss estimates or treat the explanation codes as causal labels.

## Reproduction and decision

Follow [Step 14](../step_14_dual_verification.md) with fresh output paths after
verifying the Step 12/13 artifacts. Checks reject duplicate/missing keys, different
actuals, divergent populations and invalid predictions. The passing comparison
supports lineage and consistency of the experiment; deployment remains subject
to forecast quality, new-data validation and human review.
