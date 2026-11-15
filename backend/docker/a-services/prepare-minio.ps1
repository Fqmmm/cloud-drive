param([string]$ArchivePath = '', [switch]$Export)
$ErrorActionPreference = 'Stop'
$expected = 'sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e'
$reference = 'cloud-drive-minio:release-2025-09-07'
if (!$ArchivePath) { $ArchivePath = Join-Path $PSScriptRoot 'artifacts/minio-release-2025-09-07.tar' }

function Find-VerifiedImage {
    foreach ($candidate in @($reference, "minio/minio@$expected", 'minio/minio:latest')) {
        $identity = & docker image inspect --format '{{.Id}}' $candidate 2>$null
        if ($LASTEXITCODE -eq 0 -and $identity -eq $expected) { return $candidate }
    }
    return $null
}

$source = Find-VerifiedImage
if (!$source -and (Test-Path -LiteralPath $ArchivePath)) {
    & docker image load --input $ArchivePath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not load the provided MinIO image archive.' }
    $source = Find-VerifiedImage
}
if (!$source) {
    throw 'Verified MinIO image is unavailable locally. Obtain the verified image archive from B/A and pass -ArchivePath; no registry credentials are changed.'
}
& docker image tag $source $reference
if ($LASTEXITCODE -ne 0) { throw 'Could not create the explicit course MinIO tag.' }
$version = & docker run --rm $reference --version
if ($LASTEXITCODE -ne 0 -or ($version -join "`n") -notmatch 'RELEASE\.2025-09-07T16-13-09Z') {
    throw 'MinIO version verification failed.'
}
Write-Output "Verified $reference ($expected), RELEASE.2025-09-07T16-13-09Z"
if ($Export) {
    if (Test-Path -LiteralPath $ArchivePath) { throw 'Archive already exists; choose a new export path.' }
    $parentDirectory = Split-Path -Parent ([IO.Path]::GetFullPath($ArchivePath))
    [IO.Directory]::CreateDirectory($parentDirectory) | Out-Null
    & docker image save --output $ArchivePath $reference
    if ($LASTEXITCODE -ne 0) { throw 'MinIO image export failed.' }
    $hash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText(([IO.Path]::GetFullPath($ArchivePath) + '.sha256'), $hash + "`n")
    Write-Output "Exported image archive: $([IO.Path]::GetFullPath($ArchivePath))"
    Write-Output "Archive SHA-256: $hash"
}
