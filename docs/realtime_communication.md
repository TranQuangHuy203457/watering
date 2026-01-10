Real-time communication design for RTOS_watering

1) Message flow design
- Message types:
  - Telemetry (periodic): small JSON ~200-400 bytes, period 10s, soft deadline 2s
  - Control (event): small command ~64 bytes, immediate send, hard deadline 200ms
  - Heartbeat: 16 bytes, period 5s, deadline 1s
- Producer/consumer:
  - Producers: SensorTask -> Telemetry; SwitchTask -> Control events; NetworkTask -> sender
  - Consumer: NetworkTxTask (single point to perform I/O)
- Queues:
  - Use separate queues per class: control_queue (high-priority), telemetry_queue (medium), heartbeat_queue (low)
  - Queue sizes: control=16, telemetry=32, heartbeat=8

2) Message parameters
- Telemetry: size 200-400B, period 10s, end-to-end deadline 2s (from sensor sampling -> remote ack)
- Control: size 64B, event-driven, E2E deadline 200ms
- Heartbeat: 16B, period 5s, soft deadline 1s

3) Mechanisms to reduce latency/jitter
- Queue discipline: priority queues (control > telemetry > heartbeat)
- Immediate send for Control: zero batching, flush network Tx buffer immediately
- Telemetry: batch multiple telemetry messages if bandwidth constrained, but cap batch delay to 200ms
- Retry policy: exponential backoff with limited retries (3) for telemetry; control messages: retry fast (50ms) up to 5 times then escalate/failover
- Priority traffic: mark control packets with DSCP Expedited Forwarding (EF) when using IP network

4) Synchronization points and timestamping (for E2E measurement)
- Timestamp points to log for each message:
  - T1: producer timestamp (when message created, on device)
  - T2: enqueue timestamp (when placed into tx queue)
  - T3: tx-start timestamp (when first byte written to socket/interface)
  - T4: tx-end timestamp (when all bytes handed to NIC)
  - T5: remote receive timestamp (if remote can timestamp on receive)
  - T6: remote processing complete / ack timestamp
- For on-device-only E2E, measure T1->T4 and T1->ack-received (round-trip) as end-to-end.

5) Components contributing to latency (analysis)
- Queueing delay: time waiting in priority queue (control minimized)
- Processing delay: serialization, encryption, CPU time
- I/O wait: socket send buffer, driver/NIC, network propagation
- Remote processing: server queueing, DB insert, application processing
- Retransmissions: increases end-to-end time and jitter

6) Logging & evidence collection
- Add per-message logs with timestamps T1..T4, send to serial or local file
- Provide scripts to parse logs and compute per-message E2E latency, jitter (p50/p95/p99), and loss

7) Experiments required
- Baseline: normal load, measure latency/jitter for control and telemetry (collect p50/p95/p99)
- Bad-case: inject bursts (many telemetry + sporadic heavy control), or simulate network loss/latency (tc/netem on Linux) and measure resilience; show E2E results and how system behaves (drops, delays, retries)

8) Deliverables
- `docs/realtime_communication.md` (this file)
- `scripts/comm_instrument.py` — instrumented sender that logs T1..T4 and computes stats
- `scripts/comm_badcase.sh` — script to run netem rules (if Linux) to simulate loss/latency
- Experimental logs and summary (CSV/plots)
