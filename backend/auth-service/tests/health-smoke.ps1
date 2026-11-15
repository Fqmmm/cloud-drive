param([string]$ApplicationImage = '', [string]$RuntimeImage = 'eclipse-temurin:17-jre', [string]$MysqlImage = 'mysql:8.0.29')
& "$PSScriptRoot/../../tests/health_smoke.ps1" -Service auth-service @PSBoundParameters
