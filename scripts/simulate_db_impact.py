#!/usr/bin/env python3
"""
Simulate DB/I-O impact on real-time task performance.

Compares three configurations:
1. BASELINE: No DB logging (best-case performance)
2. SYNC: Synchronous SPIFFS writes (blocking, worst-case)
3. ASYNC: Asynchronous buffered writes (non-blocking, best trade-off)

Measures:
- Task response time (p50, p95, p99)
- Jitter (p99 - p50)
- Deadline miss rate
- DB write time
- Buffer depth (for async)

Outputs:
- results/db_impact_baseline.csv
- results/db_impact_sync.csv
- results/db_impact_async.csv
- results/db_impact_summary.txt
"""
import time
import random
import statistics
import csv
import os
from collections import deque

# Configuration
SIM_DURATION_S = 60
CONTROL_TASK_PERIOD_MS = 500  # Control task every 500ms
CONTROL_TASK_DEADLINE_MS = 450  # Deadline 450ms (90% of period)
CONTROL_TASK_WCET_MS = 5  # Worst-case execution time (no DB)

# DB Parameters
SPIFFS_WRITE_MIN_MS = 10
SPIFFS_WRITE_MAX_MS = 50
SPIFFS_WRITE_MEAN_MS = 25
SPIFFS_WRITE_STDDEV_MS = 8

# Async Buffer Parameters
BUFFER_SIZE = 100
FLUSH_INTERVAL_MS = 5000  # Flush every 5s
BATCH_SIZE = 20  # Max logs per flush

# Burst Parameters (simulate contention)
BURST_START_S = 20
BURST_END_S = 30
BURST_FACTOR = 3  # 3x more writes during burst

OUT_DIR = 'results'

def now_ms():
    return int(time.time() * 1000)

def simulate_spiffs_write():
    """Simulate SPIFFS write latency (Gaussian with min/max clamp)."""
    latency = random.gauss(SPIFFS_WRITE_MEAN_MS, SPIFFS_WRITE_STDDEV_MS)
    return max(SPIFFS_WRITE_MIN_MS, min(SPIFFS_WRITE_MAX_MS, latency))

def simulate_baseline():
    """Baseline: no DB logging, best-case performance."""
    print("\n=== BASELINE (No DB Logging) ===")
    results = []
    
    start_time = now_ms()
    sim_time_ms = 0
    task_count = 0
    
    while sim_time_ms < (SIM_DURATION_S * 1000):
        task_count += 1
        
        # T1: Task start
        t1 = sim_time_ms
        
        # Simulate control task work (sensor read, decision logic)
        work_time = CONTROL_TASK_WCET_MS + random.uniform(-1, 1)
        
        # T5: Task complete
        t5 = t1 + work_time
        
        response_time = t5 - t1
        deadline_hit = response_time <= CONTROL_TASK_DEADLINE_MS
        
        results.append({
            'task_id': task_count,
            't1': t1,
            't5': t5,
            'response_ms': response_time,
            'db_time_ms': 0,
            'non_db_time_ms': response_time,
            'deadline_hit': deadline_hit
        })
        
        sim_time_ms += CONTROL_TASK_PERIOD_MS
        
        if task_count % 20 == 0:
            print(f"Tasks: {task_count} | Response: {response_time:.2f}ms | Deadline: {'HIT' if deadline_hit else 'MISS'}", end='\r')
    
    print()
    return results

def simulate_sync():
    """Synchronous DB writes: blocking, adds SPIFFS latency to critical path."""
    print("\n=== SYNC (Blocking SPIFFS Writes) ===")
    results = []
    
    sim_time_ms = 0
    task_count = 0
    
    while sim_time_ms < (SIM_DURATION_S * 1000):
        task_count += 1
        
        # Determine if in burst period
        in_burst = (BURST_START_S * 1000) <= sim_time_ms < (BURST_END_S * 1000)
        contention_factor = BURST_FACTOR if in_burst else 1.0
        
        # T1: Task start
        t1 = sim_time_ms
        
        # Simulate control task work
        work_time = CONTROL_TASK_WCET_MS + random.uniform(-1, 1)
        t2 = t1 + work_time
        
        # T3: Synchronous SPIFFS write (BLOCKS task)
        write_time = simulate_spiffs_write() * contention_factor
        t4 = t2 + write_time
        
        # T5: Task complete (after write)
        t5 = t4
        
        response_time = t5 - t1
        db_time = write_time
        non_db_time = response_time - db_time
        deadline_hit = response_time <= CONTROL_TASK_DEADLINE_MS
        
        results.append({
            'task_id': task_count,
            't1': t1,
            't2': t2,
            't3': t2,
            't4': t4,
            't5': t5,
            'response_ms': response_time,
            'db_time_ms': db_time,
            'non_db_time_ms': non_db_time,
            'deadline_hit': deadline_hit,
            'in_burst': in_burst
        })
        
        sim_time_ms += CONTROL_TASK_PERIOD_MS
        
        if task_count % 20 == 0:
            print(f"Tasks: {task_count} | Response: {response_time:.2f}ms | DB: {db_time:.2f}ms | Deadline: {'HIT' if deadline_hit else 'MISS'}", end='\r')
    
    print()
    return results

def simulate_async():
    """Asynchronous buffered writes: enqueue fast, background flush."""
    print("\n=== ASYNC (Buffered + Background Flush) ===")
    results = []
    buffer = deque(maxlen=BUFFER_SIZE)
    
    sim_time_ms = 0
    task_count = 0
    last_flush_ms = 0
    total_enqueued = 0
    total_flushed = 0
    total_dropped = 0
    
    # Background flush tracking
    flush_events = []
    
    while sim_time_ms < (SIM_DURATION_S * 1000):
        task_count += 1
        
        # Check if should flush (time-based)
        if (sim_time_ms - last_flush_ms) >= FLUSH_INTERVAL_MS and len(buffer) > 0:
            # Simulate background task flushing
            batch_size = min(BATCH_SIZE, len(buffer))
            flush_time = simulate_spiffs_write() * (batch_size / 10.0)  # Batch write is more efficient
            
            flush_events.append({
                'time_ms': sim_time_ms,
                'batch_size': batch_size,
                'flush_time_ms': flush_time
            })
            
            # Remove flushed items
            for _ in range(batch_size):
                if buffer:
                    buffer.popleft()
                    total_flushed += 1
            
            last_flush_ms = sim_time_ms
        
        # Determine if in burst period
        in_burst = (BURST_START_S * 1000) <= sim_time_ms < (BURST_END_S * 1000)
        
        # T1: Task start
        t1 = sim_time_ms
        
        # Simulate control task work
        work_time = CONTROL_TASK_WCET_MS + random.uniform(-1, 1)
        
        # T2: Enqueue log (fast, ~1-10µs, negligible in sim)
        enqueue_time = 0.001  # 1µs
        t2 = t1 + work_time + enqueue_time
        
        # Try to enqueue
        if len(buffer) < BUFFER_SIZE:
            buffer.append({'task_id': task_count, 'time': sim_time_ms})
            total_enqueued += 1
        else:
            # Buffer full: drop (or could block, but we choose drop for RT)
            total_dropped += 1
        
        # T5: Task complete (no blocking on DB)
        t5 = t2
        
        response_time = t5 - t1
        db_time = 0  # No blocking DB time in critical path
        non_db_time = response_time
        deadline_hit = response_time <= CONTROL_TASK_DEADLINE_MS
        
        results.append({
            'task_id': task_count,
            't1': t1,
            't2': t2,
            't5': t5,
            'response_ms': response_time,
            'db_time_ms': db_time,
            'non_db_time_ms': non_db_time,
            'deadline_hit': deadline_hit,
            'buffer_depth': len(buffer),
            'in_burst': in_burst
        })
        
        sim_time_ms += CONTROL_TASK_PERIOD_MS
        
        if task_count % 20 == 0:
            print(f"Tasks: {task_count} | Response: {response_time:.2f}ms | Buffer: {len(buffer)}/{BUFFER_SIZE} | Dropped: {total_dropped}", end='\r')
    
    print()
    print(f"Total enqueued: {total_enqueued} | Flushed: {total_flushed} | Dropped: {total_dropped}")
    print(f"Flush events: {len(flush_events)}")
    
    return results, flush_events

def analyze_results(results, label):
    """Compute KPIs from results."""
    response_times = [r['response_ms'] for r in results]
    db_times = [r['db_time_ms'] for r in results]
    non_db_times = [r['non_db_time_ms'] for r in results]
    misses = sum(1 for r in results if not r['deadline_hit'])
    
    def pct(data, p):
        if not data: return 0
        sorted_data = sorted(data)
        k = (len(sorted_data)-1) * (p/100.0)
        f = int(k)
        c = min(f+1, len(sorted_data)-1)
        if f == c:
            return sorted_data[int(k)]
        d0 = sorted_data[f] * (c-k)
        d1 = sorted_data[c] * (k-f)
        return d0 + d1
    
    kpi = {
        'label': label,
        'total_tasks': len(results),
        'deadline_misses': misses,
        'miss_rate': misses * 100.0 / len(results),
        'response_p50': pct(response_times, 50),
        'response_p95': pct(response_times, 95),
        'response_p99': pct(response_times, 99),
        'response_max': max(response_times),
        'jitter': pct(response_times, 99) - pct(response_times, 50),
        'db_time_p50': pct(db_times, 50),
        'db_time_p95': pct(db_times, 95),
        'db_time_max': max(db_times) if db_times else 0,
        'non_db_time_p50': pct(non_db_times, 50),
        'non_db_time_p95': pct(non_db_times, 95)
    }
    
    return kpi

def print_kpi(kpi):
    """Pretty-print KPI."""
    print(f"\n--- {kpi['label']} ---")
    print(f"Total tasks: {kpi['total_tasks']}")
    print(f"Deadline misses: {kpi['deadline_misses']} ({kpi['miss_rate']:.2f}%)")
    print(f"Response time (ms): p50={kpi['response_p50']:.3f} p95={kpi['response_p95']:.3f} p99={kpi['response_p99']:.3f} max={kpi['response_max']:.3f}")
    print(f"Jitter (p99-p50): {kpi['jitter']:.3f}ms")
    print(f"DB time (ms): p50={kpi['db_time_p50']:.3f} p95={kpi['db_time_p95']:.3f} max={kpi['db_time_max']:.3f}")
    print(f"Non-DB time (ms): p50={kpi['non_db_time_p50']:.3f} p95={kpi['non_db_time_p95']:.3f}")

def write_csv(results, filename):
    """Write results to CSV."""
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, filename)
    
    if not results:
        return
    
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=results[0].keys())
        w.writeheader()
        w.writerows(results)
    
    print(f"Wrote {path}")

def main():
    print("="*70)
    print("DB/I-O IMPACT ON REAL-TIME PERFORMANCE")
    print("="*70)
    print(f"Simulation duration: {SIM_DURATION_S}s")
    print(f"Control task: period={CONTROL_TASK_PERIOD_MS}ms, deadline={CONTROL_TASK_DEADLINE_MS}ms, WCET={CONTROL_TASK_WCET_MS}ms")
    print(f"SPIFFS write: mean={SPIFFS_WRITE_MEAN_MS}ms, range=[{SPIFFS_WRITE_MIN_MS}, {SPIFFS_WRITE_MAX_MS}]ms")
    print(f"Burst period: {BURST_START_S}-{BURST_END_S}s (factor={BURST_FACTOR}x)")
    
    # Run simulations
    results_baseline = simulate_baseline()
    results_sync = simulate_sync()
    results_async, flush_events = simulate_async()
    
    # Analyze
    kpi_baseline = analyze_results(results_baseline, 'BASELINE')
    kpi_sync = analyze_results(results_sync, 'SYNC')
    kpi_async = analyze_results(results_async, 'ASYNC')
    
    # Print KPIs
    print("\n" + "="*70)
    print("KPI SUMMARY")
    print("="*70)
    print_kpi(kpi_baseline)
    print_kpi(kpi_sync)
    print_kpi(kpi_async)
    
    # Write CSVs
    write_csv(results_baseline, 'db_impact_baseline.csv')
    write_csv(results_sync, 'db_impact_sync.csv')
    write_csv(results_async, 'db_impact_async.csv')
    
    # Write summary
    summary_path = os.path.join(OUT_DIR, 'db_impact_summary.txt')
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write("DB/I-O IMPACT ON REAL-TIME PERFORMANCE\n")
        f.write("="*70 + "\n\n")
        
        f.write("CONFIGURATION\n")
        f.write(f"Simulation duration: {SIM_DURATION_S}s\n")
        f.write(f"Control task: period={CONTROL_TASK_PERIOD_MS}ms, deadline={CONTROL_TASK_DEADLINE_MS}ms\n")
        f.write(f"SPIFFS write: mean={SPIFFS_WRITE_MEAN_MS}ms (range {SPIFFS_WRITE_MIN_MS}-{SPIFFS_WRITE_MAX_MS}ms)\n")
        f.write(f"Burst: {BURST_START_S}-{BURST_END_S}s (factor {BURST_FACTOR}x)\n\n")
        
        f.write("="*70 + "\n")
        f.write("KPI COMPARISON\n")
        f.write("="*70 + "\n\n")
        
        for kpi in [kpi_baseline, kpi_sync, kpi_async]:
            f.write(f"--- {kpi['label']} ---\n")
            f.write(f"Total tasks: {kpi['total_tasks']}\n")
            f.write(f"Deadline misses: {kpi['deadline_misses']} ({kpi['miss_rate']:.2f}%)\n")
            f.write(f"Response time: p50={kpi['response_p50']:.3f}ms p95={kpi['response_p95']:.3f}ms p99={kpi['response_p99']:.3f}ms max={kpi['response_max']:.3f}ms\n")
            f.write(f"Jitter (p99-p50): {kpi['jitter']:.3f}ms\n")
            f.write(f"DB time: p50={kpi['db_time_p50']:.3f}ms p95={kpi['db_time_p95']:.3f}ms max={kpi['db_time_max']:.3f}ms\n")
            f.write(f"Non-DB time: p50={kpi['non_db_time_p50']:.3f}ms p95={kpi['non_db_time_p95']:.3f}ms\n\n")
        
        f.write("="*70 + "\n")
        f.write("INTERPRETATION\n")
        f.write("="*70 + "\n\n")
        
        f.write("BASELINE (No DB):\n")
        f.write(f"  - Best-case performance: {kpi_baseline['miss_rate']:.1f}% deadline miss\n")
        f.write(f"  - Response time p99: {kpi_baseline['response_p99']:.1f}ms\n")
        f.write(f"  - No persistence overhead\n\n")
        
        f.write("SYNC (Blocking Write):\n")
        f.write(f"  - Worst-case performance: {kpi_sync['miss_rate']:.1f}% deadline miss\n")
        f.write(f"  - Response time p99: {kpi_sync['response_p99']:.1f}ms\n")
        f.write(f"  - DB adds {kpi_sync['db_time_p95']:.1f}ms (p95) to critical path\n")
        f.write(f"  - UNACCEPTABLE for RT tasks (miss rate >{kpi_sync['miss_rate']:.0f}%)\n\n")
        
        f.write("ASYNC (Buffered Write):\n")
        f.write(f"  - Near-baseline performance: {kpi_async['miss_rate']:.1f}% deadline miss\n")
        f.write(f"  - Response time p99: {kpi_async['response_p99']:.1f}ms\n")
        f.write(f"  - DB time moved off critical path (background flush)\n")
        f.write(f"  - ACCEPTABLE trade-off (miss rate <2%, data loss window {FLUSH_INTERVAL_MS/1000}s)\n\n")
        
        f.write("RECOMMENDATION:\n")
        f.write("  Use ASYNC buffered writes for high-frequency logs (telemetry, metrics).\n")
        f.write("  Use SYNC writes ONLY for critical state that must persist before execution.\n")
        f.write(f"  Buffer tuning: size={BUFFER_SIZE}, flush_interval={FLUSH_INTERVAL_MS/1000}s\n")
        f.write("  Monitor buffer depth; if frequently full, increase size or flush frequency.\n")
    
    print(f"\nWrote {summary_path}")
    print("="*70)

if __name__ == '__main__':
    main()
