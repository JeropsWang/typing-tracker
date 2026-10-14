# 本机搜索部署入口：在 .local/searxng 准备配置，验证 Compose 后启动 Linux 容器并检查 JSON 搜索。
# -PrepareOnly 仍会准备本地配置并验证 Compose，但跳过容器启动和网络就绪检查。
param([switch]$PrepareOnly)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$searchRuntime = Join-Path $projectRoot '.local/searxng'
$configDir = Join-Path $searchRuntime 'config'
$dataDir = Join-Path $searchRuntime 'data'
$settingsFile = Join-Path $configDir 'settings.yml'
$composeFile = Join-Path $PSScriptRoot 'compose.yaml'
New-Item -ItemType Directory -Path $configDir, $dataDir -Force | Out-Null

if (-not (Test-Path -LiteralPath $settingsFile)) {
    # 仅首次生成随机服务密钥，保留已存在配置，不把密钥打印到终端。
    $randomBytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($randomBytes) } finally { $generator.Dispose() }
    $serverSecret = ([System.BitConverter]::ToString($randomBytes)).Replace('-', '').ToLowerInvariant()
    $template = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot 'settings.example.yml'))
    $configured = $template.Replace('__GENERATED_SECRET__', $serverSecret)
    [System.IO.File]::WriteAllText($settingsFile, $configured, (New-Object System.Text.UTF8Encoding $false))
    Write-Host 'Initialized local search configuration; existing files will be preserved.'
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCommand) { throw 'Install Docker Desktop and select Linux containers first.' }
$dockerExe = $dockerCommand.Source
& $dockerExe compose -f $composeFile config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose configuration validation failed.' }
if ($PrepareOnly) {
    Write-Host 'Configuration prepared and validated. No container was started.'
    return
}

$containerOS = & $dockerExe info --format '{{.OSType}}'
# 镜像依赖 Linux 引擎，启动前检查当前 Docker 模式，避免误用 Windows 容器。
if ($LASTEXITCODE -ne 0 -or $containerOS -ne 'linux') {
    throw 'Start Docker Desktop and wait until the Linux container engine is ready.'
}
& $dockerExe compose -f $composeFile up -d
if ($LASTEXITCODE -ne 0) { throw 'Could not start SearXNG. Check Docker network access and port 8080.' }

$ready = $false
# 有界轮询仅确认本机 Web 服务；随后 JSON 探测单独检查搜索格式和上游可用性。
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $page = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/' -UseBasicParsing -TimeoutSec 3
        if ($page.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    throw 'SearXNG did not become ready. Run docker compose -f deploy/searxng/compose.yaml logs --tail 50.'
}
Write-Host 'SearXNG is ready: http://127.0.0.1:8080'
try {
    $searchResult = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/search?q=SearXNG&format=json' -TimeoutSec 20
    if ($null -eq $searchResult.results) { throw 'No results field in JSON response.' }
    $resultCount = @($searchResult.results).Count
    Write-Host "JSON search is available. Results returned: $resultCount"
    if ($resultCount -eq 0) { Write-Warning 'Search returned no results. Check upstream engine connectivity in Docker.' }
} catch {
    Write-Warning 'Web service is ready, but JSON search could not be verified. Check formats and upstream connectivity.'
}
