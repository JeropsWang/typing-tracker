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
$taskQtRuntimeDir = python -c "from pathlib import Path; import PySide6; print(Path(PySide6.__file__).parent)"
if ($LASTEXITCODE -ne 0) { throw 'Cannot locate PySide6 runtime' }

# 运行必需素材全部位于 app/ui/assets（--add-data 递归收集整棵树，新增子目录无需再加参数）：
#   background.png / lettering.svg / nav/*.svg            交付 v1
#   paper/deckle-paper.png                                交付 v2 撕边纸张（透明 PNG）
#   lettering/{today,stats,growth,settings,training}.svg  交付 v2 四页转曲艺术标题
#   decorations/*.svg                                     交付 v2 八个装饰贴纸
#   app_icon.py / icons.py                                程序化图标与线性图标
python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name Sariana `
    --paths "$Root\.deps" `
    --exclude-module pygame `
    --add-binary "$taskQtRuntimeDir\*140*.dll;." `
    --runtime-hook "$Root\scripts\pyinstaller_runtime.py" `
    --icon "$Root\app.ico" `
    --add-data "config;config" `
    --add-data "app/theme/themes;app/theme/themes" `
    --add-data "app/ui/assets;app/ui/assets" `
    --add-data "app/storage/schema.sql;app/storage" `
    main.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "BUILD FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "DONE: $Root\dist\Sariana.exe"
