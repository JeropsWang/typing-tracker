# Build script (M4): PyInstaller single-file exe
# Usage: powershell -File scripts\build.ps1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".deps\PyInstaller")) {
    Write-Host 'Installing PyInstaller into .deps ...'
    python scripts\fetch_deps.py pyinstaller pywin32-ctypes pefile altgraph pyinstaller-hooks-contrib setuptools
}

$env:PYTHONPATH = "$Root\.deps"

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name TypingTracker `
    --paths "$Root\.deps" `
    --exclude-module pygame `
    --icon "$Root\app.ico" `
    --add-data "config;config" `
    --add-data "app/theme/themes;app/theme/themes" `
    --add-data "app/storage/schema.sql;app/storage" `
    main.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "BUILD FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "DONE: $Root\dist\TypingTracker.exe"
