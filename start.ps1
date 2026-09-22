[CmdletBinding()]
param(
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker was not found. Install Docker Desktop, then open a new PowerShell window.'
    }
    & docker info --format '{{.OSType}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker is unavailable. Open Docker Desktop, wait until its engine is running, then run this script again.'
    }
    & docker compose version
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is unavailable. Enable or update Docker Desktop.' }

    # Create local configuration once; preserve existing database credentials.
    $configPath = Join-Path $PSScriptRoot '.env'
    if (-not (Test-Path -LiteralPath $configPath)) {
        $randomBytes = New-Object byte[] 24
        $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $random.GetBytes($randomBytes) } finally { $random.Dispose() }
        $password = [BitConverter]::ToString($randomBytes).Replace('-', '').ToLowerInvariant()
        $stream = [System.IO.File]::Open($configPath, [System.IO.FileMode]::CreateNew)
        try {
            $data = [System.Text.Encoding]::UTF8.GetBytes("DEMO_DB_PASSWORD=$password`n")
            $stream.Write($data, 0, $data.Length)
        } finally { $stream.Dispose() }
        Write-Host 'Created local configuration.'
    }

    $configText = [System.IO.File]::ReadAllText($configPath)
    $defaults = @{ LLM_PROVIDER='ollama'; GROQ_API_KEY=''; GROQ_MODEL='openai/gpt-oss-20b'; LLM_DAILY_REQUEST_LIMIT='100' }
    foreach ($setting in $defaults.GetEnumerator()) {
        if ($configText -notmatch ('(?m)^' + $setting.Key + '=')) {
            [System.IO.File]::AppendAllText($configPath, "`n$($setting.Key)=$($setting.Value)`n")
        }
    }
    if ($configText -notmatch '(?m)^DEMO_DB_PASSWORD=\S+') {
        $bytes = New-Object byte[] 24
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $generated = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
        $updated = [System.IO.File]::ReadAllText($configPath) -replace '(?m)^DEMO_DB_PASSWORD=.*\r?\n?', ''
        [System.IO.File]::WriteAllText($configPath, $updated + "`nDEMO_DB_PASSWORD=$generated`n")
    }

    Write-Host 'Building and starting the dashboard, execution worker, banking app, and database...'
    & docker compose up --build -d --wait --wait-timeout 120
    if ($LASTEXITCODE -ne 0) {
        & docker compose ps -a
        & docker compose logs --tail 60 dashboard worker app db
        throw 'Startup failed. Review the service status and logs above.'
    }
    $health = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 10
    if ($health.status -ne 'ready') { throw 'The app did not return a healthy status.' }
    $dashboard = Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 10
    if ($dashboard.StatusCode -ne 200) { throw 'The dashboard is unavailable.' }
    $execution = Invoke-RestMethod 'http://127.0.0.1:5173/api/health' -TimeoutSec 15
    if (-not $execution.bank) { throw 'The execution worker cannot reach the banking app.' }
    if (-not $execution.model) { Write-Host 'Replay is ready. Discovery needs a configured model provider. Check LLM_PROVIDER and Model status.' }
    Write-Host "`nDashboard ready: http://127.0.0.1:5173"
    Write-Host "`nApp ready: http://127.0.0.1:8000"
    Write-Host 'Synthetic customers: C-104 and C-205'
    Write-Host 'Stop with: docker compose down (saved data is retained).'
    if ($OpenBrowser) { Start-Process 'http://127.0.0.1:5173' }
} catch {
    Write-Host "Startup error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
