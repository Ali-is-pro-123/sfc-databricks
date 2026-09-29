Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$exportRoot = (Resolve-Path -LiteralPath (Join-Path $projectRoot 'handoff_exports')).Path
$packageRoot = Join-Path $exportRoot 'submission_package'

if (Test-Path -LiteralPath $packageRoot) {
    throw "The submission package already exists: $packageRoot. Review it before rebuilding."
}

$sections = @(
    '01_project_report',
    '02_source_code',
    '03_big_data_dataset',
    '04_spark_processing_evidence',
    '05_spark_mllib_evidence',
    '06_python_model_evidence',
    '07_dual_pipeline_comparison',
    '08_restaurant_intelligence_report',
    '09_test_cases',
    '10_installation_instructions',
    '11_execution_instructions',
    '12_github_repository',
    '13_deployed_application',
    '14_demonstration_video',
    '15_technical_blog',
    '16_ai_tool_usage_declaration',
    '17_final_submission_checklist'
)

New-Item -ItemType Directory -Path $packageRoot | Out-Null
foreach ($section in $sections) {
    New-Item -ItemType Directory -Path (Join-Path $packageRoot $section) | Out-Null
}

function Copy-Relative {
    param([string] $Source, [string] $Destination)

    $sourcePath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Source))
    $destinationPath = [System.IO.Path]::GetFullPath((Join-Path $packageRoot $Destination))
    if (-not $sourcePath.StartsWith($projectRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Source escapes the project: $Source"
    }
    if (-not $destinationPath.StartsWith($packageRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Destination escapes the package: $Destination"
    }
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Missing source: $Source"
    }
    if (Test-Path -LiteralPath $destinationPath) {
        throw "Destination already exists: $Destination"
    }
    New-Item -ItemType Directory -Path (Split-Path -Path $destinationPath -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Recurse
}

function Copy-FilteredTree {
    param([string] $Source, [string] $Destination)

    $sourcePath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Source))
    $destinationPath = [System.IO.Path]::GetFullPath((Join-Path $packageRoot $Destination))
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
        throw "Missing source directory: $Source"
    }
    foreach ($file in Get-ChildItem -LiteralPath $sourcePath -Recurse -File) {
        if (($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
        $relative = [System.IO.Path]::GetRelativePath($sourcePath, $file.FullName)
        if ($relative -match '(^|[\\/])(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|staticfiles|media)([\\/]|$)') { continue }
        if ($file.Name -match '^(db\.sqlite3|\.env|\.env\..*)$|\.(pyc|pyo|log)$') { continue }
        $copyPath = Join-Path $destinationPath $relative
        New-Item -ItemType Directory -Path (Split-Path -Path $copyPath -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $copyPath
    }
}

# Preserve the report's original documentation tree so its relative links work.
Copy-Relative 'documentation' '01_project_report/documentation'
Copy-Relative 'documentation/submission/project_report.md' '01_project_report/project_report.md'
Copy-Relative 'documentation/submission/design_diagrams.md' '01_project_report/design_diagrams.md'

# This is a source snapshot, not a second runnable checkout or a Git history export.
foreach ($name in @('dine_iq', 'data_generator', 'spark_jobs', 'spark_sql', 'python_pipeline',
                   'templates', 'static', 'tests', 'scripts', 'src', 'config', 'notebooks',
                   'database', 'documentation', 'sample_data')) {
    Copy-FilteredTree $name "02_source_code/source/$name"
}
foreach ($name in @('README.md', 'AI_USAGE.md', 'pyproject.toml', 'uv.lock',
                   'compose.yaml', '.env.example', '.python-version', '.dockerignore')) {
    Copy-Relative $name "02_source_code/source/$name"
}

Copy-Relative 'raw_data/full-seed42' '03_big_data_dataset/raw_data/full-seed42'
Copy-Relative 'parquet_data/step05-full' '03_big_data_dataset/parquet_data/step05-full'
Copy-Relative 'parquet_data/step12-full' '03_big_data_dataset/parquet_data/step12-full'
Copy-Relative 'sample_data' '03_big_data_dataset/sample_data'
Copy-FilteredTree 'data_generator' '03_big_data_dataset/data_generator'
Copy-Relative 'documentation/data_dictionary.md' '03_big_data_dataset/data_dictionary.md'
Copy-Relative 'documentation/step_04_generation.md' '03_big_data_dataset/generation_method.md'

foreach ($name in @('step05-full', 'step06-full', 'step07-full', 'step08-full')) {
    Copy-Relative "processed_data/$name" "04_spark_processing_evidence/processed_data/$name"
}
Copy-FilteredTree 'spark_jobs' '04_spark_processing_evidence/spark_jobs'
Copy-FilteredTree 'spark_sql' '04_spark_processing_evidence/spark_sql'
foreach ($name in @('step_05_spark.md', 'step_06_integration.md', 'step_07_features.md', 'step_08_eda.md')) {
    Copy-Relative "documentation/$name" "04_spark_processing_evidence/documentation/$name"
}

Copy-Relative 'models/step12-full' '05_spark_mllib_evidence/models/step12-full'
Copy-Relative 'processed_data/step12-full' '05_spark_mllib_evidence/processed_data/step12-full'
Copy-Relative 'documentation/step_12_spark_models.md' '05_spark_mllib_evidence/method.md'

foreach ($name in @('step13-full', 'step20-full', 'step24-final-full')) {
    Copy-Relative "models/$name" "06_python_model_evidence/models/$name"
}
foreach ($name in @('step13-full', 'step20-full', 'step22-full', 'step24-final-full', 'step24-verified-full')) {
    Copy-Relative "processed_data/$name" "06_python_model_evidence/processed_data/$name"
}
Copy-FilteredTree 'python_pipeline' '06_python_model_evidence/python_pipeline'
foreach ($name in @('step_13_python_pipeline.md', 'step_20_configurable_forecast.md',
                     'step_22_forecast_accuracy.md', 'step_24_wastage_risk.md')) {
    Copy-Relative "documentation/$name" "06_python_model_evidence/documentation/$name"
}

Copy-Relative 'documentation/submission/dual_pipeline_report.md' '07_dual_pipeline_comparison/dual_pipeline_report.md'
Copy-Relative 'processed_data/step14-full-verified' '07_dual_pipeline_comparison/processed_data/step14-full-verified'
Copy-Relative 'documentation/step_14_dual_verification.md' '07_dual_pipeline_comparison/method.md'

Copy-Relative 'documentation/submission/project_report.md' '08_restaurant_intelligence_report/project_report_reference.md'
Copy-Relative 'screenshots' '08_restaurant_intelligence_report/screenshots'
foreach ($file in Get-ChildItem -LiteralPath (Join-Path $projectRoot 'processed_data') -Recurse -File -Filter '*.json') {
    $relative = [System.IO.Path]::GetRelativePath($projectRoot, $file.FullName)
    Copy-Relative $relative "08_restaurant_intelligence_report/$relative"
}

Copy-FilteredTree 'tests' '09_test_cases/tests'
foreach ($area in @('python_pipeline', 'spark_jobs')) {
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $projectRoot $area) -File -Filter 'test_*.py') {
        Copy-Relative "$area/$($file.Name)" "09_test_cases/$area/$($file.Name)"
    }
}
foreach ($file in Get-ChildItem -LiteralPath (Join-Path $projectRoot 'dine_iq/apps') -Recurse -File) {
    if ($file.Name -eq 'tests.py' -or $file.Name -like 'test_*.py') {
        $relative = [System.IO.Path]::GetRelativePath($projectRoot, $file.FullName)
        Copy-Relative $relative "09_test_cases/$relative"
    }
}
Copy-Relative 'documentation/submission/test_evidence.md' '09_test_cases/test_evidence.md'
Copy-Relative 'documentation/submission/evidence' '09_test_cases/evidence'
Copy-Relative 'documentation/nfr_acceptance_plan.md' '09_test_cases/nfr_acceptance_plan.md'

foreach ($name in @('README.md', 'compose.yaml', '.env.example', 'pyproject.toml', 'uv.lock')) {
    Copy-Relative $name "10_installation_instructions/$name"
}
Copy-Relative 'documentation/submission/evaluator_guide.md' '10_installation_instructions/evaluator_guide.md'
Copy-Relative 'config/README.md' '10_installation_instructions/spark_setup.md'
Copy-Relative 'config/spark.Dockerfile' '10_installation_instructions/config/spark.Dockerfile'

Copy-Relative 'README.md' '11_execution_instructions/project_readme.md'
Copy-Relative 'documentation/submission/evaluator_guide.md' '11_execution_instructions/evaluator_guide.md'
foreach ($file in Get-ChildItem -LiteralPath (Join-Path $projectRoot 'documentation') -File -Filter 'step_*.md') {
    Copy-Relative "documentation/$($file.Name)" "11_execution_instructions/steps/$($file.Name)"
}

Copy-Relative 'README.md' '12_github_repository/project_readme.md'
Copy-Relative 'documentation/submission/evaluator_guide.md' '13_deployed_application/local_evaluator_guide.md'
Copy-Relative 'compose.yaml' '13_deployed_application/compose.yaml'
Copy-Relative 'config/spark.Dockerfile' '13_deployed_application/config/spark.Dockerfile'
Copy-Relative '.env.example' '13_deployed_application/env.example'
Copy-Relative 'documentation/submission/demonstration_storyboard.md' '14_demonstration_video/storyboard.md'
Copy-Relative 'AI_USAGE.md' '16_ai_tool_usage_declaration/AI_USAGE.md'
Copy-Relative 'documentation/submission/team_contributions.md' '16_ai_tool_usage_declaration/team_review_template.md'
Copy-Relative 'documentation/submission/README.md' '17_final_submission_checklist/submission_register.md'
Copy-Relative 'documentation/submission/requirements_traceability.md' '17_final_submission_checklist/requirements_traceability.md'
Copy-Relative 'documentation/submission/team_contributions.md' '17_final_submission_checklist/team_contributions.md'
Copy-Relative 'documentation/submission/evidence/source_manifest.json' '17_final_submission_checklist/source_manifest.json'

$files = Get-ChildItem -LiteralPath $packageRoot -Recurse -File
$bytes = ($files | Measure-Object -Property Length -Sum).Sum
Write-Output ("Created {0} sections, {1} files, {2:N1} MB at {3}" -f $sections.Count, $files.Count, ($bytes / 1MB), $packageRoot)
