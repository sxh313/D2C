$ErrorActionPreference = 'Stop'
$processFile = Join-Path $PSScriptRoot 'runtime\workbench-processes.json'
if (-not (Test-Path -LiteralPath $processFile)) { Write-Output '没有找到本工作台启动的进程。'; return }
function Stop-StartedTree([int]$ParentId, [datetime]$RootStart) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        if ($child.CreationDate.ToUniversalTime() -ge $RootStart) {
            Stop-StartedTree -ParentId $child.ProcessId -RootStart $RootStart
        }
    }
    Stop-Process -Id $ParentId -ErrorAction SilentlyContinue
}
$previous = Get-Content -Raw -LiteralPath $processFile | ConvertFrom-Json
foreach ($item in @($previous.processes)) {
    $proc = Get-Process -Id $item.id -ErrorAction SilentlyContinue
    if ($proc -and $proc.StartTime.ToUniversalTime().Ticks -eq $item.start_ticks) {
        Stop-StartedTree -ParentId $proc.Id -RootStart $proc.StartTime.ToUniversalTime()
    }
}
Remove-Item -LiteralPath $processFile
Write-Output 'Design2Code 已停止。'
