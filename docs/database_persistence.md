# Part 4: Database/Persistent Storage & Real-Time Trade-offs

## 1. Vai trò Database trong hệ thống

### 1.1 Logging
- **Telemetry log**: Ghi lại soil moisture, temperature, humidity mỗi 10s
- **Event log**: Ghi lại irrigation start/stop, mode changes, errors
- **Metric log**: Ghi lại task response times, deadline misses, queue depths

### 1.2 State Store
- **Persistent configuration**: Irrigation schedule, thresholds, WiFi credentials
- **Last known state**: Pump status, last irrigation time, sensor readings
- **Recovery data**: State checkpoints để recovery sau power loss

### 1.3 Command History
- **User commands**: Manual pump on/off, mode changes (timestamp + action)
- **Scheduled commands**: Auto irrigation events với outcomes
- **System events**: Watchdog triggers, task restarts, network reconnects

### 1.4 Truy vấn/Reports
- **Historical data**: Query sensor trends cho web dashboard
- **Diagnostics**: Phân tích deadline misses, error patterns
- **Audit trail**: Compliance tracking cho critical operations

---

## 2. Thiết kế Write/Read Paths

### 2.1 Synchronous Write (Blocking)
```
Task → Format log → SPIFFS write() → Block until complete → Continue
```
**Pros**: Đảm bảo consistency, data không bị mất khi crash ngay sau write  
**Cons**: Block task (SPIFFS write ~10-50ms), có thể miss deadline, tăng jitter

**Use case**: Critical state (e.g., irrigation start command phải log trước khi thực thi)

### 2.2 Asynchronous Write (Buffered)
```
Task → Enqueue to ring buffer → Continue immediately
Background task → Dequeue batch → SPIFFS write() → Sync periodically
```
**Pros**: Task không block (enqueue ~1-10µs), predictable latency, reduce jitter  
**Cons**: Risk mất data nếu crash trước flush, thêm complexity (buffer management)

**Use case**: High-frequency telemetry (soil/temp readings mỗi 10s)

### 2.3 Batching Strategy
- **Time-based**: Flush buffer mỗi 5s hoặc 10s
- **Size-based**: Flush khi buffer đạt 4KB hoặc 80% capacity
- **Priority-based**: Critical logs flush immediately, telemetry batch

**Trade-off**: Lớn batch = ít SPIFFS writes (reduce wear, better throughput) nhưng nhiều risk mất data

### 2.4 Backpressure Handling
Khi buffer đầy (producer nhanh hơn consumer):
1. **Drop oldest** (ring buffer overwrite): Mất data cũ, giữ data mới
2. **Drop newest** (reject enqueue): Giữ data cũ, signal producer slow down
3. **Block producer** (wait for space): Fallback to sync write, nhưng safe

**Recommendation**: Drop oldest for telemetry, block for critical commands

---

## 3. Persistence Technologies (ESP32)

### 3.1 SPIFFS (SPI Flash File System)
- **Latency**: Read ~5-10ms, Write ~10-50ms (depending on file size, fragmentation)
- **Wear leveling**: Built-in, but finite write cycles (~10k-100k)
- **Concurrency**: Single-threaded, mutex needed for multi-task access
- **Use case**: Config files, small logs (<1MB)

### 3.2 LittleFS (Alternative)
- **Advantages**: Better wear leveling, faster mount, power-loss resilient
- **Latency**: Similar to SPIFFS
- **Use case**: Preferred for newer projects

### 3.3 SD Card (SPI)
- **Latency**: Higher variance (10-200ms), depends on card quality
- **Capacity**: Much larger (GB vs MB)
- **Use case**: Long-term data logging, high-volume telemetry

### 3.4 NVS (Non-Volatile Storage)
- **Latency**: Fast (~1-5ms), key-value store
- **Capacity**: Limited (~16KB default partition)
- **Use case**: Config, calibration data, small state

---

## 4. Thí nghiệm: DB Impact trên Deadline

### 4.1 Baseline (No DB Logging)
- Control task: check sensor → decide irrigation → apply output
- **Measurement**: Response time, jitter, deadline miss rate
- **Expected**: Best-case performance (no I/O overhead)

### 4.2 Synchronous DB Logging
- Control task: check → decide → **SPIFFS write (BLOCK)** → apply
- **Measurement**: Response time tăng ~10-50ms, jitter tăng, có thể miss deadline
- **Expected**: Worst-case performance (full I/O penalty)

### 4.3 Asynchronous DB Logging (Buffered)
- Control task: check → decide → **enqueue log (1µs)** → apply
- Background DBTask: dequeue batch → SPIFFS write → flush
- **Measurement**: Response time gần baseline, jitter thấp, deadline OK
- **Expected**: Best of both worlds (persistence + timeliness)

### 4.4 Stress Test: High Contention
- Multiple tasks log simultaneously (Sensor + Control + Network)
- SPIFFS mutex contention → waiting time tăng
- **Mitigation**: Dedicate single DB task (serialize writes), use batching

---

## 5. Consistency vs Timeliness Trade-offs

### 5.1 Spectrum
```
Sync Write          Async Buffered       Async No-Persist
(Slow, Safe)        (Fast, Mostly Safe)  (Fastest, Risky)
```

### 5.2 Decision Matrix
| Data Type          | Method    | Reason                                    |
|--------------------|-----------|-------------------------------------------|
| Irrigation command | Sync      | Critical, must persist before execution   |
| Sensor telemetry   | Async     | High-frequency, loss acceptable           |
| Error events       | Async+Pri | Important but rare, priority flush        |
| User config        | Sync      | Infrequent, must be durable               |
| Watchdog reset     | NVS       | Must survive crash, fast write needed     |

### 5.3 Tuning Parameters
- **Buffer size**: 8KB (trade-off: memory vs batch efficiency)
- **Flush interval**: 5s (trade-off: data loss window vs write frequency)
- **Priority levels**: 2 (critical=immediate, normal=batched)
- **Backpressure**: Drop oldest telemetry, block critical commands

---

## 6. Instrumentation & Tracing

### 6.1 Timestamping Points
```
T1: Task start
T2: Log enqueue (or sync write start)
T3: DB write start (background task)
T4: DB write complete
T5: Task complete (output applied)
```

**DB time**: T4 - T3  
**Non-DB time**: (T2 - T1) + (T5 - T4)  
**Total E2E**: T5 - T1

### 6.2 Metrics to Collect
- **Enqueue latency**: T2 - T1 (should be ~1-10µs)
- **Write latency**: T4 - T3 (SPIFFS write time, ~10-50ms)
- **Task response**: T5 - T1 (end-to-end with DB)
- **Queue depth**: Count of pending logs in buffer
- **Drop count**: Number of logs dropped due to backpressure

### 6.3 Implementation
```cpp
struct LogEntry {
    uint64_t t1_task_start;
    uint64_t t2_enqueue;
    uint64_t t3_write_start;
    uint64_t t4_write_end;
    char data[128];
};
```

---

## 7. Kết quả mong đợi

### 7.1 KPI Comparison

| Metric              | Baseline | Sync Write | Async Write |
|---------------------|----------|------------|-------------|
| Task response (p50) | 50µs     | 15ms       | 80µs        |
| Task response (p99) | 200µs    | 45ms       | 500µs       |
| Jitter (p99-p50)    | 150µs    | 30ms       | 420µs       |
| Deadline miss rate  | 0%       | 15-30%     | 0-2%        |
| DB write time       | N/A      | 10-50ms    | 10-50ms     |
| Throughput (logs/s) | N/A      | 20-100     | 500-1000    |

### 7.2 Interpretation
- **Sync write**: Unacceptable cho real-time tasks (deadline miss >15%)
- **Async write**: Acceptable (miss rate <2%, trade-off: 5s data loss window)
- **Buffer tuning**: Larger buffer = fewer misses but longer loss window
- **Priority**: Critical tasks không nên log hoặc chỉ enqueue, để background flush

---

## 8. Mitigations & Best Practices

### 8.1 Architectural
1. **Dedicate DB task**: Single task with low priority (1-2) handles all writes
2. **Lock-free buffer**: Ring buffer with atomic head/tail pointers
3. **Pre-allocate files**: Avoid SPIFFS fragmentation, pre-create log files

### 8.2 Code Patterns
```cpp
// Fast enqueue (lock-free if possible)
bool log_async(const char* msg) {
    if (buffer_full()) return false;  // or drop oldest
    enqueue(msg);
    return true;
}

// Background flush
void DBTask(void* param) {
    while (1) {
        if (should_flush()) {  // time or size threshold
            batch = dequeue_all();
            SPIFFS_write(batch);  // single write for efficiency
        }
        vTaskDelay(100 / portTICK_PERIOD_MS);  // check every 100ms
    }
}
```

### 8.3 Testing
1. Measure baseline without DB
2. Add sync writes, observe deadline misses
3. Switch to async, verify miss rate drops
4. Stress test with burst logging, check backpressure
5. Power-loss test, verify data within acceptable loss window

---

## 9. Summary

**Key Insight**: DB I/O (10-50ms) là quá chậm cho real-time tasks (deadline ~100-500ms). Async buffering giảm impact từ 15-30% deadline miss xuống <2%, trade-off là 5s data loss window.

**Evidence Required**:
1. ✅ KPI table: baseline vs sync vs async (response time, jitter, miss rate)
2. ✅ Trace: separate DB time (T4-T3) vs non-DB time (T2-T1, T5-T4)
3. ✅ Log: show buffer depth, drop count under load
4. ✅ Experiment: stress test with contention, show mitigation effectiveness
