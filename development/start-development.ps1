param([switch]$Once)
$ErrorActionPreference = 'Stop'
if (-not $Once) { throw 'È autorizzata soltanto la modalità -Once. Nessun avvio continuo è configurato.' }
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
Set-Location -LiteralPath $projectPath
& $pythonPath -B -m development.orchestrator run --once
exit $LASTEXITCODE
