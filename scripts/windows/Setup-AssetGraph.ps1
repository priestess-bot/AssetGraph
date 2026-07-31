[CmdletBinding()]
param(
    [switch]$SkipBrowserUse,
    [switch]$SkipFrontendBuild,
    [switch]$SkipToolInstall,
    [string]$PostgresSuperPassword = "assetgraph"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$minioVersion = "RELEASE.2025-04-22T22-12-26Z"
$minioSha256 = "2ceb3b3d68bdf1c4def9702cb02c5c8adb235197d1c8f2eaad24136833ab9a57"
$minioUrl = "https://dl.min.io/server/minio/release/windows-amd64/archive/minio.$minioVersion"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

function Resolve-Executable {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string[]]$Candidates = @()
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Resolve-PostgresBin {
    $psql = Get-Command psql -ErrorAction SilentlyContinue
    if ($null -ne $psql) {
        return Split-Path -Parent $psql.Source
    }

    $postgresRoot = Join-Path $env:ProgramFiles "PostgreSQL"
    if (Test-Path -LiteralPath $postgresRoot) {
        $install = Get-ChildItem -LiteralPath $postgresRoot -Directory |
            Sort-Object { try { [version]$_.Name } catch { [version]"0.0" } } -Descending |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "bin\psql.exe") } |
            Select-Object -First 1
        if ($null -ne $install) {
            return Join-Path $install.FullName "bin"
        }
    }
    return $null
}

function Resolve-WinGetPackageExecutable {
    param([Parameter(Mandatory = $true)][string]$Name)

    $packagesRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (-not (Test-Path -LiteralPath $packagesRoot)) {
        return $null
    }
    $match = Get-ChildItem -LiteralPath $packagesRoot -Recurse -File -Filter "$Name.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $match) {
        return $match.FullName
    }
    return $null
}

$winget = Resolve-Executable -Name "winget"
$uv = Resolve-Executable -Name "uv" -Candidates @(
    (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\uv.exe")
)
if (-not $uv) {
    if ($SkipToolInstall -or -not $winget) {
        throw "uv is missing. Install astral-sh.uv or rerun without -SkipToolInstall."
    }
    Invoke-Checked -FilePath $winget -ArgumentList @(
        "install", "--id", "astral-sh.uv", "--exact", "--source", "winget",
        "--accept-package-agreements", "--accept-source-agreements", "--silent"
    )
    $uv = Resolve-Executable -Name "uv" -Candidates @(
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\uv.exe")
    )
}
if (-not $uv) {
    throw "uv installation completed but uv.exe could not be located."
}

$python = Resolve-Executable -Name "python"
$npm = Resolve-Executable -Name "npm.cmd" -Candidates @(
    (Join-Path $env:ProgramFiles "nodejs\npm.cmd")
)
$git = Resolve-Executable -Name "git" -Candidates @(
    (Join-Path $env:ProgramFiles "Git\cmd\git.exe")
)
if (-not $python -or -not $npm -or -not $git) {
    throw "Python, Node.js/npm, and Git are required before setup can continue."
}

$env:PATH = "$(Split-Path -Parent $uv);$(Split-Path -Parent $git);$env:PATH"

$ffmpeg = Resolve-Executable -Name "ffmpeg" -Candidates @(
    (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\ffmpeg.exe")
)
if (-not $ffmpeg) {
    $ffmpeg = Resolve-WinGetPackageExecutable -Name "ffmpeg"
}
if (-not $ffmpeg) {
    if ($SkipToolInstall -or -not $winget) {
        throw "FFmpeg is missing. Install Gyan.FFmpeg or rerun without -SkipToolInstall."
    }
    Invoke-Checked -FilePath $winget -ArgumentList @(
        "install", "--id", "Gyan.FFmpeg", "--exact", "--source", "winget",
        "--accept-package-agreements", "--accept-source-agreements", "--silent"
    )
    $ffmpeg = Resolve-Executable -Name "ffmpeg" -Candidates @(
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\ffmpeg.exe")
    )
    if (-not $ffmpeg) {
        $ffmpeg = Resolve-WinGetPackageExecutable -Name "ffmpeg"
    }
}
if (-not $ffmpeg -or -not (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $ffmpeg) "ffprobe.exe"))) {
    throw "FFmpeg installation completed but ffmpeg.exe and ffprobe.exe could not both be located."
}
$env:PATH = "$(Split-Path -Parent $ffmpeg);$env:PATH"

$postgresBin = Resolve-PostgresBin
if (-not $postgresBin) {
    if ($SkipToolInstall -or -not $winget) {
        throw "PostgreSQL 16 is missing. Install it or rerun without -SkipToolInstall."
    }
    $installerArguments = "--mode unattended --unattendedmodeui none --superpassword `"$PostgresSuperPassword`" --servicepassword `"$PostgresSuperPassword`" --serverport 5432 --disable-components stackbuilder"
    Invoke-Checked -FilePath $winget -ArgumentList @(
        "install", "--id", "PostgreSQL.PostgreSQL.16", "--exact", "--source", "winget",
        "--accept-package-agreements", "--accept-source-agreements", "--silent",
        "--override", $installerArguments
    )
    $postgresBin = Resolve-PostgresBin
}
if (-not $postgresBin) {
    throw "PostgreSQL installation completed but its bin directory could not be located."
}

$postgresService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    Select-Object -First 1
if ($null -eq $postgresService) {
    throw "No PostgreSQL Windows service was found."
}
if ($postgresService.Status -ne "Running") {
    Start-Service -Name $postgresService.Name
    $postgresService.WaitForStatus("Running", [TimeSpan]::FromSeconds(30))
}

$env:PGPASSWORD = $PostgresSuperPassword
$psql = Join-Path $postgresBin "psql.exe"
$createdb = Join-Path $postgresBin "createdb.exe"
$roleResult = @(& $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='assetgraph'")
if ($LASTEXITCODE -ne 0) {
    throw "Unable to authenticate to PostgreSQL as postgres. Pass -PostgresSuperPassword with the installed password."
}
if (($roleResult -join "").Trim() -ne "1") {
    Invoke-Checked -FilePath $psql -ArgumentList @(
        "-h", "127.0.0.1", "-p", "5432", "-U", "postgres", "-d", "postgres",
        "-v", "ON_ERROR_STOP=1", "-c", "CREATE ROLE assetgraph WITH LOGIN PASSWORD 'assetgraph'"
    )
} else {
    Invoke-Checked -FilePath $psql -ArgumentList @(
        "-h", "127.0.0.1", "-p", "5432", "-U", "postgres", "-d", "postgres",
        "-v", "ON_ERROR_STOP=1", "-c", "ALTER ROLE assetgraph WITH LOGIN PASSWORD 'assetgraph'"
    )
}

$databaseResult = @(& $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='assetgraph'")
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect local PostgreSQL databases."
}
if (($databaseResult -join "").Trim() -ne "1") {
    Invoke-Checked -FilePath $createdb -ArgumentList @(
        "-h", "127.0.0.1", "-p", "5432", "-U", "postgres", "-O", "assetgraph", "assetgraph"
    )
}
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

Push-Location $repoRoot
try {
    Invoke-Checked -FilePath $python -ArgumentList @("scripts\bootstrap_reproducible.py", "--skip-skill")

    if (-not $SkipBrowserUse) {
        Invoke-Checked -FilePath $python -ArgumentList @(
            "scripts\bootstrap_reproducible.py", "--skip-dependencies", "--skip-skill", "--with-browser-use"
        )
    }

    if (-not $SkipFrontendBuild) {
        Push-Location (Join-Path $repoRoot "frontend")
        try {
            Invoke-Checked -FilePath $npm -ArgumentList @("ci")
            Invoke-Checked -FilePath $npm -ArgumentList @("run", "build")
        } finally {
            Pop-Location
        }
    }

    $minioBin = Join-Path $repoRoot ".external\bin"
    $minio = Join-Path $minioBin "minio.exe"
    New-Item -ItemType Directory -Force -Path $minioBin | Out-Null
    $downloadRequired = -not (Test-Path -LiteralPath $minio)
    if (-not $downloadRequired) {
        $downloadRequired = (Get-FileHash -LiteralPath $minio -Algorithm SHA256).Hash.ToLowerInvariant() -ne $minioSha256
    }
    if ($downloadRequired) {
        $temporary = "$minio.download"
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        Invoke-WebRequest -UseBasicParsing -Uri $minioUrl -OutFile $temporary
        $actualHash = (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $minioSha256) {
            Remove-Item -LiteralPath $temporary -Force
            throw "Downloaded MinIO checksum mismatch."
        }
        Move-Item -LiteralPath $temporary -Destination $minio -Force
    }

    foreach ($relativePath in @(
        "data\maitu-mirror",
        "data\material-analysis",
        "data\live-research",
        "data\video-productions",
        "data\minio"
    )) {
        New-Item -ItemType Directory -Force -Path (Join-Path $repoRoot $relativePath) | Out-Null
    }

    $backendPython = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
    Invoke-Checked -FilePath $backendPython -ArgumentList @("scripts\apply_migrations.py")
} finally {
    Pop-Location
}

Write-Host "AssetGraph Windows setup is complete."
Write-Host "Start development services with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\windows\Start-AssetGraph.ps1"
