# Test evidence and acceptance boundaries

Captured 27 September 2026 from the current local source, after the navigation
change. All three suites below completed with exit code 0. Console output is
retained as plain text; these results are automated evidence, not human sign-off.

| Suite | Tests | Runtime | Captured output |
| --- | ---: | ---: | --- |
| Django accounts/domain/dashboard/report/export tests | 86 | 41.188 seconds | [Django output](evidence/django_tests.txt) |
| Independent Python analytical pipeline fixtures | 60 | 15.146 seconds | [Python output](evidence/python_tests.txt) |
| Synthetic generator fixtures | 11 | 8.710 seconds | [Generator output](evidence/generator_tests.txt) |

Total: 157 tests. Test runtimes are suite runtimes on this machine, not production
latency or distributed scaling benchmarks. Commands are included in each output
file and the [evaluator guide](evaluator_guide.md).

## Coverage map

| SRS area | Existing automated/evidence source |
| --- | --- |
| Authentication, roles, grants, domain validation | `dine_iq/apps/accounts/tests.py`, `restaurants/tests.py` |
| Dashboard scope, missing evidence, filters | `restaurants/test_*dashboard.py` |
| Reports and CSV authorization/boundaries | `restaurants/test_reports.py`, `test_exports.py` |
| What-if validation and evidence | `restaurants/test_scenarios.py`, `test_recommendations.py` |
| Reproducibility, corruption, invalid references, overwrite refusal | `tests/test_generator.py` |
| Demand, forecast/time guards and paired comparison | `python_pipeline/test_demand.py`, `test_forecast.py`, `test_time_validation.py`, `test_forecast_accuracy.py`, `test_compare_demand.py` |
| Customer, basket, waste, price, promotion and anomaly logic | Additional `python_pipeline/test_*.py` files |
| Spark quality, joins, features, EDA, classifications and models | `spark_jobs/test_*.py`; historical stage logs and reports |

The Spark suite was not rerun during this documentation pass. Historical Spark
test and full-run results are described in Steps 5-12, with local logs under
`processed_data/`. Those artifacts must be packaged and reviewed separately.

## Earlier interactive QA evidence

The preceding QA session opened 11 key application pages without a server error,
confirmed populated metrics, and ran a clean-import dry-run that matched all 13
tables' counts/keys. After navigation changes, the responsive drawer opened with
keyboard input, highlighted Reports, closed with Escape and restored focus to
its trigger. These observations are browser smoke checks, not exhaustive task,
mobile-device or cross-browser acceptance tests.

## Known open acceptance work

- End-to-end hidden-dataset and clean-machine installation rehearsals.
- Five-million-order-line load, memory/concurrency measurement and a defined
  two-model inference latency workload.
- Uptime measurement over the agreed evaluation window.
- Public deployment security settings and evaluator credentials.
- Application audit/job-status/model-version requirements and failure injection.
- Complete screenshots, report-download review and mobile/browser matrix.
- Independent human code/document review, verifier names and explainability rehearsal.

Earlier `check --deploy` found five development warnings: DEBUG enabled, no
HTTPS redirect, no HSTS duration, and non-secure session/CSRF cookies. They are
not represented as resolved in this pack. Demand forecasts have measurable MAE
improvement but material large-error behavior; model quality is assessed in the
project/comparison reports rather than inferred from tests passing.
