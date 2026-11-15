$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $projectPath '.development-state'
$null = New-Item -ItemType Directory -Path $statePath -Force
[IO.File]::WriteAllText((Join-Path $statePath 'STOP'), "User requested development STOP`n")
Write-Output 'STOP richiesto per il solo ciclo di sviluppo. JARVIS e Ollama restano indipendenti.'
