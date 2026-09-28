param(
    [string]$ImagesArchive = '',
    [string]$ProjectName = 'dineiq-student',
    [int]$PostgresPort = 5432,
    [int]$RedisPort = 6379,
    [int]$SparkPort = 17077,
    [int]$MasterUiPort = 18080,
    [int]$WorkerUiPort = 18081
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]+$') { throw 'Invalid Docker project name.' }
foreach ($port in @($PostgresPort, $RedisPort, $SparkPort, $MasterUiPort, $WorkerUiPort)) {
    if ($port -lt 1024 -or $port -gt 65535) { throw 'Ports must be in the range 1024-65535.' }
}
function Invoke-Checked {
    param([string]$Command, [string[]]$CommandArgs)
    & $Command @CommandArgs
    if ($LASTEXITCODE -ne 0) { throw "$Command failed (exit $LASTEXITCODE)." }
}
Get-Command uv, docker -ErrorAction Stop | Out-Null
Invoke-Checked 'docker' @('info', '--format', '{{.OSType}}')
Invoke-Checked 'uv' @('sync', '--locked')
Invoke-Checked 'uv' @('run', 'python', 'scripts/verify_handoff.py')

if ($ImagesArchive) {
    $imagePath = (Resolve-Path -LiteralPath $ImagesArchive).Path
    Invoke-Checked 'docker' @('load', '--input', $imagePath)
}

if (-not (Test-Path -LiteralPath '.env')) {
    # Every recipient receives fresh application/database secrets.
    $appSecret = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    $dbSecret = [guid]::NewGuid().ToString('N')
    $envText = Get-Content -Raw -LiteralPath '.env.example'
    $envText = $envText.Replace('replace-this-with-a-long-random-value', $appSecret)
    $envText = $envText.Replace('replace-this-with-a-random-db-password', $dbSecret)
    $envText = $envText.Replace('POSTGRES_PORT=5432', "POSTGRES_PORT=$PostgresPort")
    $envText = $envText.Replace('@127.0.0.1:5432/', "@127.0.0.1:$PostgresPort/")
    $envText = $envText.Replace('REDIS_PORT=6379', "REDIS_PORT=$RedisPort")
    $envText = $envText.Replace('127.0.0.1:6379', "127.0.0.1:$RedisPort")
    $envText = $envText.Replace('SPARK_MASTER_PORT=17077', "SPARK_MASTER_PORT=$SparkPort")
    $envText = $envText.Replace('127.0.0.1:17077', "127.0.0.1:$SparkPort")
    $envText = $envText.Replace('SPARK_MASTER_UI_PORT=18080', "SPARK_MASTER_UI_PORT=$MasterUiPort")
    $envText = $envText.Replace('SPARK_WORKER_UI_PORT=18081', "SPARK_WORKER_UI_PORT=$WorkerUiPort")
    $envText += "`nCOMPOSE_PROJECT_NAME=$ProjectName`n"
    [System.IO.File]::WriteAllText((Join-Path $projectRoot '.env'), $envText)
}

$composeArgs = @('compose', '-p', $ProjectName)
Invoke-Checked 'docker' ($composeArgs + @('up', '-d', 'postgres', 'redis'))
$databaseReady = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    & docker @composeArgs exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | Out-Null
    if ($LASTEXITCODE -eq 0) { $databaseReady = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $databaseReady) { throw 'PostgreSQL did not become ready.' }

$tableCount = & docker @composeArgs exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM pg_tables WHERE schemaname = current_schema()"'
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the target database.' }
if ([int]$tableCount -eq 0) {
    Invoke-Checked 'docker' ($composeArgs + @('cp', 'handoff/database.dump', 'postgres:/tmp/dineiq-handoff.dump'))
    Invoke-Checked 'docker' ($composeArgs + @('exec', '-T', 'postgres', 'sh', '-c',
        'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl --exit-on-error --single-transaction /tmp/dineiq-handoff.dump'))
} else {
    Write-Host 'Target database already contains tables; preserving it and checking compatibility.'
}

if ($ImagesArchive) {
    Invoke-Checked 'docker' ($composeArgs + @('up', '-d', '--no-build', 'spark-master', 'spark-worker'))
} else {
    Invoke-Checked 'docker' ($composeArgs + @('up', '-d', '--build', 'spark-master', 'spark-worker'))
}
Invoke-Checked 'uv' @('run', 'python', 'dine_iq/manage.py', 'migrate', '--check')
Invoke-Checked 'uv' @('run', 'python', 'dine_iq/manage.py', 'check')
Invoke-Checked 'uv' @('run', 'python', 'dine_iq/manage.py', 'import_clean_dataset', '--dry-run')
Invoke-Checked 'uv' @('run', 'python', 'scripts/check_handoff_app.py')
Write-Host 'Setup verified. Start Django: uv run python dine_iq/manage.py runserver 127.0.0.1:8000'
