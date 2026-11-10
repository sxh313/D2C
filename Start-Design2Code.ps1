$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$envPath = Join-Path $projectRoot '.env'
$backendDir = Join-Path $projectRoot 'screenshot-to-code\backend'
$frontendDir = Join-Path $projectRoot 'screenshot-to-code\frontend'
# Keep the process registry in a stable location even if .env changes while running.
$processFile = Join-Path $projectRoot 'runtime\workbench-processes.json'

if (-not (Test-Path -LiteralPath $envPath)) { throw '找不到根目录 .env。' }
$settings = @{}
foreach ($line in [System.IO.File]::ReadAllLines($envPath)) {
    if ($line -match '^\s*(D2C_WEB_HOST|D2C_WEB_PORT|D2C_BACKEND_HOST|D2C_BACKEND_PORT|D2C_FIGMA_MODE|D2C_RUNTIME_DIR)\s*=\s*(.*?)\s*$') {
        $settings[$Matches[1]] = $Matches[2].Trim('"', "'")
    }
}
$runtimeSetting = if ($settings.D2C_RUNTIME_DIR) { $settings.D2C_RUNTIME_DIR } else { './runtime' }
if ($runtimeSetting -eq '~') { $runtimeSetting = $env:USERPROFILE }
elseif ($runtimeSetting -match '^~[/\\]') { $runtimeSetting = Join-Path $env:USERPROFILE $runtimeSetting.Substring(2) }
$runtimeDir = if ([IO.Path]::IsPathRooted($runtimeSetting)) { [IO.Path]::GetFullPath($runtimeSetting) } else { [IO.Path]::GetFullPath((Join-Path $projectRoot $runtimeSetting)) }
$webHost = if ($settings.D2C_WEB_HOST) { $settings.D2C_WEB_HOST } else { '127.0.0.1' }
$backendHost = if ($settings.D2C_BACKEND_HOST) { $settings.D2C_BACKEND_HOST } else { '127.0.0.1' }
$webPort = if ($settings.D2C_WEB_PORT) { [int]$settings.D2C_WEB_PORT } else { 5173 }
$backendPort = if ($settings.D2C_BACKEND_PORT) { [int]$settings.D2C_BACKEND_PORT } else { 7001 }
if ($webHost -notin @('127.0.0.1', 'localhost') -or $backendHost -notin @('127.0.0.1', 'localhost')) { throw '工作台与后端只能绑定本机地址。' }
if ($webPort -lt 1 -or $webPort -gt 65535 -or $backendPort -lt 1 -or $backendPort -gt 65535 -or $webPort -eq $backendPort) { throw '请检查 .env 中的端口。' }
if (Test-Path -LiteralPath $processFile) {
    $previous = Get-Content -Raw -LiteralPath $processFile | ConvertFrom-Json
    foreach ($item in @($previous.processes)) {
        $proc = Get-Process -Id $item.id -ErrorAction SilentlyContinue
        if ($proc -and $proc.StartTime.ToUniversalTime().Ticks -eq $item.start_ticks) { throw '工作台已经启动；需要重启时先运行 Stop-Design2Code.ps1。' }
    }
}
foreach ($port in @($webPort, $backendPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw "端口 $port 已被占用，请先停止占用该端口的服务。" }
}
$poetry = Get-Command poetry.exe -ErrorAction SilentlyContinue
if (-not $poetry) {
    $poetryPath = Join-Path $env:USERPROFILE '.local\bin\poetry.exe'
    if (-not (Test-Path -LiteralPath $poetryPath)) { throw '未找到 Poetry，请先安装后端依赖。' }
} else { $poetryPath = $poetry.Source }
Push-Location $backendDir
try { $pythonPath = (& $poetryPath env info --executable | Select-Object -Last 1).Trim() } finally { Pop-Location }
if (-not $pythonPath -or -not (Test-Path -LiteralPath $pythonPath)) { throw '未找到后端虚拟环境，请先在 backend 运行 poetry install。' }
$node = Get-Command node.exe -ErrorAction SilentlyContinue
$vitePath = Join-Path $frontendDir 'node_modules\vite\bin\vite.js'
if (-not $node -or -not (Test-Path -LiteralPath $vitePath)) { throw '未找到 Node.js 或前端依赖，请先在 frontend 运行 pnpm install。' }
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $processFile) | Out-Null
function Stop-StartedTree([int]$ParentId, [datetime]$RootStart) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        if ($child.CreationDate.ToUniversalTime() -ge $RootStart) {
            Stop-StartedTree -ParentId $child.ProcessId -RootStart $RootStart
        }
    }
    Stop-Process -Id $ParentId -ErrorAction SilentlyContinue
}
$started = @()
$bridge = $null
function Save-StartedProcesses {
    $records = foreach ($proc in $started) { @{ id = $proc.Id; start_ticks = $proc.StartTime.ToUniversalTime().Ticks } }
    @{ processes = @($records) } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $processFile -Encoding UTF8
}
try {
    if ($settings.D2C_FIGMA_MODE -eq 'mcp') {
        $bridgeDir = Join-Path $projectRoot 'figma-mcp-bridge\server'
        $bridgePath = Join-Path $bridgeDir 'workbench-bridge.mjs'
        if (-not (Test-Path -LiteralPath (Join-Path $bridgeDir 'dist\index.js'))) {
            Write-Warning 'Figma bridge 尚未构建；截图和 Spec 仍可使用。需要 Figma 时请先构建 bridge。'
        } elseif (Get-NetTCPConnection -LocalPort 1994 -State Listen -ErrorAction SilentlyContinue) {
            try {
                $ping = Invoke-RestMethod -Uri 'http://127.0.0.1:1994/ping' -TimeoutSec 2
                if ($ping.status -ne 'ok' -or -not $ping.version) { throw 'unexpected bridge response' }
                Write-Output '复用已运行的 Figma bridge；停止工作台时不会关闭该外部进程。'
            } catch { Write-Warning 'Figma bridge 端口不可用；截图和 Spec 仍可使用，请检查端口 1994。' }
        } else {
            try {
                $bridge = Start-Process -FilePath $node.Source -ArgumentList @('"' + $bridgePath + '"') -WorkingDirectory $bridgeDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'bridge.out.log') -RedirectStandardError (Join-Path $runtimeDir 'bridge.err.log')
            } catch { Write-Warning 'Figma bridge 启动失败；截图和 Spec 仍可使用。' }
            if ($bridge) { $started += $bridge; Save-StartedProcesses }
        }
    }
    $backendArgs = @('-m', 'uvicorn', 'main:app', '--host', $backendHost, '--port', "$backendPort", '--workers', '1')
    $backend = Start-Process -FilePath $pythonPath -ArgumentList $backendArgs -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'backend.out.log') -RedirectStandardError (Join-Path $runtimeDir 'backend.err.log')
    $started += $backend
    Save-StartedProcesses
    $viteArgs = @('"' + $vitePath + '"')
    $frontend = Start-Process -FilePath $node.Source -ArgumentList $viteArgs -WorkingDirectory $frontendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'frontend.out.log') -RedirectStandardError (Join-Path $runtimeDir 'frontend.err.log')
    $started += $frontend
    Save-StartedProcesses
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if ($backend.HasExited -or $frontend.HasExited) { break }
        try {
            $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://${backendHost}:${backendPort}/api/d2c/v1/capabilities"
            $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://${webHost}:${webPort}/"
            $ready = $true
            break
        } catch { }
    }
    if (-not $ready) { throw '启动未完成，请检查 D2C_RUNTIME_DIR 目录下的服务日志。' }
    if ($bridge) {
        try { $ping = Invoke-RestMethod -Uri 'http://127.0.0.1:1994/ping' -TimeoutSec 2; if ($ping.status -ne 'ok') { throw 'bridge not ready' } }
        catch { Write-Warning 'Figma bridge 尚未就绪；截图和 Spec 仍可使用，请检查 bridge 日志。' }
    }
    Write-Output "Design2Code 已启动：http://${webHost}:${webPort}"
} catch {
    foreach ($proc in $started) { if (-not $proc.HasExited) { Stop-StartedTree -ParentId $proc.Id -RootStart $proc.StartTime.ToUniversalTime() } }
    Remove-Item -LiteralPath $processFile -ErrorAction SilentlyContinue
    throw
}
