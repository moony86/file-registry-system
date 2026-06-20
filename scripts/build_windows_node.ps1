param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PackageDir = Join-Path $RepoRoot "dist\FSYSNode"
$PyInstallerDist = Join-Path $RepoRoot "dist\_pyinstaller_node"
$PyInstallerWork = Join-Path $RepoRoot "build\pyinstaller-node"
$StorageApp = Join-Path $RepoRoot "storage-node\app.py"
$StoragePath = Join-Path $RepoRoot "storage-node"

Write-Host "Building FSYS Windows Storage Node package..."

if (Test-Path $PackageDir) {
    Remove-Item -LiteralPath $PackageDir -Recurse -Force
}
if (Test-Path $PyInstallerDist) {
    Remove-Item -LiteralPath $PyInstallerDist -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null
New-Item -ItemType Directory -Force -Path $PyInstallerWork | Out-Null

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --console `
    --name fsys-node `
    --distpath $PyInstallerDist `
    --workpath $PyInstallerWork `
    --specpath $PyInstallerWork `
    --paths $StoragePath `
    --hidden-import flask `
    --hidden-import flask_cors `
    --hidden-import requests `
    --hidden-import dotenv `
    --hidden-import routes.debug `
    --hidden-import routes.files `
    --hidden-import routes.local `
    --hidden-import routes.pages `
    --hidden-import routes.status `
    --hidden-import services.auth `
    --hidden-import services.hashing `
    --hidden-import services.heartbeat `
    --hidden-import services.master_client `
    --hidden-import services.media `
    --hidden-import services.probe `
    --hidden-import services.registration `
    --hidden-import services.space_cache `
    --hidden-import services.thumbnails `
    $StorageApp

$BuiltDir = Join-Path $PyInstallerDist "fsys-node"
if (!(Test-Path $BuiltDir)) {
    throw "PyInstaller output not found: $BuiltDir"
}

Copy-Item -Path (Join-Path $BuiltDir "*") -Destination $PackageDir -Recurse -Force

foreach ($dir in @("data", "shared_space", "thumbnails", "logs")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $PackageDir $dir) | Out-Null
}

Copy-Item -LiteralPath (Join-Path $RepoRoot "storage-node\.env.example") -Destination (Join-Path $PackageDir ".env.example") -Force

@'
@echo off
cd /d "%~dp0"
fsys-node.exe
pause
'@ | Set-Content -Path (Join-Path $PackageDir "start_node.bat") -Encoding ASCII

@'
@echo off
cd /d "%~dp0"
curl http://127.0.0.1:5001/api/status
if errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5001/api/status | Select-Object -ExpandProperty Content"
)
pause
'@ | Set-Content -Path (Join-Path $PackageDir "check_status.bat") -Encoding ASCII

@'
# FSYS Windows Storage Node

1. Edit `.env` after first run, or copy `.env.example` to `.env` manually.
2. Set `MASTER_URLS` to your Master Node addresses.
3. Set `LOCAL_LIBRARY_DIRS` to folders this node may browse, separated by commas.
4. Run `start_node.bat`.
5. Run `check_status.bat` to verify `/api/status`.

The first run creates `.env` from `.env.example` if `.env` is missing.

Runtime folders:
- `data/` stable node identity
- `shared_space/` managed cached files
- `thumbnails/` generated thumbnails
- `logs/` `node.log`

Windows Service, setup wizard, auto update, and signed installer are planned later.
'@ | Set-Content -Path (Join-Path $PackageDir "README_NODE_WINDOWS.md") -Encoding UTF8

if (Test-Path $PyInstallerDist) {
    Remove-Item -LiteralPath $PyInstallerDist -Recurse -Force
}

Write-Host "Done: $PackageDir"
