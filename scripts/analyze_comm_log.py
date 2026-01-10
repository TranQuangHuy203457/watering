#!/usr/bin/env python3
import csv
import statistics
import os

CSV_PATH = 'results/comm_control_log.csv'

latencies = []
exec_times = []
missing_ack = 0
rows = []
with open(CSV_PATH, newline='') as f:
    r = csv.DictReader(f)
    for row in r:
        rows.append(row)
        try:
            t1 = int(row['t1_us'])
            tx_start = int(row['tx_start_us'])
            tx_end = int(row['tx_end_us'])
            lat = (tx_start - t1)/1000.0
            ex = (tx_end - tx_start)/1000.0
            latencies.append(lat)
            exec_times.append(ex)
        except Exception:
            continue
        if not row.get('ack_recv_us'):
            missing_ack += 1
        # collect server receive and rtt if present
        try:
            srv_recv = int(row['srv_recv_us']) if row.get('srv_recv_us') else None
        except Exception:
            srv_recv = None
        try:
            ack_recv = int(row['ack_recv_us']) if row.get('ack_recv_us') else None
        except Exception:
            ack_recv = None
        # store E2E if available
        row['_srv_recv'] = srv_recv
        row['_ack_recv'] = ack_recv

def pct(data,p):
    if not data: return 0
    data=sorted(data)
    k=(len(data)-1)*(p/100.0)
    f=int(k)
    c=min(f+1,len(data)-1)
    if f==c:
        return data[int(k)]
    d0=data[f]*(c-k)
    d1=data[c]*(k-f)
    return d0+d1

print(f"rows={len(rows)} samples={len(latencies)} missing_ack={missing_ack}")
for label,arr in [('latency_ms',latencies),('exec_ms',exec_times)]:
    if not arr:
        print(label, 'no data')
        continue
    print(f"{label}: p50={pct(arr,50):.3f} p95={pct(arr,95):.3f} p99={pct(arr,99):.3f} max={max(arr):.3f} mean={statistics.mean(arr):.3f}")

# write summary
os.makedirs('results', exist_ok=True)
with open('results/comm_control_summary.txt','w') as f:
    f.write(f"rows={len(rows)} samples={len(latencies)} missing_ack={missing_ack}\n")
    for label,arr in [('latency_ms',latencies),('exec_ms',exec_times)]:
        if not arr:
            f.write(label+': no data\n')
            continue
        f.write(f"{label}: p50={pct(arr,50):.3f} p95={pct(arr,95):.3f} p99={pct(arr,99):.3f} max={max(arr):.3f} mean={statistics.mean(arr):.3f}\n")
    # E2E stats when server recv and ack present
    e2e = []
    rtts = []
    for row in rows:
        srv = row.get('_srv_recv')
        ack = row.get('_ack_recv')
        try:
            t1 = int(row['t1_us'])
        except Exception:
            t1 = None
        if srv and t1:
            e2e.append((srv - t1)/1000.0)
        if ack and t1:
            rtts.append((int(ack) - t1)/1000.0)
    if e2e:
        f.write('e2e_ms: p50={:.3f} p95={:.3f} p99={:.3f} max={:.3f} mean={:.3f}\n'.format(pct(e2e,50), pct(e2e,95), pct(e2e,99), max(e2e), statistics.mean(e2e)))
    if rtts:
        f.write('rtt_ms: p50={:.3f} p95={:.3f} p99={:.3f} max={:.3f} mean={:.3f}\n'.format(pct(rtts,50), pct(rtts,95), pct(rtts,99), max(rtts), statistics.mean(rtts)))
print('Wrote results/comm_control_summary.txt')
