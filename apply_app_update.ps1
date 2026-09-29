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
try {
    while ((Get-Date) -lt $deadline) {
        $running = Get-CimInstance Win32_Process -Filter "name = 'Policy Amadeus.exe'" |
            Where-Object { $_.ExecutablePath -eq $Target }
        if (-not $running) { break }
        Start-Sleep -Seconds 10
    }
    if ($running) { throw '程序仍在运行，更新将在下次检查时重试' }
    if (-not (Test-Path -LiteralPath $Staged)) { throw '待安装程序不存在' }
    if ((Get-FileHash -LiteralPath $Staged -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedHash) {
        throw '待安装程序哈希不匹配'
    }
    Copy-Item -LiteralPath $Target -Destination $backup -Force
    $replacementStarted = $true
    Copy-Item -LiteralPath $Staged -Destination $Target -Force
    if ((Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedHash) {
        Copy-Item -LiteralPath $backup -Destination $Target -Force
        throw '安装后校验失败，已回滚'
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
