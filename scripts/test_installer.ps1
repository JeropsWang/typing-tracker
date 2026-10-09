param(
    [Parameter(Mandatory=$true)][string]$PackageDir,
    [Parameter(Mandatory=$true)][string]$Workspace
)
$ErrorActionPreference = 'Stop'
$taskPackageDir = (Resolve-Path -LiteralPath $PackageDir).Path
$taskWorkspace = [IO.Path]::GetFullPath($Workspace)
$taskRegistryKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8A3CAB17-B864-4379-9BAA-A2C7AE85706D}_is1'
if (Test-Path -LiteralPath $taskRegistryKey) { throw 'An installed TypingTracker exists; use a clean Windows test machine' }
$taskPackages = @(Get-ChildItem -LiteralPath (Join-Path $taskPackageDir 'assets') -Filter '*-setup.exe')
if ($taskPackages.Count -ne 1) { throw 'Expected exactly one installer' }
$taskInstallDir = Join-Path $taskWorkspace ('install-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $taskWorkspace | Out-Null
$taskExpectedExe = Join-Path $taskPackageDir 'payload\TypingTracker.exe'
$taskDataDir = Join-Path $env:APPDATA 'TypingTracker'
New-Item -ItemType Directory -Force -Path $taskDataDir | Out-Null
$taskSentinel = Join-Path $taskDataDir ('release-smoke-' + [guid]::NewGuid().ToString('N') + '.txt')
'preserve-user-records' | Set-Content -LiteralPath $taskSentinel
$taskSentinelHash = (Get-FileHash -LiteralPath $taskSentinel).Hash
try {
    $taskProcess = Start-Process -FilePath $taskPackages[0].FullName -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS','/TASKS=',('/DIR="' + $taskInstallDir + '"') -WindowStyle Hidden -Wait -PassThru
    if ($taskProcess.ExitCode -ne 0) { throw "Installation failed: $($taskProcess.ExitCode)" }
    $taskInstalledExe = Join-Path $taskInstallDir 'TypingTracker.exe'
    if ((Get-FileHash -LiteralPath $taskInstalledExe).Hash -ne (Get-FileHash -LiteralPath $taskExpectedExe).Hash) { throw 'Installed executable differs from verified payload' }
    $taskBootstrap = Start-Process -FilePath $taskInstalledExe -ArgumentList '--help' -WindowStyle Hidden -Wait -PassThru
    if ($taskBootstrap.ExitCode -ne 0) { throw 'Installed executable bootstrap failed' }
    $taskRecord = Get-ItemProperty -LiteralPath $taskRegistryKey
    $taskManifest = Get-Content -LiteralPath (Join-Path $taskPackageDir 'payload\release-manifest.json') | ConvertFrom-Json
    if ($taskRecord.DisplayVersion -ne $taskManifest.version) { throw 'Uninstall record version mismatch' }
    $taskUninstall = Join-Path $taskInstallDir 'unins000.exe'
    $taskProcess = Start-Process -FilePath $taskUninstall -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -WindowStyle Hidden -Wait -PassThru
    if ($taskProcess.ExitCode -ne 0) { throw "Uninstall failed: $($taskProcess.ExitCode)" }
    if (Test-Path -LiteralPath $taskInstalledExe) { throw 'Uninstall left the application executable' }
    if (Test-Path -LiteralPath $taskRegistryKey) { throw 'Uninstall left its registry entry' }
    if (-not (Test-Path -LiteralPath $taskSentinel) -or (Get-FileHash -LiteralPath $taskSentinel).Hash -ne $taskSentinelHash) { throw 'Uninstall changed user data' }
    Write-Output "Installer verified: version=$($taskManifest.version), payload matches, bootstrap=0, uninstall preserves data"
} finally {
    # Remove only our uniquely named test sentinel; never remove the user's data directory.
    if (Test-Path -LiteralPath $taskSentinel) { Remove-Item -LiteralPath $taskSentinel }
}
