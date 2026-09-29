# DineIQ submission preparation

Prepared: 27 September 2026. Status: working submission pack; human review pending.

This pack maps SRS section 1.10 (PDF pages 38-52) to the actual repository.
It is an evidence index, not a declaration that every requirement is complete.
Application source lives in `dine_iq/`; dependencies are managed by `uv.lock`
and `pyproject.toml`. These differences from the SRS example folder list are
explicit and should be explained to evaluators.

## Start here

1. Read the [Word project report with six diagrams](DineIQ_Project_Report.docx), alongside the [detailed Markdown report](project_report.md) and [diagram sources](design_diagrams.md).
2. Review [Requirements traceability](requirements_traceability.md).
3. Follow [Evaluator guide](evaluator_guide.md) for installation and evidence navigation.
4. Read [Test evidence](test_evidence.md) and [Dual-pipeline comparison](dual_pipeline_report.md).
5. Use [Demonstration storyboard](demonstration_storyboard.md) to prepare the mandatory video.
6. Complete [Team contribution record](team_contributions.md) with real names and review evidence.

The [source manifest](evidence/source_manifest.json) records SHA-256 hashes and
sizes for 11 local analytical reports/CSV files used while preparing this pack.
It identifies the source snapshot; it does not distribute those ignored files.

## Deliverable register

The number column follows the SRS deliverable sections. "Local evidence" means
files exist on this machine; it does not mean they are included in Git or shared.

| # | Required deliverable | Current evidence | Remaining work |
| --- | --- | --- | --- |
| 1 | Project report | [Word draft with six diagrams](DineIQ_Project_Report.docx), [detailed report](project_report.md), [diagram sources](design_diagrams.md), [data dictionary](../data_dictionary.md) | Team review and final sign-off |
| 2 | Source code | Django, templates, static assets, generator, Spark/SQL, Python pipeline, tests | Public repository; license decision; dependency export if evaluator requires requirements.txt |
| 3 | Big Data dataset | `raw_data/full-seed42/`, Step 5 clean/quarantine Parquet, Steps 12/13 supervised snapshots | Package small raw/clean samples; publish large-artifact access instructions; execute hidden-data rehearsal |
| 4 | Spark processing evidence | Step 5-12 JSON reports, SQL, historical execution logs under `processed_data/` | Collect the authoritative logs and reports into a shareable evidence bundle |
| 5 | Spark MLlib evidence | Step 12 saved model, report, predictions; three candidate algorithms | Explain model settings and provenance; human review; artifact distribution |
| 6 | Python model evidence | Steps 13, 20, 22 and verified Step 24 artifacts | Same review/distribution work; do not claim a confusion matrix for demand regression |
| 7 | Dual-pipeline comparison | [Separate report](dual_pipeline_report.md); verified CSV has 17,180 unseen records | Package CSV and source reports with final submission |
| 8 | Restaurant Intelligence report | Twelve HTML report families at `/reports/`; Step 8-39 evidence | Export and assemble one reviewed business report covering all SRS topics |
| 9 | Test cases/results | [Test evidence](test_evidence.md), unit tests and historical Spark tests | Repeat Spark acceptance run when final code is frozen; hidden-data, scale and deployment tests |
| 10 | Installation instructions | [Evaluator guide](evaluator_guide.md), root README, stage-specific commands | Rehearse on a clean Windows machine |
| 11 | Execution instructions | Evaluator guide and linked Step 4-50 documents | End-to-end regeneration rehearsal with a new output namespace |
| 12 | Public GitHub repository | Public `main` at `https://github.com/Ali-is-pro-123/sfc-databricks` | Verify real individual contribution claims; do not invent or backdate history |
| 13 | Deployed application/local alternative | Local Django; Spark runtime published at `alirazazulfiqar/sfc-databricks:latest` | Docker image is not a public web deployment; validate complete local installation or deploy web app |
| 14 | Mandatory MP4 demonstration | [Storyboard](demonstration_storyboard.md) | Record, review and provide the MP4/link |
| 15 | Published technical blog, at least 2,000 words | Methodology/evidence in this pack and step documents | Write reviewed article, check word count, publish and add URL |
| 16 | AI declaration | [AI_USAGE.md](../../AI_USAGE.md), documentation-assistance entry | Real human verifier names and independent review for every affected module |
| 17 | Final submission checklist | This register and requirements matrix | Resolve open items, verify every public link, sign off |
| Checklist | Project presentation | Architecture, methods, results and limits available in this pack | Build and rehearse a slide deck |
| Checklist | Team contribution record | [Honest review template](team_contributions.md) | Fill from actual work and review evidence |

## Completion rules

- Do not label a feature complete merely because a stage document exists.
- A passed pipeline report means its validation checks passed; it does not certify model accuracy or deployment readiness.
- Preserve the difference between generated reference data, raw corrupted data,
  accepted records, eligible analytical populations, and held-out records.
- Generated data, model artifacts, and reports are ignored by Git. A public code
  repository alone will not deliver them. Provide regeneration instructions and
  an accessible artifact bundle or external download with checksums.
- Earlier exploratory output directories are not interchangeable with the
  authoritative paths listed in the project report and evaluator guide.
- Team identity, license choice, public URLs, reviewer signatures and recordings
  require actual information. No placeholder is an approved deliverable.

## Preparation order

1. Foundation: consolidated report, diagrams, traceability, evaluator guide,
   comparison report, test evidence and video storyboard (this pack).
2. Evidence packaging: business report, samples, screenshots, model/data manifest,
   and a clean-install/hidden-data rehearsal.
3. Communication: technical blog draft, presentation and video recording.
4. Release: remaining SRS implementation gaps, human sign-off, artifact hosting,
   public repository and final access checks.
