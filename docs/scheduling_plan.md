Scheduling plan for RTOS migration and jitter control

1) Mapping tasks → threads/processes
- SensorTask (Soil/DHT): thread `SensorTask`
  - Period: 2000 ms
  - Work: read sensors, update state snapshot
  - Priority: HIGH (time-critical sampling)
- DisplayTask: thread `DisplayTask`
  - Period: 5000 ms
  - Work: update LCD / UI
  - Priority: LOW-MEDIUM (soft real-time)
- NetworkTask: thread `NetworkTask`
  - Period: 10000 ms (can be event-driven)
  - Work: upload telemetry, handle HTTP
  - Priority: MEDIUM
- SwitchTask (control/pump): thread `SwitchTask`
  - Period: 60000 ms or event-based
  - Work: run control algorithm, start/stop irrigation
  - Priority: HIGHEST (control decision)
- EDFSchedulerTask / Watchdog / ErrorCheck: maintain as system tasks
  - Priorities according to criticality (Watchdog high)

2) Priority assignment (concrete values for FreeRTOS on ESP32)
- FreeRTOS priorities: 0..configMAX_PRIORITIES-1 (e.g., 0..24)
- Example mapping (configMAX_PRIORITIES >= 6 assumed):
  - `SwitchTask` = 5  (highest)
  - `SensorTask` = 4
  - `NetworkTask` = 3
  - `DisplayTask` = 2
  - `Background/Logging` = 1
  - Idle = 0

3) Timer/clock source
- Use FreeRTOS tick for coarse scheduling and a high-resolution hardware timer (millis/esp_timer_get_time) for jitter measurement and short timers.
- For ESP32, use `esp_timer_get_time()` (microsecond resolution) when measuring latency/jitter.

4) Policy (OS-level)
- On POSIX/linux: use POSIX RT policies for equivalent design:
  - SCHED_FIFO for predictable, low-latency control tasks (no timeslicing)
  - SCHED_RR for periodic interactive tasks that require timeslicing
- Trade-offs:
  - SCHED_FIFO: low latency, but starvation risk (lower-priority tasks starve if higher-priority jobs never block).
  - SCHED_RR: fairer among equal-priority tasks via timeslice but still priority-based.
  - EDF: optimal for deadline misses when tasks have dynamic deadlines but needs admission control and worst-case execution time bounds.

5) Synchronization & shared resources
- Use FreeRTOS Mutexes (not binary semaphores) to protect shared state (e.g., `stateMutex = xSemaphoreCreateMutex()`), because FreeRTOS mutexes implement priority inheritance to mitigate priority inversion.
- For POSIX: use `pthread_mutexattr_setprotocol(&attr, PTHREAD_PRIO_INHERIT)` when creating mutexes.
- Avoid long-held locks. Keep critical sections minimal (read sensors into local variables, then lock briefly to copy into shared state).
- If a low-priority task holds a mutex needed by a high-priority task, priority inversion occurs; mitigate with:
  - Priority inheritance (mutex-based)
  - Short critical sections
  - Avoid blocking calls while holding mutex

6) Jitter control strategies
- Use a high-resolution timer and avoid doing network or I/O inside the time-critical path.
- Use deferred work: network uploads from a medium-priority task, not the sensor task.
- Limit stack/heap contention and avoid malloc/free in hot paths.

7) Measurement plan (what to collect)
- For the primary real-time tasks (SensorTask and SwitchTask): measure the response time per activation (activation → start of work, or arrival to start), and record sample intervals to compute jitter.
- Metrics: p50/p95/p99 and max latency; deadline miss count.
- Tools: on-device measurement using `esp_timer_get_time()` and log to serial, or host-side simulation using provided `scripts/measure_jitter.py`.

8) Deliverables
- `docs/scheduling_plan.md` (this file)
- `scripts/measure_jitter.py` to run baseline and post-change measurements
- Patch to `src/main.cpp` to explicitly set priorities and ensure mutex usage (if requested)

References:
- FreeRTOS: mutexes provide priority inheritance.
- POSIX: SCHED_FIFO, SCHED_RR, and PTHREAD_PRIO_INHERIT.
