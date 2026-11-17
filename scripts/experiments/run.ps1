param(
    [string]$RunId = (Get-Date -Format 'yyyyMMdd-HHmmss'),
    [int]$Port = 8088,
    [int]$RestorePort = 8089,
    [string]$NpmRegistry = 'https://registry.npmjs.org',
    [string]$MavenMirror = '',
    [switch]$SkipRestore,
    [switch]$IncludeMysql
)
# Compatible with Windows PowerShell 5.1 and PowerShell 7. No admin privileges.
$ErrorActionPreference = 'Stop'
$previousUtf8 = $env:PYTHONUTF8
$env:PYTHONUTF8 = '1'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Push-Location $repo
try {
    if ($RunId -notmatch '^[a-z0-9-]{1,24}$') { throw 'Invalid RunId.' }
    if ($Port -eq $RestorePort) { throw 'Experiment and restore ports must differ.' }
    $privateRoot = Join-Path $repo 'artifacts/liu-tools'
    $pythonExe = Join-Path $privateRoot 'Scripts/python.exe'
    if (!(Test-Path -LiteralPath $pythonExe)) {
        & python -m venv $privateRoot
        if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
    }
    & $pythonExe -m pip install -r scripts/experiments/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    $previousBrowsers = $env:PLAYWRIGHT_BROWSERS_PATH
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $repo 'artifacts/liu-browsers'
    try {
        & $pythonExe -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed.' }
        & $pythonExe -m unittest discover -s scripts/experiments -p test_experiments.py -v
        if ($LASTEXITCODE -ne 0) { throw 'Experiment-tool checks failed.' }
        Write-Host "RunId=$RunId. Building six services, then acceptance, E3 and E4. Logs are saved automatically."
        Write-Host "Live build log: experiments/acceptance/$RunId-deployment/build.live.log"
        $arguments = @('-u', 'scripts/experiments/run.py', 'all', '--run-id', $RunId,
            '--port', "$Port", '--restore-port', "$RestorePort", '--npm-registry', $NpmRegistry)
        if (!$SkipRestore) { $arguments += '--restore' }
        if ($IncludeMysql) { $arguments += '--include-mysql' }
        if ($MavenMirror) { $arguments += @('--maven-mirror', $MavenMirror) }
        New-Item -ItemType Directory -Path (Join-Path $repo "artifacts/liu/$RunId") -Force | Out-Null
        & $pythonExe @arguments 2>&1 | Tee-Object -FilePath (Join-Path $repo "artifacts/liu/$RunId/console.log")
        if ($LASTEXITCODE -ne 0) { throw "Run $RunId stopped. Keep this batch and share the final error; do not overwrite it." }
        Write-Host "Complete: experiments/E3/$RunId, experiments/E4/$RunId, docs/exp/E3-results.md and E4-results.md"
        Write-Host 'Containers, named volumes and private backups are retained.'
    } finally {
        if ($null -eq $previousBrowsers) { Remove-Item Env:PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue }
        else { $env:PLAYWRIGHT_BROWSERS_PATH = $previousBrowsers }
    }
} finally {
    Pop-Location
    if ($null -eq $previousUtf8) { Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue }
    else { $env:PYTHONUTF8 = $previousUtf8 }
}
