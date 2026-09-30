param(
    [Parameter(Mandatory = $true)][int]$ParentPid,
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Staged,
    [Parameter(Mandatory = $true)][string]$ExpectedHash,
    [Parameter(Mandatory = $true)][string]$StatusFile
)

$ErrorActionPreference = 'Stop'
$backup = "$Target.backup"
$deadline = (Get-Date).AddHours(12)
$replacementStarted = $false
function Get-UpdateHash([string]$Path) {
    $inputStream = [System.IO.File]::OpenRead($Path)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [System.BitConverter]::ToString($algorithm.ComputeHash($inputStream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
        $inputStream.Dispose()
    }
}
try {
    while ((Get-Date) -lt $deadline) {
        $running = Get-CimInstance Win32_Process -Filter "name = 'Policy Amadeus.exe'" |
            Where-Object { $_.ExecutablePath -eq $Target }
        if (-not $running) { break }
        Start-Sleep -Seconds 10
    }
    if ($running) { throw 'Application is still running; retry on the next update check' }
    if (-not (Test-Path -LiteralPath $Staged)) { throw 'Staged application is missing' }
    if ((Get-UpdateHash $Staged) -ne $ExpectedHash) {
        throw 'Staged application hash does not match the signed manifest'
    }
    Copy-Item -LiteralPath $Target -Destination $backup -Force
    $replacementStarted = $true
    Copy-Item -LiteralPath $Staged -Destination $Target -Force
    if ((Get-UpdateHash $Target) -ne $ExpectedHash) {
        Copy-Item -LiteralPath $backup -Destination $Target -Force
        throw 'Installed application hash mismatch; restored the backup'
    }
    @{ state = 'installed'; installed_at = (Get-Date).ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath $StatusFile -Encoding UTF8
} catch {
    if ($replacementStarted -and (Test-Path -LiteralPath $backup)) {
        Copy-Item -LiteralPath $backup -Destination $Target -Force -ErrorAction SilentlyContinue
    }
    @{ state = 'failed'; error = $_.Exception.Message; checked_at = (Get-Date).ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath $StatusFile -Encoding UTF8
} finally {
    Remove-Item -LiteralPath $Staged -Force -ErrorAction SilentlyContinue
}
