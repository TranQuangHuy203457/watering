# Demo Presentation Slides
## RTOS Watering System - Real-Time Performance Analysis

**For conversion to PowerPoint or PDF (5-8 slides)**

---

## Slide 1: Title & Team

### RTOS Watering System
**Real-Time Performance Analysis**

**Course:** Hệ điều hành thời gian thực  
**Instructor:** Đỗ Trọng Tuấn  
**Date:** January 2026

**Team Members:**
- Trần Quang Huy (20241123e) - Team Lead, Scheduling  
- Đỗ Văn Hinh (20240650e) - Communication  
- Nguyễn Thành Đăng (20241668e) - Database  

---

## Slide 2: System Architecture & Demo

### ESP32-Based Automated Irrigation System

```
┌─────────────────────────────────────────┐
│         ESP32 (FreeRTOS)                │
│                                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
│  │  Soil   │  │  Temp/  │  │ Weather │ │
│  │ Sensors │  │   Hum   │  │   API   │ │
│  └────┬────┘  └────┬────┘  └────┬────┘ │
│       │            │            │       │
│       └────────────┴────────────┘       │
│                    │                     │
│              ┌─────▼─────┐              │
│              │  Control  │              │
│              │  Logic    │              │
│              └─────┬─────┘              │
│                    │                     │
│         ┌──────────┴──────────┐         │
│         │        Pump         │         │
│         │       Relay         │         │
│         └─────────────────────┘         │
└─────────────────────────────────────────┘
                   │
          ┌────────▼────────┐
          │  Web Dashboard  │
          │  (Chart.js)     │
          └─────────────────┘
```

**Live Demo:** 
- Web dashboard showing real-time sensor data (Temperature, Humidity, Soil moisture)
- Control mode: Auto (rule-based) vs Manual (user-driven)
- Pump/Light control with duration timers
- KPI graphs: Response time, Queue depth, Latency

**Screenshot:** [Include web_preview.py running with charts]

---

## Slide 3: Key Performance Indicators (KPIs)

### Part 1: Scheduling Performance

| Metric | Baseline (Static) | EDF | Difference |
|--------|-------------------|-----|------------|
| **Normal load** | 0% miss | 0% miss | ✓ Equivalent |
| **Severe overload** | 30.1% miss | 45.6% miss | ⚠️ EDF +51% worse |
| **Avg response** | 152 ms | 178 ms | EDF +17% slower |

**Insight:** EDF optimal under light load, but degrades faster under extreme sporadic bursts due to preemption overhead.

---

### Part 2: Jitter & Latency

| Task | p50 | p95 | p99 | Max |
|------|-----|-----|-----|-----|
| Switch (Control) | 2.3s | 3.5s | 3.7s | 3.7s |
| Sensor | 2.3s | 3.6s | 3.7s | 3.7s |

**Note:** Host-side Python simulation; on-device jitter would be ~2-3ms (1000x lower)

---

### Part 3: Communication Latency

| Metric | Baseline | Bad-case (50ms delay, 20% loss) |
|--------|----------|----------------------------------|
| E2E p99 | **6 µs** | Graceful degradation |
| TX duration p99 | 147 µs | 198 µs |
| Packet loss | 0% | ~20% (by design) |

**Insight:** System tolerates network adversity with appropriate timeout tuning.

---

### Part 4: Database I/O Impact

| Mode | Response p99 | DB Time p95 | Deadline Miss |
|------|--------------|-------------|---------------|
| **No DB** | 5.9 ms | 0 ms | 0% |
| **Sync Write** | **123.7 ms** | **95.8 ms** | 0% (but 21x slower) |
| **Async Write** | **6.0 ms** | 0 ms | 0% |

**Insight:** Synchronous DB writes add **95.8 ms penalty** (21x overhead) to control loop. Async buffered writes are **essential** for real-time performance.

---

## Slide 4: Stress Test - Severe Overload

### Scenario: 10x WCET Burst + 5 Heavy Sporadic Jobs

**Timeline:**
```
Time: 0s ─────────── 20s ─────────── 30s ─────────── 60s
       │     Normal     │   OVERLOAD   │    Normal    │
       │   (baseline)   │   (10x WC)   │ (recovery)   │
```

**Stress Conditions:**
- All tasks execute at 10x their WCET during 20-30s window
- 5 additional sporadic jobs (1000ms WCET each) injected
- Total utilization > 1000% during burst

**Results:**
- **Baseline (Static Priority):** 31 misses out of 103 jobs = **30.1% miss rate**
- **EDF:** 47 misses out of 103 jobs = **45.6% miss rate**

**Visual:** [Include timeline chart showing job arrivals, deadlines, HIT/MISS markers]

---

### Explanation (2-3 sentences):

EDF's deadline-driven preemption causes "thrashing" when many jobs have similar approaching deadlines during overload. Context switches dominate execution time, leaving insufficient time for actual work. Static-priority scheduling provides more predictable degradation by avoiding excessive preemption, resulting in **51% fewer deadline misses** under this specific stress scenario.

---

## Slide 5: Database I/O - Critical Path Comparison

### Synchronous vs Asynchronous Write Impact

**Synchronous (Blocking):**
```
Task → Format log → ⏸️ SPIFFS write (10-50ms BLOCK) → Continue
                          ↑
                    Critical path delay
```
- Guarantees consistency
- **Penalty:** +95.8ms (21x overhead)

**Asynchronous (Buffered):**
```
Task → Enqueue (~1µs) → Continue
                         ↓
Background thread → Batch flush every 5s
```
- Non-blocking for RT tasks
- **Trade-off:** 5s data loss window
- **Performance:** Near-baseline (6ms vs 5.9ms)

**Bar Chart:**
```
Response Time p99 (ms):
No DB:        █ 5.9
Sync Write:   █████████████████████ 123.7  (21x slower)
Async Write:  █ 6.0
```

**Conclusion:** Async writes are **mandatory** for hard real-time tasks.

---

## Slide 6: Communication - Bad-Case Tolerance

### Network Stress Test

**Baseline (Clean Network):**
- Latency p50: 0.001 ms
- Latency p99: 0.006 ms
- Packet loss: 0%

**Bad-case (Adversarial Conditions):**
- Injected delay: **50 ms per packet**
- Injected loss: **20% random drops**
- Timeout: 200 ms

**Result:** System maintains functionality with graceful degradation:
- Retries handle packet loss
- Timeout tuning prevents deadlock
- Control messages prioritized over telemetry

**Graph:** [Include latency histogram: baseline vs bad-case]

**Mitigation Strategies:**
- Priority queue (control > telemetry > heartbeat)
- Exponential backoff retry policy
- DSCP EF marking for QoS

---

## Slide 7: Reproducibility & Deliverables

### Package Contents

```
RTOS_watering/
├── README.md                      # Build & run instructions
├── run_all_experiments.ps1        # One-command entrypoint
├── requirements.txt               # Python dependencies
├── platformio.ini                 # ESP32 build config
├── src/                           # Firmware (C++)
├── data/www/                      # Web dashboard (HTML/JS)
├── scripts/                       # Simulation & analysis
│   ├── simulate_overload.py       # Part 1: Scheduling
│   ├── measure_jitter.py          # Part 2: Jitter
│   ├── comm_instrument.py         # Part 3: Communication
│   └── simulate_db_impact.py      # Part 4: Database
├── configs/
│   ├── baseline.json              # Static priority, no DB
│   └── improved.json              # EDF, async DB
├── docs/
│   ├── Project_Report_Template.md # Full report (8-12 pages)
│   └── Demo_Slides.md             # This presentation
└── results/                       # Generated CSVs & logs
```

**Run All Tests:**
```powershell
.\run_all_experiments.ps1
```
OR for quick validation:
```powershell
.\run_all_experiments.ps1 -FastMode
```

**Time:** ~2 min (FastMode) or ~5 min (full)

---

## Slide 8: Conclusion & Takeaways

### Key Findings

1. **Scheduling:** Static priority more robust under extreme overload (30.1% vs 45.6% miss)
2. **Database:** Sync writes unsuitable for RT (21x overhead); async essential
3. **Communication:** 6µs p99 latency achievable; graceful degradation under stress
4. **Jitter:** Predictable (p95=3.5s in simulation; ~2-3ms expected on-device)

### Lessons Learned

- ✓ Priority inheritance prevents priority inversion
- ✓ Async buffering moves I/O off critical path
- ✓ EDF not always better (preemption overhead under overload)
- ✓ Network timeout tuning critical for bad-case tolerance

### Future Work

- On-device profiling (GPIO tracing, cycle counter)
- Adaptive scheduling (switch static/EDF based on load)
- Formal verification (UPPAAL model checking)
- Multi-device E2E latency with NTP sync

**Thank you!**

**Q&A**

---

**End of Slides (8 pages)**
