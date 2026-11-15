$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$statusPath = Join-Path $projectPath '.development-state\status.json'
if (Test-Path -LiteralPath $statusPath) { Get-Content -LiteralPath $statusPath -Encoding UTF8 -Raw }
else { Write-Output '{"status":"not_started"}' }
