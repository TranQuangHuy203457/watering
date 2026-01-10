# RTOS Watering System - Real-Time Performance Analysis

**Course:** Hệ điều hành thời gian thực (Real-Time Operating Systems)  
**Instructor:** Đỗ Trọng Tuấn  
**Semester:** 2025-2026

**Team Members:**
- Trần Quang Huy (20241123e) - Team Lead, Scheduling & OS Implementation
- Đỗ Văn Hinh (20240650e) - Communication & Network Analysis
- Nguyễn Thành Đăng (20241668e) - Database & Storage Performance

---

## Project Overview

Firmware and experiment scaffolding for an ESP32-based automated irrigation system with comprehensive real-time performance analysis covering:
1. **Real-time Scheduling** (Static Priority vs EDF)
2. **OS Synchronization** (Mutex, Jitter, Latency)
3. **Real-time Communication** (E2E latency with timestamping)
4. **Database I/O Impact** (Synchronous vs Asynchronous writes)

This README documents how to build, run, and evaluate the firmware, plus a detailed Real-Time Task Table (periods, WCET, deadlines, precedence, firmness) for your scheduling analysis deliverable.

## Repository Structure

```
RTOS_watering/
├── README.md                      # This file
├── run_all_experiments.ps1        # One-command entrypoint for all experiments
├── requirements.txt               # Python dependencies (stdlib only)
├── platformio.ini                 # ESP32 build configuration
├── src/                           # Firmware (C++)
│   ├── main.cpp                   # FreeRTOS tasks implementation
│   ├── system_mode.h              # System mode definitions
│   ├── web_server.cpp/h           # Web server implementation
├── data/www/                      # Web dashboard
│   ├── index.html                 # UI with Auto/Manual controls
│   ├── app.js                     # Client-side logic (Chart.js)
│   └── style.css                  # Styling
├── scripts/                       # Simulation & analysis tools
│   ├── simulate_logic.py          # Part 1: Irrigation logic simulation
│   ├── simulate_overload.py       # Part 1: Scheduling analysis (Static vs EDF)
│   ├── measure_jitter.py          # Part 2: Jitter measurement
│   ├── comm_instrument.py         # Part 3: Communication E2E latency
│   ├── final_comm_report.py       # Part 3: Communication results summary
│   ├── simulate_db_impact.py      # Part 4: Database I/O impact analysis
│   ├── web_preview.py             # Local web server for dashboard preview
│   ├── parse_logs.py              # Log parser for miss rates
│   └── make_esp_hex.py            # Hex file generator
├── configs/                       # Experiment configurations
│   ├── baseline.json              # Static priority, no DB
│   └── improved.json              # EDF, async DB
├── docs/                          # Documentation
│   ├── Project_Report_Template.md # Full report template (8-12 pages)
│   ├── Demo_Slides.md             # Demo presentation (8 slides)
│   ├── scheduling_plan.md         # Scheduling design
│   └── database_persistence.md    # Database design
├── results/                       # Generated experiment results
│   ├── scheduling_*.csv           # Scheduling analysis
│   ├── jitter_*.csv               # Jitter measurements
│   ├── comm_*.csv                 # Communication latency
│   └── db_impact_*.csv            # Database impact
└── logs/                          # Runtime logs

---

## Quick Start - Reproducibility Package

### Prerequisites
- Python 3.8+ (no external dependencies required)
- PowerShell (for Windows)
- PlatformIO CLI (for firmware build)

### Run All Experiments (One Command)

```powershell
.\run_all_experiments.ps1
```

**OR** for quick validation (faster execution):

```powershell
.\run_all_experiments.ps1 -FastMode
```

This will:
1. Run irrigation logic simulation (60s)
2. Perform scheduling analysis (Baseline vs EDF)
3. Measure jitter (60s)
4. Test communication latency (Baseline + Bad-case)
5. Analyze database I/O impact (Sync vs Async)

**Results** will be generated in `results/` directory with CSV logs and summary text files.

**Time:** ~5 minutes (full) or ~2 minutes (FastMode)

---

## Firmware Build & Upload (ESP32)

### Setup (Local Machine)

1. **Create Python virtual environment** (optional but recommended):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. **Install PlatformIO CLI**:
2. **Install PlatformIO CLI**:
```powershell
python -m pip install --upgrade pip
pip install -U platformio
```

3. **Build firmware** (provide API keys at build time):
```powershell
pio run -e baseline -DSUPABASE_URL="https://<proj>.supabase.co" -DSUPABASE_KEY="<your_key>" -DWEATHER_API_KEY="<your_key>"
```

4. **Upload & Monitor**:
```powershell
pio run -e baseline -t upload
pio device monitor -p COM3 -e baseline
```

---

## Web Dashboard Preview

Run local web server with simulated backend:

```powershell
python scripts\web_preview.py
```

Then open: http://localhost:8080

**Features:**
- Real-time sensor data (Temperature, Humidity, Soil moisture)
- Control Mode: Auto (rule-based) vs Manual (user-driven)
- Pump/Light control with duration timers
- KPI graphs: Response time, Queue depth, Latency

---

## Key Results Summary

### Part 1: Scheduling (Severe Overload)
- **Baseline (Static Priority):** 30.1% deadline miss rate
- **EDF:** 45.6% deadline miss rate
- **Insight:** EDF degrades faster under extreme sporadic load (+51% more misses)

### Part 2: Jitter & Latency
- **Switch Task:** p95 = 3.5s, p99 = 3.7s (host simulation)
- **Expected on-device:** ~2-3ms (1000x lower)

### Part 3: Communication
- **E2E Latency p99:** 6 µs (baseline)
- **Bad-case tolerance:** Graceful with 50ms delay + 20% loss

### Part 4: Database I/O Impact
- **No DB:** 5.9ms response p99
- **Sync Write:** 123.7ms response p99 (21x slower, +95.8ms penalty)
- **Async Write:** 6.0ms response p99 (near-baseline, 0% deadline miss)
- **Conclusion:** Async buffered writes **essential** for real-time

---

## Security
- Never commit API keys or service-role keys. Use build flags, environment-specific `platformio.ini.local` (gitignored), or CI secrets.
- For CI, store `SUPABASE_KEY` and `WEATHER_API_KEY` in repository secrets and inject them in workflows.

Supabase telemetry
The firmware posts telemetry to Supabase `telemetry` table. Example SQL to create a compatible table:
```sql
create table public.telemetry (
  id bigint generated by default as identity primary key,
  created_at timestamptz default now(),
  airtemp numeric,
  airhum numeric,
  forecasttemp numeric,
  forecasthum numeric,
  forecastlight numeric,
  forecast3temp numeric,
  forecast3hum numeric,
  forecast3light numeric,
  pumpon boolean,
  rainsoon boolean,
  nextirrigationms bigint,
  soil jsonb,
  valves jsonb
);
```

---

## Documentation

- **[Project Report Template](docs/Project_Report_Template.md)** - Full 8-12 page report with all required sections
- **[Demo Slides](docs/Demo_Slides.md)** - 8-slide presentation for demo
- **[Scheduling Plan](docs/scheduling_plan.md)** - Task mapping and priority assignment
- **[Database Design](docs/database_persistence.md)** - DB roles and trade-offs

---

## Instrumentation & Measurement
- The firmware logs timing and deadline checks using `logTask()`; format:
  ```
  [<timestamp>ms] <Task> end duration=<d>ms deadline=<DL>ms HIT|MISS
  ```
- Use `scripts/parse_logs.py` to compute miss rates and latency percentiles.

Real-Time Task Table (detailed)

Legend:
- Period / Release — how often the task runs or how it is released.
- WCET — conservative worst-case execution time estimate (to be measured on-device).
- Deadline — the `DL_*` constant used by `logTask()` in code.
- Precedence — inputs or tasks that must complete first for fresh data.
- Firmness — `hard` (miss unacceptable), `firm` (miss degrades performance), `soft` (best-effort).

| Task            | Period / Release                 | WCET (est.) | Deadline (`DL_*`) | Precedence / Inputs                                 | Firmness |
|-----------------|----------------------------------:|------------:|------------------:|----------------------------------------------------|:--------:|
| SoilTask        | periodic, every 1000 ms           | 30–80 ms    | `DL_SOIL_MS` = 1000 ms  | none (provides `soilPct[]`)                         | firm     |
| DHTTask         | periodic, every 2000 ms           | 100–200 ms  | `DL_DHT_MS` = 2000 ms   | none (provides `airTemp`, `airHum`)                 | firm     |
| SwitchTask      | periodic decision, check every 1000 ms; scheduled irrigation events release asynchronously | 20–120 ms   | `DL_SWITCH_MS` = 1000 ms | depends on `soilPct[]`, `airTemp/airHum`, `forecast*`, `pumpOk/valveOk` | hard     |
| ErrorCheckTask  | periodic, every 5000 ms           | 80–300 ms   | `DL_ERROR_MS` = 5000 ms | uses feedback pins to set `pumpOk`/`valveOk`        | soft     |
| WeatherTask     | periodic, every 3600 s (1 h)      | 1–6 s (HTTP+parse) | `DL_WEATHER_MS` = 3600000 ms | networked HTTP call → updates `forecast*`, `rainSoon` | soft     |
| NetworkTask     | periodic send loop, admission control min interval 30 s | 200–2000 ms | `DL_NETWORK_MS` = 30000 ms | depends on `soilPct[]`, `airTemp`, `forecast*`, `valveOn[]` | soft     |
| DisplayTask     | periodic update (two-view cycle), ~3 s combined | 50–250 ms   | `DL_DISPLAY_MS` = 1000 ms | reads sensors + forecast + device state            | soft     |
| WatchdogTask    | periodic heartbeat, 2000 ms       | 5–20 ms     | `DL_WATCHDOG_MS` = 2000 ms | none                                              | hard     |

Notes and rationale
- `SwitchTask` controls actuation and is therefore the highest criticality: treat as `hard` in scheduling analysis. Ensure its input tasks (SoilTask, DHTTask) have sufficient priority and meet deadlines.
- `WeatherTask` is high-latency and infrequent; it provides advisory forecast values to improve scheduling decisions but is `soft`.
- `NetworkTask` is best-effort telemetry and should be throttled via `NETWORK_MIN_SEND_INTERVAL_MS` to avoid connectivity spikes.
- `ErrorCheckTask` improves safety by toggling relays briefly and reading feedback pins; when a device is flagged unhealthy the outputs are gated off by `applyOutputs()`.

How to measure and tune
1. Build and upload firmware, then capture serial logs (`platformio device monitor`).
2. Run `scripts/parse_logs.py` against the serial log to compute miss rates and latency percentiles.
3. Tune `DL_*` constants and task priorities in `src/main.cpp` and re-evaluate.

Collaboration and CI
- Invite collaborators via GitHub: Settings → Manage access (or `gh repo add-collaborator owner/repo user --permission write`).
- Add `SUPABASE_KEY` and `WEATHER_API_KEY` as GitHub Secrets for CI builds.

Optional additions I can implement for you:
- GitHub Actions workflow that builds `baseline` and `improved` (without secrets), runs static checks, and exposes artifacts.
- A `platformio.ini.local.example` template and a small `build-local.ps1` script that reads local secrets from a `.env` file.

---
Last updated: 2025-12-24
