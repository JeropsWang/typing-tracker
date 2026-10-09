param(
    [Parameter(Mandatory=$true)][string]$PackageDir,
    [Parameter(Mandatory=$true)][string]$Workspace,
    [string]$UpgradeFromSetup
)
$ErrorActionPreference = 'Stop'
function Invoke-CheckedProcess {
    param([string]$FilePath, [string[]]$Arguments, [int]$TimeoutSeconds = 120)
    $taskChild = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (-not $taskChild.WaitForExit($TimeoutSeconds * 1000)) {
        # Kill only the process tree started by this test, including one-file extraction children.
        & taskkill.exe /PID $taskChild.Id /T /F | Out-Null
        throw "Process timed out after ${TimeoutSeconds}s: $FilePath"
    }
    $taskChild.Refresh()
    if ($taskChild.ExitCode -ne 0) { throw "Process failed with exit code $($taskChild.ExitCode): $FilePath" }
}
$taskPackageDir = (Resolve-Path -LiteralPath $PackageDir).Path
$taskWorkspace = [IO.Path]::GetFullPath($Workspace)
$taskRegistryKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8A3CAB17-B864-4379-9BAA-A2C7AE85706D}_is1'
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
New-Item -ItemType Directory -Force -Path $taskDataDir | Out-Null
$taskSentinel = Join-Path $taskDataDir ('release-smoke-' + [guid]::NewGuid().ToString('N') + '.txt')
'preserve-user-records' | Set-Content -LiteralPath $taskSentinel
$taskSentinelHash = (Get-FileHash -LiteralPath $taskSentinel).Hash
try {
    $taskArguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS','/TASKS=',('/DIR="' + $taskInstallDir + '"'))
    if ($UpgradeFromSetup) {
        $taskOldSetup = (Resolve-Path -LiteralPath $UpgradeFromSetup).Path
        # DisableProgramGroupPage=yes ignores /GROUP. Exercise real product groups.
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
        # Omit /DIR to verify that the stable AppId reuses the previous location.
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
    # Remove only our uniquely named test sentinel; never remove the user's data directory.
    if (Test-Path -LiteralPath $taskSentinel) { Remove-Item -LiteralPath $taskSentinel }
}
