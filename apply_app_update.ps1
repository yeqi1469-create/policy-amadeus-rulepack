param(
    [Parameter(Mandatory = $true)][int]$ParentPid,
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Staged,
    [Parameter(Mandatory = $true)][string]$ExpectedHash,
    [Parameter(Mandatory = $true)][string]$StatusFile,
    [string]$CandidateVersion = ''
)

$ErrorActionPreference = 'Stop'
$backup = "$Target.backup"
$deadline = (Get-Date).AddHours(12)
$replacementStarted = $false
$installMutex = $null
$mutexHeld = $false
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
function Get-AppVersionParts([string]$Version) {
    if ($Version -match '^(\d{4}\.\d{2}\.\d{2})-(\d{1,9})$') {
        return @([DateTime]::ParseExact($Matches[1], 'yyyy.MM.dd', [Globalization.CultureInfo]::InvariantCulture).Ticks, [long]$Matches[2])
    }
    return @()
}
try {
    while ((Get-Date) -lt $deadline) {
        $running = Get-CimInstance Win32_Process -Filter "name = 'Policy Amadeus.exe'" |
            Where-Object { $_.ExecutablePath -eq $Target }
        if (-not $running) { break }
        Start-Sleep -Seconds 10
    }
    if ($running) { throw 'Application is still running; retry on the next update check' }
    # Serialize replacement for this exact target, not the whole computer.
    $targetBytes = [System.Text.Encoding]::UTF8.GetBytes([System.IO.Path]::GetFullPath($Target).ToLowerInvariant())
    $nameHasher = [System.Security.Cryptography.SHA256]::Create()
    try { $mutexName = 'Local\PolicyAmadeusInstall-' + [System.BitConverter]::ToString($nameHasher.ComputeHash($targetBytes)).Replace('-', '') }
    finally { $nameHasher.Dispose() }
    $installMutex = New-Object System.Threading.Mutex($false, $mutexName)
    $mutexHeld = $installMutex.WaitOne(60000)
    if (-not $mutexHeld) { throw 'Another installer is replacing this application; retry later' }
    $pendingSelection = Join-Path (Split-Path -Parent $StatusFile) 'pending_app_update.json'
    if (Test-Path -LiteralPath $pendingSelection) {
        $selection = Get-Content -LiteralPath $pendingSelection -Raw | ConvertFrom-Json
        $selectionAlive = $selection.helper_pid -and (Get-Process -Id $selection.helper_pid -ErrorAction SilentlyContinue)
        $selectedVersion = @(Get-AppVersionParts ([string]$selection.version))
        $ownVersion = @(Get-AppVersionParts $CandidateVersion)
        $newerSelected = $selectedVersion.Count -eq 2 -and $ownVersion.Count -eq 2 -and (
            $selectedVersion[0] -gt $ownVersion[0] -or ($selectedVersion[0] -eq $ownVersion[0] -and $selectedVersion[1] -ge $ownVersion[1]))
        $unknownVersionWithLiveReplacement = $ownVersion.Count -eq 0 -and $selectionAlive -and (Test-Path -LiteralPath $selection.staged)
        if ($selection.sha256 -ne $ExpectedHash -and ($newerSelected -or $unknownVersionWithLiveReplacement)) {
            # Keep rejecting obsolete helpers even after the newer helper
            # exits and deletes its staging file. PID liveness alone is not
            # sufficient to prevent an old helper downgrading the installation.
            @{ state = 'superseded'; checked_at = (Get-Date).ToString('o') } |
                ConvertTo-Json | Set-Content -LiteralPath $StatusFile -Encoding UTF8
            return
        }
    }
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
    if ($mutexHeld) { $installMutex.ReleaseMutex() }
    if ($installMutex) { $installMutex.Dispose() }
    Remove-Item -LiteralPath $Staged -Force -ErrorAction SilentlyContinue
}
