[CmdletBinding()]
param([switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path '.venv/Scripts/python.exe')) {
        & python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or later is required.' }
    }
    $pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    & $pythonPath -m pip install -e '.[test]'
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency setup failed.' }
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PSScriptRoot '.browsers'
    & $pythonPath -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Browser setup failed.' }
    $npmCommand = Get-Command npm.cmd -ErrorAction Stop
    Push-Location frontend
    try {
        & $npmCommand.Source ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency setup failed.' }
        & $npmCommand.Source run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    New-Item -ItemType Directory -Force work/local | Out-Null
    foreach ($service in @(@{name='bank';port=8000;module='demo.app:create_app';health='/health'}, @{name='api';port=5174;module='engine.api:create_app';health='/api/health'})) {
        $serviceUrl = "http://127.0.0.1:$($service.port)"
        $running = $false
        try { Invoke-RestMethod ($serviceUrl + $service.health) -TimeoutSec 8 | Out-Null; $running = $true } catch {}
        if (-not $running) {
            Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn',$service.module,'--factory','--host','127.0.0.1','--port',$service.port,'--no-access-log') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "work/local/$($service.name).out.log" -RedirectStandardError "work/local/$($service.name).err.log" | Out-Null
            for ($attempt=0; $attempt -lt 30; $attempt++) {
                Start-Sleep -Seconds 1
                try { Invoke-RestMethod ($serviceUrl + $service.health) -TimeoutSec 8 | Out-Null; $running=$true; break } catch {}
            }
        }
        if (-not $running) { throw "$($service.name) did not start. Inspect work/local logs." }
    }
    Write-Host 'Dashboard + execution API: http://127.0.0.1:5174'
    Write-Host 'Cedar Bank: http://127.0.0.1:8000'
    Write-Host 'Local mode uses SQLite. Discovery uses an already-installed Ollama model.'
    if ($OpenBrowser) { Start-Process 'http://127.0.0.1:5174' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally { Pop-Location }
