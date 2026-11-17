param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [ValidateRange(5, 60)][int]$IntervalSeconds = 15
)
# Read-only Docker monitoring. Start in a second host PowerShell window.
# Captures only current-repository build history and this experiment's services.
$ErrorActionPreference = 'Continue'
if ($RunId -notmatch '^[a-z0-9-]{1,24}$') { throw 'Invalid RunId.' }
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$folder = Join-Path $repo "artifacts/liu/$RunId"
$environmentFile = Join-Path $folder '.env'
if (!(Test-Path -LiteralPath $environmentFile)) { throw 'Experiment environment not found.' }
$projectLine = Get-Content -LiteralPath $environmentFile | Where-Object { $_ -match '^COMPOSE_PROJECT_NAME=' } | Select-Object -First 1
$projectName = $projectLine.Substring('COMPOSE_PROJECT_NAME='.Length)
if ($projectName -notmatch '^cloud-drive-liu-[a-z0-9-]{1,32}$') { throw 'Invalid experiment project.' }
Push-Location $repo
try {
    Write-Host "Monitoring $projectName every $IntervalSeconds seconds. Ctrl+C stops monitoring only."
    while ($true) {
        $observed = [DateTime]::UtcNow.ToString('o')
        $containerOutput = @(& docker ps -a --filter "label=com.docker.compose.project=$projectName" --format '{{json .}}' 2>$null)
        $containerExit = $LASTEXITCODE
        $buildOutput = @(& docker buildx history ls --local --format '{{json .}}' 2>$null)
        $buildExit = $LASTEXITCODE
        $snapshot = [ordered]@{
            observed_utc = $observed
            project = $projectName
            container_query_exit = $containerExit
            containers = $containerOutput
            repository_build_query_exit = $buildExit
            repository_builds = $buildOutput
            interval_seconds = $IntervalSeconds
            scope = 'Read-only; current repository builds and selected Compose project'
        }
        $json = $snapshot | ConvertTo-Json -Depth 8
        # Private diagnostics, excluded from Git. No environment/config dump.
        $json | Set-Content -LiteralPath (Join-Path $folder 'live-status.json') -Encoding UTF8
        ($snapshot | ConvertTo-Json -Depth 8 -Compress) | Add-Content -LiteralPath (Join-Path $folder 'live-status.jsonl') -Encoding UTF8
        Write-Host "$observed containers=$($containerOutput.Count) dockerExit=$containerExit buildExit=$buildExit"
        $buildOutput | Select-Object -First 4 | ForEach-Object { Write-Host $_ }
        Start-Sleep -Seconds $IntervalSeconds
    }
} finally { Pop-Location }
