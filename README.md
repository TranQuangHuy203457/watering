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
## RTOS Watering — Tổng quan ngắn gọn

Dự án firmware và bộ công cụ thử nghiệm cho hệ tưới tự động trên ESP32, tập trung phân tích hiệu năng thời gian thực: lập lịch, jitter, truyền thông, và tác động I/O cơ sở dữ liệu.

Phiên bản rút gọn này mô tả cách build, chạy thử các thí nghiệm và vị trí các script quan trọng.

--

## Bắt đầu nhanh

Yêu cầu:
- Windows, PowerShell
- Python 3.8+
- PlatformIO CLI (để build firmware)

Chạy toàn bộ thí nghiệm (PowerShell):

```powershell
.\run_all_experiments.ps1
```

Chạy nhanh (FastMode):

```powershell
.\run_all_experiments.ps1 -FastMode
```

Kết quả sẽ nằm trong thư mục `results/`.

--

## Build firmware (ESP32)

Tạo virtualenv (khuyến nghị):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Cài PlatformIO CLI:

```powershell
python -m pip install --upgrade pip
pip install -U platformio
```

Build (đưa biến môi trường / define cho API keys khi cần):

```powershell
pio run -e baseline -DSUPABASE_URL="https://<proj>.supabase.co" -DSUPABASE_KEY="<your_key>" -DWEATHER_API_KEY="<your_key>"
```

Upload và monitor:

```powershell
pio run -e baseline -t upload
pio device monitor -p COM3 -e baseline
```

Ghi chú: không commit API keys; sử dụng file `platformio.ini.local` (gitignored) hoặc CI secrets.

--

## Cấu trúc chính (tóm tắt)

- `src/` — mã firmware (C++): `main.cpp`, `web_server.*`, `state.h`, `system_mode.h`.
- `scripts/` — script Python để mô phỏng, đo lường và phân tích (ví dụ `measure_jitter.py`, `parse_logs.py`, `simulate_db_impact.py`).
- `data/www/` — dashboard web tĩnh (`index.html`, `app.js`, `style.css`).
- `configs/` — file cấu hình thí nghiệm (ví dụ `baseline.json`, `improved.json`).
- `results/` — đầu ra thí nghiệm (CSV, txt).

--

## Tự kiểm tra & đo lường

1. Build và upload firmware, mở serial monitor để thu logs.
2. Dùng `scripts/parse_logs.py` để tính tỷ lệ miss và phân vị độ trễ.
3. Dùng `run_all_experiments.ps1` để tái tạo toàn bộ pipeline thử nghiệm.

--

## An toàn & CI

- Không commit keys vào git. Thêm `platformio.ini.local.example` nếu cần.
- Tích hợp CI: có thể thêm GitHub Actions để build firmware (không chứa secrets) và chạy kiểm tra tĩnh.

--

## Thao tác thêm (tùy chọn)

- Thêm `platformio.ini.local.example` và script `build-local.ps1` để load secrets từ `.env`.
- Tạo workflow GitHub Actions để build + lint tự động.

Last updated: 2026-01-27
