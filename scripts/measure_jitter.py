#!/usr/bin/env python3
"""
Simulate periodic task activations and measure jitter/latency statistics.
This host-side script runs synthetic tasks invoking a worker function and
measures start-time jitter and execution latency.

Run:
    Normal (không overload):
        python scripts/measure_jitter.py --mode normal
    Overload/burst:
        python scripts/measure_jitter.py --mode overload

Produces: CSV logs và các KPI p50/p95/p99/max cho từng task
"""
import time
import random
import statistics
import csv
import argparse

# Giá trị mặc định, sẽ được override theo --mode
OUT_CSV = 'results/jitter_baseline.csv'

# Simulation params
SIM_S = 60  # seconds
TICK_MS = 10

# Task definitions: (name, period_ms, nominal_work_ms, priority)
TASKS = [
    ("SwitchTask", 500, 6, 5),
    ("SoilTask", 500, 5, 4),
    ("Display", 1000, 10, 2),
]

# noise factor injection during burst (sẽ được cấu hình theo mode)
BURST_START_S = 20
BURST_END_S = 30
BURST_FACTOR = 200


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
        # (scheduled_us, actual_start_us, latency_us, exec_us, deadline_ms, result)
        self.samples = []

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

            # Deadline = period tính từ thời điểm scheduled
            deadline_ms = self.period_ms
            deadline_us = scheduled_us + deadline_ms * 1000
            result = 'HIT' if exec_end <= deadline_us else 'MISS'

            self.samples.append((scheduled_us, exec_start, latency_us, exec_us, deadline_ms, result))
            # schedule next
            self.next_ms += self.period_ms


def run_sim():
    start = time.time()
    sim_start_s = start
    tasks = [PeriodicTask(*t) for t in TASKS]
    end_time = sim_start_s + SIM_S
    while time.time() < end_time:
        # Tính thời gian hiện tại theo "đồng hồ thực" của mô phỏng
        now_ms = (time.time() - sim_start_s) * 1000.0
        for task in tasks:
            task.schedule_if_due(now_ms, sim_start_s)
        time.sleep(TICK_MS / 1000.0)

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
        w.writerow(['task','scheduled_us','start_us','latency_us','exec_us','deadline_ms','result'])
        for r in rows:
            w.writerow(r)

    # stats
    for task in tasks:
        if not task.samples:
            continue

        lat = [s[2] for s in task.samples]
        lat_ms = [l/1000.0 for l in lat]
        total = len(task.samples)
        misses = sum(1 for s in task.samples if s[5] == 'MISS')
        hits = total - misses
        miss_rate = misses / total if total else 0.0

        print(f"Task {task.name}: samples={total} hits={hits} misses={misses} miss_rate={miss_rate*100:.1f}% "
              f"p50={statistics.median(lat_ms):.3f}ms p95={percentile(lat_ms,95):.3f}ms "
              f"p99={percentile(lat_ms,99):.3f}ms max={max(lat_ms):.3f}ms")


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
    parser = argparse.ArgumentParser(description='Jitter simulator with normal/overload modes')
    parser.add_argument('--mode', choices=['normal', 'overload'], default='overload',
                        help='Simulation mode: normal (no burst) or overload (with burst)')
    args = parser.parse_args()

    # Cấu hình theo mode
    if args.mode == 'normal':
        OUT_CSV = 'results/jitter_normal.csv'
        BURST_FACTOR = 1  # không nhân thêm tải
    else:
        OUT_CSV = 'results/jitter_overload.csv'
        BURST_FACTOR = 200  # giữ nguyên hệ số burst hiện tại

    print(f"Running jitter simulation in {args.mode} mode → {OUT_CSV}")
    run_sim()
    print('Wrote', OUT_CSV)
