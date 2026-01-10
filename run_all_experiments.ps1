# ==============================================================================
# RTOS Watering System - Complete Reproducibility Script
# ==============================================================================
# This script runs all experiments and generates results for the project report
# Total runtime: ~5 minutes
# Usage: .\run_all_experiments.ps1 [-FastMode]
# ==============================================================================

param(
    [switch]$FastMode = $false
)

$ErrorActionPreference = 'Stop'
$startTime = Get-Date

Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host " RTOS Watering System - Reproducibility Pipeline" -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host ""

# Create directories
$resultsDir = 'results'
if (-not (Test-Path $resultsDir)) { 
    New-Item -ItemType Directory -Path $resultsDir | Out-Null 
    Write-Host "[OK] Created directory: $resultsDir" -ForegroundColor Green
}

Write-Host ""
Write-Host "===================================================================="-ForegroundColor Yellow
Write-Host " Step 1: Irrigation Logic Simulation" -ForegroundColor Yellow
Write-Host "===================================================================="-ForegroundColor Yellow
Write-Host "Running irrigation control logic simulator (60s simulation)..."
Write-Host ""

python scripts/simulate_logic.py
if ($LASTEXITCODE -ne 0) { Write-Warning "Irrigation simulation had errors"; }

Write-Host ""
Write-Host "[OK] Irrigation logic simulation completed" -ForegroundColor Green
Start-Sleep -Seconds 1

Write-Host ""
Write-Host "===================================================================="-ForegroundColor Yellow
Write-Host " Step 2: Scheduling & Deadline Analysis" -ForegroundColor Yellow
Write-Host "===================================================================="-ForegroundColor Yellow
Write-Host "Running overload scenario (baseline vs EDF)..."
Write-Host "- Moderate burst: 4x WCET"
Write-Host "- Severe burst: 10x WCET + 5 sporadic jobs"
Write-Host ""

python scripts/simulate_overload.py > results/scheduling_analysis.txt
if ($LASTEXITCODE -ne 0) { Write-Warning "Scheduling analysis had errors"; }

Write-Host ""
Write-Host "[OK] Scheduling analysis completed" -ForegroundColor Green
Write-Host "     Results: results/scheduling_analysis.txt"
Start-Sleep -Seconds 1

Write-Host ""
Write-Host "===================================================================="-ForegroundColor Yellow
Write-Host " Step 3: Jitter Measurement" -ForegroundColor Yellow
Write-Host "===================================================================="-ForegroundColor Yellow
Write-Host "Measuring task jitter (60s simulation with burst)..."
Write-Host ""

python scripts/measure_jitter.py > results/jitter_analysis.txt
if ($LASTEXITCODE -ne 0) { Write-Warning "Jitter measurement had errors"; }

Write-Host ""
Write-Host "[OK] Jitter measurement completed" -ForegroundColor Green
Write-Host "     Results: results/jitter_baseline.csv, results/jitter_analysis.txt"
Start-Sleep -Seconds 1

Write-Host ""
Write-Host "===================================================================="-ForegroundColor Yellow
Write-Host " Step 4: Real-Time Communication Tests" -ForegroundColor Yellow
Write-Host "===================================================================="-ForegroundColor Yellow
Write-Host "Running E2E communication latency tests..."
Write-Host ""

# Clean old communication logs
Remove-Item -Path results/comm_*.csv -ErrorAction SilentlyContinue

Write-Host "[4a] Starting baseline test (clean network)..."
$serverJob = Start-Job -ScriptBlock { 
    python scripts/comm_instrument.py --server --port 5005 
}
Start-Sleep -Seconds 2

if ($FastMode) {
    python scripts/comm_instrument.py --target 127.0.0.1 --port 5005 --type baseline --count 15 --interval-ms 2
} else {
    python scripts/comm_instrument.py --target 127.0.0.1 --port 5005 --type baseline --count 30 --interval-ms 5
}

Stop-Job -Job $serverJob -ErrorAction SilentlyContinue
Remove-Job -Job $serverJob -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "[4b] Starting bad-case test (50ms delay, 20% loss)..."
$serverJob = Start-Job -ScriptBlock { 
    python scripts/comm_instrument.py --server --port 5005 --badcase --delay-ms 50 --drop-prob 0.2 
}
Start-Sleep -Seconds 2

if ($FastMode) {
    python scripts/comm_instrument.py --target 127.0.0.1 --port 5005 --type badcase --count 15 --interval-ms 2 --timeout-ms 200
} else {
    python scripts/comm_instrument.py --target 127.0.0.1 --port 5005 --type badcase --count 30 --interval-ms 5 --timeout-ms 200
}

Stop-Job -Job $serverJob -ErrorAction SilentlyContinue
Remove-Job -Job $serverJob -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "[4c] Analyzing communication logs..."
python scripts/final_comm_report.py > results/communication_analysis.txt

Write-Host ""
Write-Host "[OK] Communication tests completed" -ForegroundColor Green
Write-Host "     Results: results/comm_baseline_log.csv, results/comm_badcase_log.csv"
Write-Host "              results/final_comm_summary.txt"
Start-Sleep -Seconds 1

Write-Host ""
Write-Host "===================================================================="-ForegroundColor Yellow
Write-Host " Step 5: Database I/O Impact Analysis" -ForegroundColor Yellow
Write-Host "===================================================================="-ForegroundColor Yellow
Write-Host "Running DB impact simulation (baseline vs sync vs async)..."
Write-Host ""

python scripts/simulate_db_impact.py > results/database_analysis.txt
if ($LASTEXITCODE -ne 0) { Write-Warning "DB impact analysis had errors"; }

Write-Host ""
Write-Host "[OK] Database analysis completed" -ForegroundColor Green
Write-Host "     Results: results/db_impact_*.csv, results/db_impact_summary.txt"
Start-Sleep -Seconds 1

Write-Host ""
Write-Host "===================================================================="-ForegroundColor Cyan
Write-Host " PIPELINE COMPLETED SUCCESSFULLY" -ForegroundColor Cyan
Write-Host "===================================================================="-ForegroundColor Cyan
Write-Host ""
Write-Host "All results generated in:" -ForegroundColor Green
Write-Host "  - results/jitter_baseline.csv"
Write-Host "  - results/comm_baseline_log.csv"
Write-Host "  - results/comm_badcase_log.csv"
Write-Host "  - results/db_impact_baseline.csv"
Write-Host "  - results/db_impact_sync.csv"
Write-Host "  - results/db_impact_async.csv"
Write-Host "  - results/*.txt (summaries)"
Write-Host ""
$elapsed = ([int]((Get-Date) - $startTime).TotalSeconds)
Write-Host "Total runtime: $elapsed seconds" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Review results in results/ directory"
Write-Host "  2. Generate plots (if needed)"
Write-Host "  3. Include data in project report"
Write-Host ""
