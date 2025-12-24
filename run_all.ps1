# Run build/upload for baseline and improved, then collect serial logs
# Requires PlatformIO CLI (`pio`) installed and in PATH.

$envs = @('baseline','improved')
$logsDir = 'logs'
$resultsDir = 'results'

if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }
if (-not (Test-Path $resultsDir)) { New-Item -ItemType Directory -Path $resultsDir | Out-Null }

foreach ($e in $envs) {
    Write-Host "Building environment: $e"
    pio run -e $e
    Write-Host "Uploading (env: $e)"
    pio run -e $e -t upload
    $logfile = "logs/serial_$e.log"
    Write-Host "Starting monitor and saving to $logfile (Ctrl+C to stop)"
    pio device monitor -e $e > $logfile
    Write-Host "Monitor ended for $e"
}

Write-Host "Run parser example (host): python scripts/parse_logs.py logs/serial_baseline.log -o results/baseline.csv"
