#!/usr/bin/env python3
"""
Simulate periodic task activations and measure jitter/latency statistics.
This host-side script runs synthetic tasks invoking a worker function and
measures start-time jitter and execution latency.

Run: python scripts/measure_jitter.py
Produces: CSV logs and printed p50/p95/p99/max
"""
import time
import random
import statistics
import csv

OUT_CSV = 'results/jitter_baseline.csv'

# Simulation params
SIM_S = 60  # seconds
TICK_MS = 10

# Task definitions: (name, period_ms, nominal_work_ms, priority)
TASKS = [
    ("Switch", 1000, 5, 5),
    ("Sensor", 200, 2, 4),
    ("Display", 1000, 1, 2),
]

# noise factor injection during burst
BURST_START_S = 20
BURST_END_S = 30
BURST_FACTOR = 8


def now_us():
    return int(time.time() * 1_000_000)


def work(duration_ms):
    # busy-wait to simulate work (coarse)
    target = now_us() + int(duration_ms * 1000)
    while now_us() < target:
        pass


class PeriodicTask:
    def __init__(self, name, period_ms, work_ms, prio):
        self.name = name
        self.period_ms = period_ms
        self.work_ms = work_ms
        self.prio = prio
        self.next_ms = 0
        self.samples = []  # (scheduled_us, actual_start_us, latency_us, exec_us)

    def schedule_if_due(self, now_ms, sim_start_s):
        if now_ms >= self.next_ms:
            # scheduled
            scheduled_us = int(sim_start_s*1_000_000) + int(self.next_ms*1000)
            # compute work with burst factor
            work_ms = self.work_ms
            t_s = time.time() - sim_start_s
            if BURST_START_S <= t_s < BURST_END_S:
                work_ms *= BURST_FACTOR
            start_us = now_us()
            exec_start = now_us()
            work(work_ms)
            exec_end = now_us()
            latency_us = exec_start - scheduled_us
            exec_us = exec_end - exec_start
            self.samples.append((scheduled_us, exec_start, latency_us, exec_us))
            # schedule next
            self.next_ms += self.period_ms


def run_sim():
    start = time.time()
    sim_start_s = start
    tasks = [PeriodicTask(*t) for t in TASKS]
    t_ms = 0
    end_time = sim_start_s + SIM_S
    while time.time() < end_time:
        # tick
        for task in tasks:
            task.schedule_if_due(t_ms, sim_start_s)
        time.sleep(TICK_MS / 1000.0)
        t_ms += TICK_MS

    # gather samples
    rows = []
    for task in tasks:
        for s in task.samples:
            rows.append((task.name,) + s)
    # write csv
    import os
    os.makedirs('results', exist_ok=True)
    with open(OUT_CSV, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['task','scheduled_us','start_us','latency_us','exec_us'])
        for r in rows:
            w.writerow(r)

    # stats
    for task in tasks:
        lat = [s[2] for s in task.samples]
        if not lat:
            continue
        lat_ms = [l/1000.0 for l in lat]
        print(f"Task {task.name}: samples={len(lat_ms)} p50={statistics.median(lat_ms):.3f}ms p95={percentile(lat_ms,95):.3f}ms p99={percentile(lat_ms,99):.3f}ms max={max(lat_ms):.3f}ms")


def percentile(data, p):
    if not data:
        return 0.0
    data = sorted(data)
    k = (len(data)-1) * (p/100.0)
    f = int(k)
    c = min(f+1, len(data)-1)
    if f == c:
        return data[int(k)]
    d0 = data[f] * (c-k)
    d1 = data[c] * (k-f)
    return d0 + d1


if __name__ == '__main__':
    run_sim()
    print('Wrote', OUT_CSV)
