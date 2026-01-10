#!/usr/bin/env python3
"""
Instrumented message sender to simulate device-side timestamps T1..T4 and measure E2E.
This script runs a local UDP echo server (or can send to remote) and logs timestamps.

Timestamping points:
  T1 (t1_us): Message creation/producer timestamp
  T2 (enqueue_us): Queue/send buffer timestamp
  T3 (tx_start_us): Socket send start
  T4 (tx_end_us): Socket send complete
  T5 (srv_recv_us): Server receive timestamp (from echo)
  T6 (ack_recv_us): Client ACK receive timestamp
  RTT: Round-trip time (tx_start -> ack_recv)

Run examples:
  # start clean server
  python scripts/comm_instrument.py --server --port 5005
  
  # start bad-case server (50ms delay, 20% drop)
  python scripts/comm_instrument.py --server --port 5005 --badcase --delay-ms 50 --drop-prob 0.2
  
  # run baseline sender (30 messages, 5ms interval)
  python scripts/comm_instrument.py --target 127.0.0.1 --port 5005 --type baseline --count 30 --interval-ms 5
  
  # run control sender with burst (50 messages, 10ms interval, burst at msg 20-30)
  python scripts/comm_instrument.py --target 127.0.0.1 --port 5005 --type control --count 50 --interval-ms 10 --burst

Outputs: results/comm_<type>_log.csv
"""
import socket
import time
import argparse
import os
import csv
import random
import sys

OUT_DIR = 'results'

now_us = lambda: int(time.time()*1_000_000)
now_ms = lambda: int(time.time()*1000)


def run_server(port, badcase=False, delay_ms=0, drop_prob=0.0):
    """
    UDP echo server that timestamps incoming packets and echoes them back.
    Supports bad-case mode with configurable delay and packet drop.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', port))
    
    mode = 'BADCASE' if badcase else 'CLEAN'
    print(f'[SERVER] UDP echo server running on port {port}')
    print(f'[SERVER] Mode: {mode} | Delay: {delay_ms}ms | Drop: {drop_prob*100:.0f}%')
    
    msg_count = 0
    dropped = 0
    
    try:
        while True:
            data, addr = s.recvfrom(65535)
            msg_count += 1
            
            # simulate bad-case: random drop
            if badcase and (drop_prob > 0.0) and (random.random() < drop_prob):
                dropped += 1
                if msg_count % 10 == 0:
                    print(f'[SERVER] Received {msg_count} | Dropped {dropped}', end='\r')
                continue
            
            # optional processing delay (simulate server load)
            if badcase and delay_ms > 0:
                time.sleep(delay_ms/1000.0)
            
            # add server receive timestamp and send it back
            srv_recv = now_us()
            resp = data + b'|SRV|' + str(srv_recv).encode()
            
            try:
                s.sendto(resp, addr)
            except Exception as e:
                print(f'[SERVER] Send error: {e}')
            
            if msg_count % 10 == 0:
                print(f'[SERVER] Received {msg_count} | Dropped {dropped}', end='\r')
                
    except KeyboardInterrupt:
        print(f'\n[SERVER] Stopped. Total received: {msg_count}, Dropped: {dropped}')


def send_messages(target, port, mtype, count, interval_ms, burst=False, timeout_ms=100):
    """
    Send instrumented messages and log timestamps.
    
    Args:
        target: Target IP address
        port: Target port
        mtype: Message type label (e.g., 'control', 'telemetry')
        count: Number of messages to send
        interval_ms: Interval between messages in milliseconds
        burst: Enable burst mode (sends burst at messages 20-30)
        timeout_ms: Socket timeout in milliseconds
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    out_csv = os.path.join(OUT_DIR, f'comm_{mtype}_log.csv')
    
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4*1024*1024)
    
    # optional DSCP mark for priority (requires rights on some OS)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)  # DSCP EF
    except Exception:
        pass

    print(f'[CLIENT] Sending {count} messages to {target}:{port}')
    print(f'[CLIENT] Type: {mtype} | Interval: {interval_ms}ms | Burst: {burst} | Timeout: {timeout_ms}ms')
    
    success = 0
    timeouts = 0
    errors = 0
    
    with open(out_csv, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['seq','t1_us','enqueue_us','tx_start_us','tx_end_us','srv_recv_us','ack_recv_us','rtt_us'])
        
        start_time = now_ms()
        
        for i in range(count):
            seq = i + 1
            
            # create payload
            payload = f"TYPE={mtype};SEQ={seq};TS={now_us()}".encode()
            
            # T1: producer timestamp
            t1 = now_us()
            
            # T2: enqueue timestamp (simulated - in real system this is queue insertion time)
            enqueue = now_us()
            
            # T3: tx start
            tx_start = now_us()
            try:
                sent = s.sendto(payload, (target, port))
            except Exception as e:
                errors += 1
                print(f'\n[CLIENT] Send error seq={seq}: {e}')
                w.writerow([seq, t1, enqueue, tx_start, '', '', '', ''])
                continue
            
            # T4: tx end
            tx_end = now_us()
            
            # wait for ack with timeout
            s.settimeout(timeout_ms/1000.0)
            srv_recv = ''
            ack_recv = ''
            rtt = ''
            
            try:
                data, addr = s.recvfrom(65535)
                # T6: ack receive timestamp
                ack_recv = now_us()
                
                # parse server recv ts (T5) if present
                if b'|SRV|' in data:
                    parts = data.split(b'|SRV|')
                    if len(parts) >= 2:
                        try:
                            srv_recv = int(parts[-1].decode())
                        except Exception:
                            srv_recv = ''
                
                # compute RTT
                rtt = ack_recv - tx_start
                success += 1
                
            except socket.timeout:
                timeouts += 1
                ack_recv = ''
                rtt = ''
            except (ConnectionResetError, OSError) as e:
                errors += 1
                ack_recv = ''
                rtt = ''
            
            # write row
            w.writerow([seq, t1, enqueue, tx_start, tx_end, srv_recv, ack_recv, rtt])
            
            # progress display
            if seq % 10 == 0 or seq == count:
                elapsed = now_ms() - start_time
                print(f'[CLIENT] Sent {seq}/{count} | Success: {success} | Timeout: {timeouts} | Error: {errors} | Elapsed: {elapsed}ms', end='\r')
            
            # burst injection: if burst and i in range, send back-to-back
            if burst and (20 <= i < 30):
                # tight loop, no sleep (burst mode)
                continue
            
            time.sleep(interval_ms/1000.0)
    
    print()
    print(f'[CLIENT] Done. Wrote {out_csv}')
    print(f'[CLIENT] Success: {success}/{count} ({success*100.0/count:.1f}%) | Timeout: {timeouts} | Errors: {errors}')


if __name__ == '__main__':
    p = argparse.ArgumentParser(
        description='Real-time communication instrumentation tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Start clean echo server
  python scripts/comm_instrument.py --server --port 5005
  
  # Start bad-case server (50ms delay, 20% drop)
  python scripts/comm_instrument.py --server --port 5005 --badcase --delay-ms 50 --drop-prob 0.2
  
  # Send baseline test (30 messages, 5ms interval)
  python scripts/comm_instrument.py --target 127.0.0.1 --port 5005 --type baseline --count 30 --interval-ms 5
  
  # Send control test with burst
  python scripts/comm_instrument.py --target 127.0.0.1 --port 5005 --type control --count 50 --interval-ms 10 --burst --timeout-ms 100
        '''
    )
    
    # Server options
    p.add_argument('--server', action='store_true', help='Run as UDP echo server')
    p.add_argument('--port', type=int, default=5005, help='Port number (default: 5005)')
    p.add_argument('--badcase', action='store_true', help='Server bad-case mode: enable delay and drops')
    p.add_argument('--delay-ms', type=int, default=0, help='Server processing delay in ms (requires --badcase)')
    p.add_argument('--drop-prob', type=float, default=0.0, help='Server drop probability 0.0-1.0 (requires --badcase)')
    
    # Client options
    p.add_argument('--target', default='127.0.0.1', help='Target IP address (default: 127.0.0.1)')
    p.add_argument('--type', default='telemetry', help='Message type label (default: telemetry)')
    p.add_argument('--count', type=int, default=30, help='Number of messages to send (default: 30)')
    p.add_argument('--interval-ms', type=int, default=10, help='Interval between messages in ms (default: 10)')
    p.add_argument('--timeout-ms', type=int, default=100, help='Socket timeout in ms (default: 100)')
    p.add_argument('--burst', action='store_true', help='Enable burst mode (sends burst at msg 20-30)')
    
    args = p.parse_args()
    
    if args.server:
        run_server(args.port, badcase=args.badcase, delay_ms=args.delay_ms, drop_prob=args.drop_prob)
    else:
        send_messages(args.target, args.port, args.type, args.count, args.interval_ms, 
                     burst=args.burst, timeout_ms=args.timeout_ms)
