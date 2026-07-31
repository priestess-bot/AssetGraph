[CmdletBinding()]
param(
    [string]$Url = "https://live2.maituai.com/LiveManage",
    [int]$DebugPort = 9223
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$debugEndpoint = "http://127.0.0.1:$DebugPort/json/version"

function Test-DebugEndpoint {
    try {
        $response = Invoke-RestMethod -Uri $debugEndpoint -TimeoutSec 2
        return $null -ne $response.webSocketDebuggerUrl
    } catch {
        return $false
    }
}

if (Test-DebugEndpoint) {
    Write-Host "A visible browser CDP session is already available at http://127.0.0.1:$DebugPort."
    return
}

$browserCandidates = @(
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe")
)
$browser = $browserCandidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
    Select-Object -First 1
if (-not $browser) {
    throw "Chrome or Edge is required for the visible Maitu session."
}

$profile = Join-Path $repoRoot "data\maitu-browser-profile"
New-Item -ItemType Directory -Force -Path $profile | Out-Null
Start-Process -FilePath $browser -ArgumentList @(
    "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=$DebugPort",
    "--user-data-dir=`"$profile`"",
    "--no-first-run",
    "--no-default-browser-check",
    $Url
) | Out-Null

$deadline = [DateTime]::UtcNow.AddSeconds(20)
while ([DateTime]::UtcNow -lt $deadline) {
    if (Test-DebugEndpoint) {
        Write-Host "Visible Maitu browser started with CDP at http://127.0.0.1:$DebugPort."
        Write-Host "Complete login in the browser before running the Browser-use probe."
        return
    }
    Start-Sleep -Milliseconds 500
}

throw "The browser opened, but its CDP endpoint did not become ready."
