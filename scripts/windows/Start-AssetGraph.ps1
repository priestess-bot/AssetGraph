[CmdletBinding()]
param(
    [switch]$Production,
    [switch]$NoBrowser,
    [switch]$SkipMinio
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runRoot = Join-Path $repoRoot ".run\windows"
$logRoot = Join-Path $runRoot "logs"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

if ($null -eq (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    $packagesRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $packagesRoot) {
        $ffmpeg = Get-ChildItem -LiteralPath $packagesRoot -Recurse -File -Filter "ffmpeg.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $ffmpeg) {
            $env:PATH = "$($ffmpeg.DirectoryName);$env:PATH"
        }
    }
}

function Test-HttpEndpoint {
    param([Parameter(Mandatory = $true)][string]$Uri)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Test-TcpPort {
    param([Parameter(Mandatory = $true)][int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return $task.Wait(400) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Wait-HttpEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$TimeoutSeconds = 60
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-HttpEndpoint -Uri $Uri) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not become ready within $TimeoutSeconds seconds. Check $logRoot."
}

function Start-TrackedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    $stdout = Join-Path $logRoot "$Name.stdout.log"
    $stderr = Join-Path $logRoot "$Name.stderr.log"
    $process = Start-Process -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    $record = [ordered]@{
        name = $Name
        process_id = $process.Id
        started_at = $process.StartTime.ToUniversalTime().ToString("O")
        executable = $FilePath
    }
    $record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runRoot "$Name.json") -Encoding UTF8
}

$postgresService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    Select-Object -First 1
if ($null -eq $postgresService) {
    throw "PostgreSQL is not installed. Run Setup-AssetGraph.ps1 first."
}
if ($postgresService.Status -ne "Running") {
    Start-Service -Name $postgresService.Name
    $postgresService.WaitForStatus("Running", [TimeSpan]::FromSeconds(30))
}

$env:NO_PROXY = "127.0.0.1,localhost,$env:NO_PROXY".TrimEnd(",")
$env:no_proxy = $env:NO_PROXY

if (-not $SkipMinio) {
    $minioHealth = "http://127.0.0.1:9000/minio/health/live"
    if (-not (Test-HttpEndpoint -Uri $minioHealth)) {
        if (Test-TcpPort -Port 9000) {
            throw "Port 9000 is occupied by a service that is not the expected MinIO instance."
        }
        $minio = Join-Path $repoRoot ".external\bin\minio.exe"
        if (-not (Test-Path -LiteralPath $minio)) {
            throw "MinIO is missing. Run Setup-AssetGraph.ps1 first."
        }
        $minioData = Join-Path $repoRoot "data\minio"
        New-Item -ItemType Directory -Force -Path $minioData | Out-Null
        $env:MINIO_ROOT_USER = "assetgraph"
        $env:MINIO_ROOT_PASSWORD = "assetgraph-secret"
        Start-TrackedProcess -Name "minio" -FilePath $minio -WorkingDirectory $repoRoot -ArgumentList @(
            "server",
            "`"$minioData`"",
            "--address",
            "127.0.0.1:9000",
            "--console-address",
            "127.0.0.1:9001"
        )
        Wait-HttpEndpoint -Uri $minioHealth -Name "MinIO"
    }
}

$backendHealth = "http://127.0.0.1:8000/health"
if (-not (Test-HttpEndpoint -Uri $backendHealth)) {
    if (Test-TcpPort -Port 8000) {
        throw "Port 8000 is occupied by a service that is not AssetGraph."
    }
    $backendPython = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $backendPython)) {
        throw "The backend environment is missing. Run Setup-AssetGraph.ps1 first."
    }
    $backendArguments = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
    if (-not $Production) {
        $backendArguments += @("--reload", "--reload-dir", "app")
    }
    Start-TrackedProcess -Name "backend" -FilePath $backendPython -ArgumentList $backendArguments -WorkingDirectory (Join-Path $repoRoot "backend")
    Wait-HttpEndpoint -Uri $backendHealth -Name "AssetGraph backend"
}

if ($Production) {
    $applicationUrl = "http://127.0.0.1:8000/console/"
    Wait-HttpEndpoint -Uri $applicationUrl -Name "AssetGraph console"
} else {
    $frontendUrl = "http://127.0.0.1:5173/console/"
    if (-not (Test-HttpEndpoint -Uri $frontendUrl)) {
        if (Test-TcpPort -Port 5173) {
            throw "Port 5173 is occupied by a service that is not the AssetGraph frontend."
        }
        $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if ($null -eq $npm) {
            $npmPath = Join-Path $env:ProgramFiles "nodejs\npm.cmd"
            if (-not (Test-Path -LiteralPath $npmPath)) {
                throw "npm.cmd is missing. Install Node.js and rerun setup."
            }
        } else {
            $npmPath = $npm.Source
        }
        Start-TrackedProcess -Name "frontend" -FilePath $npmPath -ArgumentList @("run", "dev") -WorkingDirectory (Join-Path $repoRoot "frontend")
        Wait-HttpEndpoint -Uri $frontendUrl -Name "AssetGraph frontend"
    }
    $applicationUrl = $frontendUrl
}

Write-Host "AssetGraph is running."
Write-Host "  Console: $applicationUrl"
Write-Host "  API:     http://127.0.0.1:8000/docs"
Write-Host "  MinIO:   http://127.0.0.1:9001"
Write-Host "  Logs:    $logRoot"

if (-not $NoBrowser) {
    Start-Process $applicationUrl
}
