param([switch]$InitOnly)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Push-Location $repo
try {
    if (!(Test-Path -LiteralPath '.env')) {
        $template = Get-Content -LiteralPath '.env.example' -Raw
        foreach ($name in @('MYSQL_ROOT_PASSWORD', 'AUTH_DB_PASSWORD', 'FILE_DB_PASSWORD',
                'SHARE_DB_PASSWORD', 'MINIO_ROOT_PASSWORD', 'JWT_SECRET', 'INTERNAL_API_TOKEN')) {
            $secret = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
            $template = [regex]::Replace($template, "(?m)^$name=.*$", "$name=$secret")
        }
        # CreateNew avoids replacing a concurrent initialization or existing volume credentials.
        $stream = [IO.File]::Open((Join-Path $repo '.env'), [IO.FileMode]::CreateNew)
        try {
            $bytes = [Text.UTF8Encoding]::new($false).GetBytes($template)
            $stream.Write($bytes, 0, $bytes.Length)
        } finally { $stream.Dispose() }
        Write-Host 'Created root .env with independent random credentials (not printed).'
    }
    & docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Compose configuration is invalid.' }
    if ($InitOnly) { return }
    & docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0) { throw 'Open Docker Desktop and wait for Engine running, then retry.' }
    & docker compose up -d --build --wait --wait-timeout 300
    if ($LASTEXITCODE -ne 0) { throw 'Deployment failed. Check docker compose ps and logs.' }
    & docker compose ps
    Write-Host 'Ready. Open PUBLIC_BASE_URL from the root .env (default http://localhost:8080).'
} finally { Pop-Location }
