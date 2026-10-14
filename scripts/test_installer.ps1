<#
安装/升级/卸载验工入口，仅在未安装同产品的干净 Windows 测试机使用。
读取 PackageDir 发布清单，在 Workspace 中建立唯一安装目录；UpgradeFromSetup 可验证旧版升级。
会实际运行安装器、修改安装注册表及快捷方式，并在旧数据目录写入唯一校验标记。
最终只清理自己的标记，不删除用户数据；本脚本不属于普通源码回归。
#>
param(
    [Parameter(Mandatory=$true)][string]$PackageDir,
    [Parameter(Mandatory=$true)][string]$Workspace,
    [string]$UpgradeFromSetup
)
$ErrorActionPreference = 'Stop'
function Invoke-CheckedProcess {
    <#
    隐藏启动一个验工子进程并等待退出，非零退出码立即报错。
    超时时只终止本次启动的进程树（含单文件解包子进程），不按进程名称结束其他应用。
    #>
    param([string]$FilePath, [string[]]$Arguments, [int]$TimeoutSeconds = 120)
    $taskChild = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (-not $taskChild.WaitForExit($TimeoutSeconds * 1000)) {
        # 只清理本次创建的进程树，保留其他正在运行的用户进程。
        & taskkill.exe /PID $taskChild.Id /T /F | Out-Null
        throw "Process timed out after ${TimeoutSeconds}s: $FilePath"
    }
    $taskChild.Refresh()
    if ($taskChild.ExitCode -ne 0) { throw "Process failed with exit code $($taskChild.ExitCode): $FilePath" }
}
$taskPackageDir = (Resolve-Path -LiteralPath $PackageDir).Path
$taskWorkspace = [IO.Path]::GetFullPath($Workspace)
$taskRegistryKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8A3CAB17-B864-4379-9BAA-A2C7AE85706D}_is1'
# 安装会修改共享注册表与开始菜单，因此先拒绝已有产品安装，避免覆盖真实环境。
if (Test-Path -LiteralPath $taskRegistryKey) { throw 'An installed Sariana/TypingTracker exists; use a clean Windows test machine' }
$taskPackages = @(Get-ChildItem -LiteralPath (Join-Path $taskPackageDir 'assets') -Filter '*-setup.exe')
if ($taskPackages.Count -ne 1) { throw 'Expected exactly one installer' }
$taskInstallDir = Join-Path $taskWorkspace ('install-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $taskWorkspace | Out-Null
$taskManifest = Get-Content -LiteralPath (Join-Path $taskPackageDir 'payload\release-manifest.json') | ConvertFrom-Json
$taskExeName = if ($taskManifest.executable) { [string]$taskManifest.executable } else { 'TypingTracker.exe' }
if ($taskExeName -notmatch '^[A-Za-z][A-Za-z0-9_-]{0,40}\.exe$') { throw 'Invalid manifest executable' }
$taskExpectedExe = Join-Path $taskPackageDir ('payload\' + $taskExeName)
$taskProgramsDir = [Environment]::GetFolderPath('Programs')
$taskLegacyShortcut = Join-Path $taskProgramsDir 'TypingTracker\TypingTracker.lnk'
$taskNewShortcut = Join-Path $taskProgramsDir (($taskExeName -replace '\.exe$', '') + '\' + ($taskExeName -replace '\.exe$', '.lnk'))
if ($UpgradeFromSetup -and ((Test-Path -LiteralPath $taskLegacyShortcut) -or (Test-Path -LiteralPath $taskNewShortcut))) {
    throw 'An existing product shortcut exists; use a clean Windows test machine'
}
$taskDataDir = Join-Path $env:APPDATA 'TypingTracker'
# 用唯一标记验证升级和卸载保留数据，不读取用户统计或清理整个旧数据目录。
New-Item -ItemType Directory -Force -Path $taskDataDir | Out-Null
$taskSentinel = Join-Path $taskDataDir ('release-smoke-' + [guid]::NewGuid().ToString('N') + '.txt')
'preserve-user-records' | Set-Content -LiteralPath $taskSentinel
$taskSentinelHash = (Get-FileHash -LiteralPath $taskSentinel).Hash
try {
    $taskArguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS','/TASKS=',('/DIR="' + $taskInstallDir + '"'))
    if ($UpgradeFromSetup) {
        $taskOldSetup = (Resolve-Path -LiteralPath $UpgradeFromSetup).Path
        # 安装配置禁用分组页面会忽略 /GROUP；此处检查产品实际快捷方式路径。
        $taskOldArguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/TASKS=',('/DIR="' + $taskInstallDir + '"'))
        Invoke-CheckedProcess -FilePath $taskOldSetup -Arguments $taskOldArguments
        $taskOldExe = Join-Path $taskInstallDir 'TypingTracker.exe'
        if (Test-Path -LiteralPath $taskOldExe) {
            if (-not (Test-Path -LiteralPath $taskLegacyShortcut)) { throw 'Legacy shortcut missing' }
        } else {
            $taskOldExe = Join-Path $taskInstallDir $taskExeName
            if (-not (Test-Path -LiteralPath $taskOldExe)) { throw 'Previous installation missing' }
            if (-not (Test-Path -LiteralPath $taskNewShortcut)) { throw 'Previous Sariana shortcut missing' }
        }
        # 升级时省略 /DIR，验证固定 AppId 自动沿用旧版安装位置。
        $taskArguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/TASKS=')
    }
    Invoke-CheckedProcess -FilePath $taskPackages[0].FullName -Arguments $taskArguments
    $taskInstalledExe = Join-Path $taskInstallDir $taskExeName
    if ((Get-FileHash -LiteralPath $taskInstalledExe).Hash -ne (Get-FileHash -LiteralPath $taskExpectedExe).Hash) { throw 'Installed executable differs from verified payload' }
    Invoke-CheckedProcess -FilePath $taskInstalledExe -Arguments '--help' -TimeoutSeconds 60
    $taskRecord = Get-ItemProperty -LiteralPath $taskRegistryKey
    if ($taskRecord.DisplayVersion -ne $taskManifest.version) { throw 'Uninstall record version mismatch' }
    if ($taskManifest.product_name -and -not $taskRecord.DisplayName.StartsWith($taskManifest.product_name)) { throw 'Uninstall display name mismatch' }
    if ($taskRecord.InstallLocation.TrimEnd('\') -ne $taskInstallDir) { throw 'Installation location changed' }
    if ([version]$taskManifest.version -ge [version]'0.9.5' -and $taskManifest.product_name -eq 'Sariana') {
        $taskUpdaterCheck = Join-Path $PSScriptRoot 'verify_release_updates.py'
        python -B $taskUpdaterCheck --exe $taskInstalledExe --expected-package-version $taskManifest.version --detect-installation-only --require-installed
        if ($LASTEXITCODE -ne 0) { throw 'Frozen updater installation detection failed' }
    }
    if ($taskExeName -ne 'TypingTracker.exe' -and (Test-Path -LiteralPath (Join-Path $taskInstallDir 'TypingTracker.exe'))) { throw 'Legacy executable remains after rename' }
    if ($UpgradeFromSetup) {
        if (Test-Path -LiteralPath $taskLegacyShortcut) { throw 'Legacy shortcut remains after rename' }
        if (-not (Test-Path -LiteralPath $taskNewShortcut)) { throw 'Renamed shortcut missing' }
        $taskShell = New-Object -ComObject WScript.Shell
        if ($taskShell.CreateShortcut($taskNewShortcut).TargetPath -ne $taskInstalledExe) { throw 'Renamed shortcut target mismatch' }
    }
    $taskUninstall = Join-Path $taskInstallDir 'unins000.exe'
    Invoke-CheckedProcess -FilePath $taskUninstall -Arguments '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'
    if (Test-Path -LiteralPath $taskInstalledExe) { throw 'Uninstall left the application executable' }
    if (Test-Path -LiteralPath $taskRegistryKey) { throw 'Uninstall left its registry entry' }
    if ($UpgradeFromSetup -and (Test-Path -LiteralPath $taskNewShortcut)) { throw 'Uninstall left the renamed shortcut' }
    if (-not (Test-Path -LiteralPath $taskSentinel) -or (Get-FileHash -LiteralPath $taskSentinel).Hash -ne $taskSentinelHash) { throw 'Uninstall changed user data' }
    Write-Output "Installer verified: version=$($taskManifest.version), payload matches, bootstrap=0, uninstall preserves data"
    if ($UpgradeFromSetup) { Write-Output 'Upgrade verified: previous location reused, old executable/shortcut removed, Sariana shortcut target matches, data preserved' }
} finally {
    # 无论断言成败，只移除本次唯一标记，绝不删除用户数据目录。
    if (Test-Path -LiteralPath $taskSentinel) { Remove-Item -LiteralPath $taskSentinel }
}
