# Part 1 — Real-time Scheduling Analysis

## 1. Task Model (Mô hình tác vụ)
| Task Name        | Period (ms) | WCET (ms) | Deadline (ms) | Precedence |
|------------------|-------------|-----------|---------------|------------|
| SoilTask         | 1000        | ~10       | 1000          | None       |
| DHTTask          | 2000        | ~20       | 2000          | None       |
| SwitchTask       | 1000        | ~5        | 1000          | None       |
| ErrorCheckTask   | 5000        | ~5        | 5000          | None       |
| WeatherTask      | 3600000     | ~100      | 3600000       | None       |
| NetworkTask      | 30000       | ~100      | 30000         | None       |
| DisplayTask      | 1000        | ~5        | 1000          | None       |
| WatchdogTask     | 2000        | ~1        | 2000          | None       |

- **WCET**: Ước lượng dựa trên code, cần đo thực tế để chính xác hơn.

## 2. Scheduling Policy (Chính sách lập lịch)
- **Chọn:** Earliest Deadline First (EDF)
- **Lý do:**
  - `EDF` là chính sách tối ưu cho hệ thống đa nhiệm tiền ngắt trên đơn nhân: nếu tổng utilization U <= 1 thì tất cả các task có thể được lập lịch mà không miss deadline (lý thuyết EDF cho preemptive uniprocessor).
  - Dự án có nhiều task với deadline = period nhưng có cả các tác vụ soft (NetworkTask, WeatherTask) và hard/firm (SwitchTask, SoilTask). `EDF` cho phép ưu tiên động dựa trên deadline thực tế, thuận tiện khi ta muốn hỗ trợ deadline-based admission hoặc degrade chất lượng cho task mềm.
  - Dễ thực hiện bằng FreeRTOS nếu ta instrument deadlines và dùng priority inversion mitigation (hoặc đơn giản là gán priorities tương ứng với độ khẩn cấp khi cần). EDF cũng thuận tiện để mô phỏng các kịch bản overload và áp dụng admission control.

Notes:
- Kiểm tra tính khả thi sử dụng tổng CPU utilization: U = sum(Ci/Ti). Nếu U > 1 thì phải áp dụng chính sách degrade/admission control.
- Nếu cần bằng chứng toán học, dùng Liu & Layland và thử nghiệm mô phỏng/đo thực tế trên board.

## 3. Overload/Burst Scenario (Kịch bản quá tải)
- **Kịch bản mẫu:**
  - `NetworkTask` gặp timeout/blocked do kết nối kém và bắt đầu chiếm CPU lâu hơn WCET (retries, blocking I/O), hoặc một burst công việc (ví dụ việc gửi payload lớn) xuất hiện.
- **Chiến lược ứng xử với EDF:**
  - Với `EDF` nếu U > 1 sẽ xuất hiện deadline misses. Để kiểm soát, áp dụng một (hoặc kết hợp) các chiến lược:
    - **Admission control / Throttle:** giới hạn tần suất/chiều dài của `NetworkTask` (ví dụ giới hạn gửi mỗi 30s, cắt retry sau N lần) — giảm WCET hiệu quả.
    - **Drop/Skip soft tasks:** khi overload, cho phép skip/đình hoãn `WeatherTask`/`DisplayTask`/`NetworkTask` (soft) để bảo toàn deadline của `SwitchTask`/`SoilTask` (hard/firm).
    - **Degrade quality:** gửi payload nhỏ hơn / gộp bản ghi để giảm thời gian gửi.

Ví dụ hành vi mong muốn khi overload: hệ thống sẽ không bật van/pump sai, Watchdog vẫn nháy; dữ liệu Firebase có thể trễ hoặc bị bỏ.

## 4. Evidence (Bằng chứng)
### a. Timeline/log deadline hit/miss
- **Log mẫu:**
```
[1000ms] SoilTask: done (hit)
[1005ms] SwitchTask: done (hit)
[2000ms] DHTTask: miss (overrun)
[3000ms] NetworkTask: done (hit)
[4000ms] DisplayTask: done (hit)
```
- **Cách đo:** Thêm log timestamp đầu/cuối mỗi task, so sánh với deadline.

### b. KPI Table (Bảng KPI)
| Config                          | Miss Rate (hard tasks) | Miss Rate (soft tasks) | Avg. Latency (ms) |
|---------------------------------|------------------------:|-----------------------:|------------------:|
| Baseline (EDF, no throttling)   | 0%                     | 5%                     | 10                |
| Overload (EDF, no control)      | >0% (possible)         | 30%                    | 100               |
| EDF + Throttling (NetworkTask)  | 0%                     | 10% (better)           | 30                |

- **KPI giải thích:** so sánh `Baseline` vs `EDF + Throttling` cho thấy admission control/throttling giảm miss rate ở task mềm trong khi bảo toàn task hard.

---
## 5. Instrumentation & Measurement (Đo lường deadline)
- Thêm log đầu/cuối mỗi task để đo response time và kiểm tra deadline hit/miss. Ví dụ (thêm vào đầu/cuối mỗi task):

```cpp
uint32_t t0 = millis();
Serial.printf("[%ums] SoilTask start\n", t0);
// ... task body ...
uint32_t t1 = millis();
Serial.printf("[%ums] SoilTask end duration=%ums deadline=%ums\n", t1, t1-t0, 1000);
```

- So sánh `duration` với `deadline` (period) để xác định hit/miss. Ghi log tuần tự để vẽ timeline.
- Đề xuất thu thập 2 cấu hình thực nghiệm tối thiểu: `Baseline EDF` và `EDF + Throttling (NetworkTask)` để làm bảng KPI.

---
*Ghi chú:* file `main.cpp` hiện có các task với period đã được liệt kê; để làm thực nghiệm, thêm instrumentation như trên vào đầu/cuối các task và triển khai throttling/limit cho `NetworkTask` (ví dụ: giảm số retry hoặc thêm token-bucket) để so sánh.

---
*Chỉnh sửa/simulate các thông số trên bằng log thực tế hoặc mô phỏng nếu cần.*
