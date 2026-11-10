param(
    [Parameter(Mandatory = $true)][string]$FigmaUrl,
    [string]$SessionKey
)
$ErrorActionPreference = 'Stop'
$uri = [Uri]::new($FigmaUrl)
if ($uri.Scheme -ne 'https' -or $uri.Host -notin @('figma.com', 'www.figma.com') -or $uri.AbsolutePath -notmatch '^/(design|file)/([A-Za-z0-9]+)(/|$)') {
    throw '请输入有效的 Figma 设计文件链接。'
}
$fileKey = $Matches[2]
try { $files = @((Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:1994/rpc' -ContentType 'application/json' -Body '{"tool":"list_files"}' -TimeoutSec 5).data) }
catch { throw '无法连接本地 bridge。请先启动工作台并运行 Figma 插件。' }
if (-not $SessionKey) {
    if ($files.Count -ne 1) {
        $files | Select-Object fileName, fileKey | Format-Table | Out-Host
        throw '请只打开一个插件，或者用 -SessionKey 指定上表中的会话。'
    }
    $SessionKey = $files[0].fileKey
}
if (@($files | Where-Object { $_.fileKey -ceq $SessionKey }).Count -ne 1) { throw '指定的插件会话没有连接。' }
if ($SessionKey -notmatch '^unsaved-[A-Za-z0-9-]+$') {
    if ($SessionKey -ceq $fileKey) { Write-Output '插件已提供匹配的文件标识，无需绑定。'; return }
    throw '插件提供的文件标识与链接不一致，请确认打开了正确的文件。'
}
$envPath = Join-Path $PSScriptRoot '.env'
$lines = [System.Collections.Generic.List[string]]::new()
foreach ($line in [IO.File]::ReadAllLines($envPath)) {
    if ($line -notmatch '^\s*(D2C_FIGMA_MCP_BOUND_FILE_KEY|D2C_FIGMA_MCP_SESSION_KEY)\s*=') { $lines.Add($line) }
}
$lines.Add("D2C_FIGMA_MCP_BOUND_FILE_KEY=$fileKey")
$lines.Add("D2C_FIGMA_MCP_SESSION_KEY=$SessionKey")
[IO.File]::WriteAllLines($envPath, $lines, [Text.UTF8Encoding]::new($false))
Write-Output '已绑定当前 Figma 文件和插件会话。请保持插件窗口打开。'
