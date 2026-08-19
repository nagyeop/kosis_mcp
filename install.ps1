# KOSIS MCP — 로컬 stdio 등록 (Windows PowerShell)
# 사전: KOSIS_API_KEY, pip install kosis-mcp (또는 pip install -e .)

param(
  [ValidateSet('claude','cursor','all')]
  [string]$Client = 'all',
  [string]$Command = 'kosis-mcp'
)

if (-not $env:KOSIS_API_KEY) {
  Write-Error 'KOSIS_API_KEY 환경변수가 필요합니다.'
  exit 1
}

$entry = @{
  command = $Command
  args = @()
  env = @{ KOSIS_API_KEY = $env:KOSIS_API_KEY }
}

$paths = @{
  claude = Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'
  cursor = Join-Path $env:USERPROFILE '.cursor\mcp.json'
}

$targets = if ($Client -eq 'all') { $paths.Keys } else { @($Client) }
foreach ($t in $targets) {
  $path = $paths[$t]
  $dir = Split-Path $path -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
  $data = @{ mcpServers = @{} }
  if (Test-Path $path) {
    try { $data = Get-Content $path -Raw | ConvertFrom-Json -AsHashtable } catch {}
  }
  if (-not $data.ContainsKey('mcpServers')) { $data.mcpServers = @{} }
  $data.mcpServers['kosis-mcp'] = $entry
  ($data | ConvertTo-Json -Depth 8) | Set-Content -Path $path -Encoding UTF8
  Write-Host "updated $path"
}

Write-Host '완료. 클라이언트를 재시작하세요.'
