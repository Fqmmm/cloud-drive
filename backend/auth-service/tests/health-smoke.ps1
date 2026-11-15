param(
    [string]$ApplicationImage = '',
    [string]$RuntimeImage = 'eclipse-temurin:17-jre',
    [string]$MysqlImage = 'mysql:8.0.29'
)
$ErrorActionPreference = 'Stop'
$servicePath = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$jarPath = Join-Path $servicePath 'target/auth-service.jar'
if (!$ApplicationImage -and !(Test-Path -LiteralPath $jarPath)) { throw 'Run Maven verify first.' }
$prefix = 'course-a-health-' + [guid]::NewGuid().ToString('N').Substring(0, 10)
$network = $prefix + '-net'
$database = $prefix + '-db'
$application = $prefix + '-app'
$oldPassword = $env:AUTH_DB_PASSWORD
$oldMysqlPassword = $env:MYSQL_PASSWORD
$oldRootPassword = $env:MYSQL_ROOT_PASSWORD
$oldJwtSecret = $env:JWT_SECRET

function Invoke-Docker {
    param([string[]]$Arguments)
    $output = & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Docker command failed; inspect test container status.' }
    return $output
}

function Assert-Probe {
    param([string]$Path, [int]$Status, [string]$State)
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $response = Invoke-WebRequest -Uri ($script:baseUrl + $Path) -TimeoutSec 12 -SkipHttpErrorCheck
    $timer.Stop()
    if ([int]$response.StatusCode -ne $Status -or
        ($response.Content | ConvertFrom-Json).status -ne $State) {
        throw "Probe $Path did not return $Status/$State"
    }
    if ($timer.Elapsed.TotalSeconds -gt 10) { throw 'Probe exceeded bounded wait.' }
    Write-Output ("{0} {1}/{2} ({3:N2}s)" -f $Path, $Status, $State, $timer.Elapsed.TotalSeconds)
}

function Wait-Ready {
    $deadline = (Get-Date).AddSeconds(90)
    do {
        $response = Invoke-WebRequest -Uri ($script:baseUrl + '/health/ready') -TimeoutSec 12 -SkipHttpErrorCheck
        if ($response.StatusCode -eq 200) { return }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw 'Database readiness did not recover within 90 seconds.'
}

try {
    # Credentials stay in process/container environments; never print or write them to disk.
    $env:AUTH_DB_PASSWORD = [guid]::NewGuid().ToString('N')
    $env:MYSQL_PASSWORD = $env:AUTH_DB_PASSWORD
    $env:MYSQL_ROOT_PASSWORD = [guid]::NewGuid().ToString('N')
    $env:JWT_SECRET = [guid]::NewGuid().ToString('N')
    Invoke-Docker -Arguments @('network', 'create', $network) | Out-Null
    $runArguments = @('run', '-d', '--name', $application, '--network', $network,
        '-p', '127.0.0.1::8080', '-e', 'AUTH_DB_PASSWORD', '-e', 'JWT_SECRET',
        '-e', 'JWT_ISSUER=course-drive', '-e', 'JWT_AUDIENCE=course-drive-api',
        '-e', "AUTH_DB_URL=jdbc:mysql://${database}:3306/auth_db?connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true&connectTimeout=3000&socketTimeout=5000")
    if ($ApplicationImage) {
        $runArguments += $ApplicationImage
    } else {
        $runArguments += @('--mount', "type=bind,source=$jarPath,target=/app/app.jar,readonly",
            $RuntimeImage, 'java', '-jar', '/app/app.jar')
    }
    Invoke-Docker -Arguments $runArguments | Out-Null
    $binding = Invoke-Docker -Arguments @('port', $application, '8080/tcp')
    $script:baseUrl = 'http://' + ($binding | Select-Object -First 1)
    $deadline = (Get-Date).AddSeconds(60)
    do {
        try {
            $response = Invoke-WebRequest -Uri ($script:baseUrl + '/health/live') -TimeoutSec 2
            if ($response.StatusCode -eq 200) { break }
        } catch { Start-Sleep -Seconds 1 }
    } while ((Get-Date) -lt $deadline)
    Assert-Probe '/health/live' 200 'UP'
    Assert-Probe '/health/ready' 503 'DOWN'

    # This fresh MySQL uses tmpfs only, has no host port and cannot touch course volumes.
    Invoke-Docker -Arguments @('run', '-d', '--name', $database, '--network', $network,
        '--tmpfs', '/var/lib/mysql:rw', '-e', 'MYSQL_ROOT_PASSWORD',
        '-e', 'MYSQL_PASSWORD', '-e', 'MYSQL_USER=auth_user', '-e', 'MYSQL_DATABASE=auth_db',
        $MysqlImage, '--default-time-zone=+00:00') | Out-Null
    Wait-Ready
    Assert-Probe '/health/ready' 200 'UP'
    Invoke-Docker -Arguments @('stop', $database) | Out-Null
    Assert-Probe '/health/live' 200 'UP'
    Assert-Probe '/health/ready' 503 'DOWN'
    Invoke-Docker -Arguments @('start', $database) | Out-Null
    Wait-Ready
    Assert-Probe '/health/ready' 200 'UP'
    $restarts = Invoke-Docker -Arguments @('inspect', '--format', '{{.RestartCount}}', $application)
    if ($restarts -ne '0') { throw 'Application restarted during database recovery.' }
    Write-Output 'PASS: startup outage, database recovery, outage and recovery without application restart.'
} finally {
    # Remove only the two uniquely named disposable test containers and their test network.
    & docker rm -f $application $database 2>$null | Out-Null
    & docker network rm $network 2>$null | Out-Null
    $env:AUTH_DB_PASSWORD = $oldPassword
    $env:MYSQL_PASSWORD = $oldMysqlPassword
    $env:MYSQL_ROOT_PASSWORD = $oldRootPassword
    $env:JWT_SECRET = $oldJwtSecret
}
