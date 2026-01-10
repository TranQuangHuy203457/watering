# Run build/upload for baseline and improved, then collect serial logs
# Requires PlatformIO CLI (`pio`) installed and in PATH.

$envs = @('baseline','improved')
$logsDir = 'logs'
$resultsDir = 'results'

if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }
if (-not (Test-Path $resultsDir)) { New-Item -ItemType Directory -Path $resultsDir | Out-Null }

foreach ($e in $envs) {
    Write-Host "Building environment: $e" -ForegroundColor Cyan
    pio run -e $e
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Build successful for $e" -ForegroundColor Green
    } else {
        Write-Host "Build failed for $e" -ForegroundColor Red
    }
    # Skipped: Upload and monitor (no USB device required)
    # To upload manually: pio run -e $e -t upload --upload-port COM3
    # To monitor: pio device monitor -e $e
}

Write-Host "Run parser example (host): python scripts/parse_logs.py logs/serial_baseline.log -o results/baseline.csv"
