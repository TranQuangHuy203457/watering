#!/usr/bin/env python3
"""
Generate final RT communication report comparing baseline vs bad-case scenarios.
Analyzes all comm logs and produces comprehensive E2E metrics.
"""
import csv
import statistics
import os
import glob

def pct(data, p):
    if not data: return 0
    data = sorted(data)
    k = (len(data)-1) * (p/100.0)
    f = int(k)
    c = min(f+1, len(data)-1)
    if f == c:
        return data[int(k)]
    d0 = data[f] * (c-k)
    d1 = data[c] * (k-f)
    return d0 + d1

def analyze_log(csv_path):
    """Analyze a single comm log file and return metrics."""
    if not os.path.exists(csv_path):
        return None
    
    results = {
        'file': os.path.basename(csv_path),
        'total': 0,
        'success': 0,
        'timeout': 0,
        'latency_ms': [],  # T1 -> tx_start
        'exec_ms': [],     # tx_start -> tx_end
        'e2e_ms': [],      # T1 -> srv_recv
        'rtt_ms': []       # tx_start -> ack_recv
    }
    
    with open(csv_path, newline='') as f:
        r = csv.DictReader(f)
        for row in r:
            results['total'] += 1
            try:
                t1 = int(row['t1_us'])
                tx_start = int(row['tx_start_us'])
                tx_end = int(row['tx_end_us'])
                results['latency_ms'].append((tx_start - t1)/1000.0)
                results['exec_ms'].append((tx_end - tx_start)/1000.0)
                
                if row.get('srv_recv_us') and row['srv_recv_us']:
                    srv = int(row['srv_recv_us'])
                    results['e2e_ms'].append((srv - t1)/1000.0)
                    results['success'] += 1
                else:
                    results['timeout'] += 1
                
                if row.get('rtt_us') and row['rtt_us']:
                    results['rtt_ms'].append(int(row['rtt_us'])/1000.0)
            except Exception as e:
                continue
    
    return results

def format_stats(data, label):
    if not data:
        return f"{label}: NO DATA"
    return f"{label}: p50={pct(data,50):.3f} p95={pct(data,95):.3f} p99={pct(data,99):.3f} max={max(data):.3f} mean={statistics.mean(data):.3f}"

def main():
    print("="*70)
    print("REAL-TIME COMMUNICATION FINAL REPORT")
    print("="*70)
    
    # Find all comm logs
    logs = glob.glob('results/comm_*_log.csv')
    
    if not logs:
        print("No comm logs found in results/")
        return
    
    print(f"\nFound {len(logs)} log files:")
    for log in logs:
        print(f"  - {os.path.basename(log)}")
    
    print("\n" + "="*70)
    print("DETAILED ANALYSIS")
    print("="*70)
    
    all_results = {}
    for log_path in logs:
        results = analyze_log(log_path)
        if results:
            log_name = os.path.basename(log_path).replace('comm_', '').replace('_log.csv', '')
            all_results[log_name] = results
            
            print(f"\n--- {log_name.upper()} ---")
            print(f"Total messages: {results['total']}")
            print(f"Success: {results['success']} ({results['success']*100.0/results['total']:.1f}%)")
            print(f"Timeout/Loss: {results['timeout']} ({results['timeout']*100.0/results['total']:.1f}%)")
            print()
            print(format_stats(results['latency_ms'], 'T1→TX_START (ms)'))
            print(format_stats(results['exec_ms'], 'TX_DURATION (ms)'))
            print(format_stats(results['e2e_ms'], 'E2E_T1→SRV (ms)'))
            print(format_stats(results['rtt_ms'], 'RTT (ms)'))
    
    # Write summary
    summary_path = 'results/final_comm_summary.txt'
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write("REAL-TIME COMMUNICATION FINAL REPORT\n")
        f.write("="*70 + "\n\n")
        
        for name, res in all_results.items():
            f.write(f"--- {name.upper()} ---\n")
            f.write(f"Total: {res['total']} | Success: {res['success']} ({res['success']*100.0/res['total']:.1f}%) | Loss: {res['timeout']} ({res['timeout']*100.0/res['total']:.1f}%)\n")
            f.write(format_stats(res['latency_ms'], 'T1→TX_START') + '\n')
            f.write(format_stats(res['exec_ms'], 'TX_DURATION') + '\n')
            f.write(format_stats(res['e2e_ms'], 'E2E_T1→SRV') + '\n')
            f.write(format_stats(res['rtt_ms'], 'RTT') + '\n')
            f.write('\n')
        
        # Interpretation
        f.write("\n" + "="*70 + "\n")
        f.write("INTERPRETATION\n")
        f.write("="*70 + "\n\n")
        f.write("Timestamping points:\n")
        f.write("  T1: Message creation (producer)\n")
        f.write("  T2: Queue insertion (enqueue)\n")
        f.write("  T3: Socket send start (tx_start)\n")
        f.write("  T4: Socket send complete (tx_end)\n")
        f.write("  T5: Server receive (srv_recv)\n")
        f.write("  T6: Client ACK receive (ack_recv)\n\n")
        f.write("End-to-end latency components:\n")
        f.write("  - Queueing delay: T2 - T1 (negligible in simulation)\n")
        f.write("  - Processing delay: T3 - T2 (measured as T1→TX_START)\n")
        f.write("  - I/O wait: T4 - T3 (TX_DURATION)\n")
        f.write("  - Network propagation: T5 - T4 (included in E2E)\n")
        f.write("  - Server processing: included in RTT\n")
        f.write("  - Return propagation: T6 - T5 (included in RTT)\n\n")
        f.write("Bad-case behavior:\n")
        f.write("  - Packet loss: shown in Timeout/Loss percentage\n")
        f.write("  - Increased latency: shown in p95/p99 metrics\n")
        f.write("  - Jitter: difference between p50 and p99\n")
    
    print("\n" + "="*70)
    print(f"Summary written to: {summary_path}")
    print("="*70)

if __name__ == '__main__':
    main()
