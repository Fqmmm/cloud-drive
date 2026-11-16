param([string]$ProjectName, [string]$EnvFile = '.env')
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Push-Location $repo
try {
    $resolvedEnv = (Resolve-Path -LiteralPath $EnvFile).Path
    $composeArgs = @('--env-file', $resolvedEnv)
    if ($ProjectName) { $composeArgs += @('-p', $ProjectName) }
    & docker compose @composeArgs exec -T frontend nginx -t
    if ($LASTEXITCODE -ne 0) { throw 'Nginx configuration validation failed.' }
    & docker compose @composeArgs exec -T frontend nginx -s reload
    if ($LASTEXITCODE -ne 0) { throw 'Nginx reload failed.' }
    Write-Host 'Nginx configuration validated and reload requested.'
} finally { Pop-Location }
