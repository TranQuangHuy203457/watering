#!/usr/bin/env python3
"""
Simulate periodic tasks under overload bursts and compare two schedulers:
 - baseline: static-priority, non-preemptive (FIFO within priority)
 - improved: earliest-deadline-first (preemptive simulated)

Produces:
 - timeline log with arrival/start/finish/deadline/hit-miss
 - KPI table (deadline miss rate, avg response, max lateness) for each config

Run: python scripts/simulate_overload.py
"""
import time
import heapq
import random

SIM_MS = 120_000  # total simulation time in ms
TIME_QUANTUM = 1  # ms quantum for preemptive simulation
SEQ = 0

class Job:
    def __init__(self, task, arrival, wcet, period):
        self.task = task
        self.arrival = arrival
        self.wcet = wcet
        self.rem = wcet
        self.period = period
        self.deadline = arrival + period
        self.start = None
        self.finish = None
        self.id = f"{task}@{arrival}"

    def response(self):
        return (self.finish - self.arrival) if self.finish is not None else None


# Task definitions (period in ms, wcet in ms)
TASKS = [
    ("Sensor", 2000, 50, 1),
    ("Network", 10000, 300, 3),
    ("Display", 5000, 100, 2),
    ("Switch", 60000, 200, 2),
]
# last element is static priority (lower -> higher priority)

# overload burst: between these ms inject extra load or multiply WCET
# We'll run multiple scenarios; these are defaults but overridden per-scenario
BURST_START = 30_000
BURST_END = 40_000
BURST_FACTOR = 4  # multiply WCET in burst


def generate_jobs_for_scenario(burst_start, burst_end, burst_factor, inject_sporadic=False):
    jobs = []
    for name, period, wcet, prio in TASKS:
        t = 0
        while t < SIM_MS:
            jobs.append((t, name, period, wcet, prio))
            t += period
    # optionally inject extra sporadic heavy jobs during burst to force overload
    if inject_sporadic:
        mid = burst_start + (burst_end - burst_start)//2
        # add several heavy sporadic tasks at nearly same arrival with tight deadlines
        for i in range(5):
            # (arrival, name, period, wcet, prio)
            jobs.append((mid + i*5, f"Sporadic{i}", 2000, 1000, 5))
    jobs.sort()
    # return precomputed jobs plus burst params via closure
    return jobs, (burst_start, burst_end, burst_factor)


def generate_jobs():
    # kept for backward compatibility; simple moderate scenario
    return generate_jobs_for_scenario(BURST_START, BURST_END, BURST_FACTOR)[0]


def run_baseline(jobs):
    # Static-priority non-preemptive: pick highest priority ready job and run to completion
    log = []
    t = 0
    pending = []
    job_objs = []
    jobs_iter = iter(jobs)
    next_job = None
    try:
        next_job = next(jobs_iter)
    except StopIteration:
        next_job = None

    while t < SIM_MS or pending:
        # bring arrivals
        while next_job and next_job[0] <= t:
            arr, name, period, wcet, prio = next_job
            actual_wcet = wcet * (BURST_FACTOR if BURST_START <= arr < BURST_END else 1)
            j = Job(name, arr, actual_wcet, period)
            j.priority = prio
            pending.append(j)
            job_objs.append(j)
            try:
                next_job = next(jobs_iter)
            except StopIteration:
                next_job = None
        if pending:
            # pick highest priority (lowest number), FIFO among same priority
            pending.sort(key=lambda x: (x.priority, x.arrival))
            cur = pending.pop(0)
            cur.start = max(t, cur.arrival)
            # run to completion non-preemptive
            run_time = cur.rem
            t = cur.start + run_time
            cur.finish = t
            cur.rem = 0
            hit = cur.finish <= cur.deadline
            log.append((cur.arrival, cur.start, cur.finish, cur.deadline, cur.task, hit))
        else:
            # idle advance to next arrival
            if next_job:
                t = next_job[0]
            else:
                break
    return log


def run_edf(jobs):
    # Preemptive EDF simulated with 1ms quantum
    log = []
    t = 0
    job_objs = []
    arrivals = list(jobs)
    ready = []  # heap by deadline

    while t < SIM_MS or ready or arrivals:
        # bring arrivals at current time
        while arrivals and arrivals[0][0] <= t:
            arr, name, period, wcet, prio = arrivals.pop(0)
            actual_wcet = wcet * (BURST_FACTOR if BURST_START <= arr < BURST_END else 1)
            j = Job(name, arr, actual_wcet, period)
            job_objs.append(j)
            # use a monotonic sequence to avoid Job comparison on ties
            global SEQ
            SEQ += 1
            heapq.heappush(ready, (j.deadline, SEQ, j))
        if ready:
            _, _, cur = heapq.heappop(ready)
            if cur.start is None:
                cur.start = t
            # execute one quantum
            work = min(TIME_QUANTUM, cur.rem)
            cur.rem -= work
            t += work
            # if not finished, push back
            if cur.rem > 0:
                SEQ += 1
                heapq.heappush(ready, (cur.deadline, SEQ, cur))
            else:
                cur.finish = t
                hit = cur.finish <= cur.deadline
                log.append((cur.arrival, cur.start, cur.finish, cur.deadline, cur.task, hit))
        else:
            # advance to next arrival
            if arrivals:
                t = arrivals[0][0]
            else:
                break
    return log


def compute_kpis(log):
    per_task = {}
    for arr, start, finish, dl, task, hit in log:
        if task not in per_task:
            per_task[task] = { 'count':0, 'miss':0, 'responses':[], 'max_lateness':0 }
        per_task[task]['count'] += 1
        if not hit:
            per_task[task]['miss'] += 1
        resp = finish - arr
        per_task[task]['responses'].append(resp)
        lateness = max(0, finish - dl)
        per_task[task]['max_lateness'] = max(per_task[task]['max_lateness'], lateness)
    # overall
    total = sum(v['count'] for v in per_task.values())
    total_miss = sum(v['miss'] for v in per_task.values())
    overall = {
        'total_jobs': total,
        'total_miss': total_miss,
        'miss_rate': total_miss/total if total>0 else 0
    }
    # per-task KPI format
    table = []
    for task, v in per_task.items():
        avg = sum(v['responses'])/len(v['responses'])
        table.append((task, v['count'], v['miss'], v['miss']/v['count'], avg, v['max_lateness']))
    return overall, table


def print_timeline(log, max_lines=50):
    print('--- TIMELINE ---')
    printed = 0
    for arr, start, finish, dl, task, hit in sorted(log, key=lambda x: (x[1], x[0])):
        print(f"t={arr:6d} start={start:6d} finish={finish:6d} dl={dl:6d} task={task:8s} {'HIT' if hit else 'MISS'}")
        printed += 1
        if printed>=max_lines:
            break


def run_compare():
    base_jobs = generate_jobs()
    print('Generated jobs:', len(base_jobs))

    print('\nRunning baseline (static-priority non-preemptive) ...')
    log_base = run_baseline(list(base_jobs))
    overall_b, table_b = compute_kpis(log_base)
    print_timeline(log_base, max_lines=40)

    print('\nRunning improved (EDF preemptive) ...')
    log_edf = run_edf(list(base_jobs))
    overall_e, table_e = compute_kpis(log_edf)
    print_timeline(log_edf, max_lines=40)

    print('\n--- KPI SUMMARY ---')
    print('Config, total_jobs, total_miss, miss_rate')
    print(f"baseline, {overall_b['total_jobs']}, {overall_b['total_miss']}, {overall_b['miss_rate']:.3f}")
    print(f"edf,      {overall_e['total_jobs']}, {overall_e['total_miss']}, {overall_e['miss_rate']:.3f}")

    print('\nPer-task KPIs (task, count, miss, miss_rate, avg_resp_ms, max_lateness_ms)')
    print('\nBaseline:')
    for row in sorted(table_b):
        print(row)
    print('\nEDF:')
    for row in sorted(table_e):
        print(row)

    # return logs for optional further analysis
    return log_base, log_edf, (overall_b, table_b), (overall_e, table_e)


if __name__ == '__main__':
    # Run two scenarios: moderate (no sporadic injection) and severe (heavy burst + sporadic)
    scenarios = [
        (30000, 40000, 4, False, 'moderate burst (x4)'),
        (30000, 35000, 10, True, 'severe burst (x10) + sporadic heavy jobs'),
    ]

    for bs, be, bf, inj, desc in scenarios:
        print('\n' + '='*60)
        print(f"Scenario: {desc} -- burst {bs}-{be} factor={bf} inject_sporadic={inj}")
        jobs, params = generate_jobs_for_scenario(bs, be, bf, inject_sporadic=inj)
        # set globals so run_baseline/run_edf use the scenario burst parameters
        BURST_START, BURST_END, BURST_FACTOR = bs, be, bf
        print('Generated jobs:', len(jobs))

        print('\n- Baseline -')
        log_base = run_baseline(list(jobs))
        overall_b, table_b = compute_kpis(log_base)
        print_timeline(log_base, max_lines=30)

        print('\n- EDF -')
        log_edf = run_edf(list(jobs))
        overall_e, table_e = compute_kpis(log_edf)
        print_timeline(log_edf, max_lines=30)

        print('\n--- KPI SUMMARY ---')
        print('Config, total_jobs, total_miss, miss_rate')
        print(f"baseline, {overall_b['total_jobs']}, {overall_b['total_miss']}, {overall_b['miss_rate']:.3f}")
        print(f"edf,      {overall_e['total_jobs']}, {overall_e['total_miss']}, {overall_e['miss_rate']:.3f}")

        print('\nPer-task KPIs (task, count, miss, miss_rate, avg_resp_ms, max_lateness_ms)')
        print('\nBaseline:')
        for row in sorted(table_b):
            print(row)
        print('\nEDF:')
        for row in sorted(table_e):
            print(row)
