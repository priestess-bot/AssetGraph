[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runRoot = Join-Path $repoRoot ".run\windows"

function Stop-ProcessTree {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $runRoot)) {
    Write-Host "AssetGraph has no recorded Windows development processes."
    return
}

foreach ($name in @("guided-content-generation", "maitu-interaction-sync", "maitu-interaction-analysis", "frontend", "backend", "minio", "maitu-browser")) {
    $recordPath = Join-Path $runRoot "$name.json"
    if (-not (Test-Path -LiteralPath $recordPath)) {
        continue
    }
    $record = Get-Content -Raw -LiteralPath $recordPath -Encoding UTF8 | ConvertFrom-Json
    $process = Get-Process -Id ([int]$record.process_id) -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        $expectedStart = [DateTime]::Parse([string]$record.started_at).ToUniversalTime()
        $actualStart = $process.StartTime.ToUniversalTime()
        if ([Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -le 2) {
            Stop-ProcessTree -ProcessId $process.Id
            Write-Host "Stopped $name (PID $($process.Id))."
        } else {
            Write-Warning "Skipped stale $name record because PID $($process.Id) was reused."
        }
    }
    Remove-Item -LiteralPath $recordPath -Force
}
