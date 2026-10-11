# VR-01 MVP — Observability (W4-01, W4-02)

File này được **sinh tự động** bằng `tools/gen_observability_docs.py` từ `backend/metrics.py` và `deploy/observability/alerts.yml`. Không sửa tay.

## 1. Tổng quan

| Thành phần | Ở đâu | Ghi chú |
|---|---|---|
| Metrics của API | `http://api:9090/metrics` (cổng riêng, HTTP, không token) | Chỉ mở trong mạng nội bộ của Compose, không publish ra host. Không chứa dữ liệu của từng sản phẩm |
| Metrics của Triton | `http://triton:8002/metrics` | Request theo model, CPU/RAM; GPU/VRAM khi máy có GPU |
| Prometheus | `make obs-start`, `http://127.0.0.1:9091` | Scrape 5 giây, giữ 7 ngày hoặc 2 GB |
| Grafana | `http://127.0.0.1:3000` (chỉ xem, không đăng nhập) | Dashboard `VR-01 MVP — tổng quan vận hành`, sinh bằng `tools/gen_dashboard.py` |
| Log có cấu trúc | `run/data/trace.jsonl` (JSON Lines) | Xem mục 5 |

Metric được cập nhật từ chính các sự kiện ghi vào trace log, nên số đếm và log không lệch nhau.

## 2. Health model và probe

| Probe | Endpoint | Trả 200 khi | Dùng cho |
|---|---|---|---|
| Liveness | `GET /healthz` (cả hai cổng, không token) | Tiến trình còn sống và trả lời HTTP | Kubernetes `livenessProbe`: restart khi treo |
| Readiness | `GET /readyz` (cả hai cổng, không token) | Recipe active đã được xác minh digest **và** model của recipe đó đang được nạp trên inference server **và** inference server sống **và** ghi được ledger, ổ còn trống | Kubernetes `readinessProbe`; Compose healthcheck |
| Startup | `GET /readyz` với `failureThreshold` lớn | Như readiness | Kubernetes `startupProbe`: cho phép nạp model lâu lúc khởi động |

Readiness phản ánh **đúng revision mong muốn**: lúc khởi động và mỗi lần kiểm, API đối chiếu digest của recipe active đã lưu bền và hỏi inference server xem đúng model đó có sẵn sàng không. Model active không còn được nạp (ví dụ Triton khởi động lại) thì `readyz` trả 503 với lý do `WARMUP_FAILED`, API tự nạp lại **đúng** model đó và không tự đổi sang recipe khác. Recipe/model đang active nhìn được qua metric `vr01_active_recipe_info` (nhãn gồm 12 ký tự đầu của digest).

Các lý do `readyz` có thể trả: `BACKEND_UNAVAILABLE`, `STORAGE_UNAVAILABLE`, `ACTIVE_RECIPE_UNVERIFIED`, `WARMUP_FAILED`, `SHUTTING_DOWN`. Mỗi lý do là một series của `vr01_not_ready_reason`.

## 3. Danh mục metric của API

Quy tắc nhãn: chỉ dùng nhãn có số giá trị hữu hạn và biết trước (`state`, `reason`, `decision`, `code`, `operation`, `plane`, `status`, `model`, `action`, `outcome`). **Không bao giờ** dùng `request_id`, `product_id`, `trace_id` hay tên người dùng làm nhãn; muốn tra một request thì dùng log (mục 5).

| Metric | Kiểu | Nhãn | Ý nghĩa |
|---|---|---|---|
| `vr01_build_info` | gauge | `api_version` | Luon bang 1; nhan cho biet phien ban hop dong API dang chay. |
| `vr01_process_start_time_seconds` | gauge | — | Thoi diem tien trinh API khoi dong (Unix time). Doi gia tri = da restart. |
| `vr01_process_resident_memory_bytes` | gauge | — | RAM (RSS) cua tien trinh API. |
| `vr01_process_cpu_seconds_total` | counter | — | Tong thoi gian CPU cua tien trinh API. |
| `vr01_ready` | gauge | — | 1 neu readyz tra 200 (nhan request moi), 0 neu khong. |
| `vr01_not_ready_reason` | gauge | `reason` | 1 cho moi ly do dang lam he thong chua san sang. |
| `vr01_active_recipe_info` | gauge | `recipe`, `recipe_version`, `model`, `model_version`, `recipe_sha256`, `model_sha256` | Luon bang 1; nhan cho biet recipe/model dang active va 12 ky tu dau digest. |
| `vr01_queue_depth` | gauge | — | So request da nhan nhung chua ket thuc (dang cho + dang chay). |
| `vr01_queue_capacity` | gauge | — | Gioi han hang doi admission. |
| `vr01_inflight_requests` | gauge | `model` | So request chua ket thuc theo model da pin. |
| `vr01_storage_free_bytes` | gauge | — | Dung luong trong cua o chua du lieu. |
| `vr01_http_requests_total` | counter | `plane`, `operation`, `status` | So HTTP request theo plane, operation va ma tra ve. |
| `vr01_inspections_admitted_total` | counter | `model` | So lan kiem da duoc nhan (ghi ben + pin model). |
| `vr01_inspections_rejected_total` | counter | `code` | So lan gui bi tu choi TRUOC admission, theo ma loi. |
| `vr01_inspections_replayed_total` | counter | — | So lan gui lai cung request_id (tra record cu, khong chay lai). |
| `vr01_inspections_terminal_total` | counter | `state`, `reason` | So lan kiem da ket thuc theo trang thai va ly do. |
| `vr01_inspection_decisions_total` | counter | `decision` | So ket luan chat luong theo OK/NG/REVIEW. |
| `vr01_inspections_cancelled_total` | counter | `was_started` | So lan huy, theo viec da bat dau suy luan hay chua. |
| `vr01_late_results_discarded_total` | counter | `cause` | Ket qua ve muon bi bo (sau TIMEOUT hoac sau khi huy). |
| `vr01_inference_seconds` | histogram | `model` | Thoi gian suy luan tren inference server, theo model. |
| `vr01_queue_wait_seconds` | histogram | — | Thoi gian cho trong hang doi truoc khi suy luan. |
| `vr01_inspection_total_seconds` | histogram | — | Thoi gian tu luc nhan toi luc ket thuc (COMPLETED). |
| `vr01_model_load_total` | counter | `model`, `result` | So lan nap model, theo ket qua. |
| `vr01_model_unload_total` | counter | `model` | So lan go model. |
| `vr01_model_restored_total` | counter | `model` | So lan tu nap lai model active (inference server mat model). |
| `vr01_activations_total` | counter | `action`, `outcome` | So lan chuyen recipe/rollback theo hanh dong va ket qua. |
| `vr01_auto_rollback_total` | counter | `result` | So lan tu rollback sau cutover, theo ket qua. |
| `vr01_auth_denied_total` | counter | `outcome` | So request bi tu choi xac thuc/phan quyen. |
| `vr01_storage_errors_total` | counter | — | So lan ghi ledger that bai. |
| `vr01_stale_writes_ignored_total` | counter | — | So lan ghi de trang thai ket thuc bi chan (compare-and-set). |

Histogram dùng các mốc (giây): 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30.

## 4. Luật cảnh báo

Kiểm offline bằng `make alerts-test` (promtool, `deploy/observability/alerts.test.yml`): mỗi cảnh báo chính được chứng minh **bật** khi có sự cố và **tắt** khi hết.

| Cảnh báo | Mức | Điều kiện | Giữ trong | Ý nghĩa | Cần làm |
|---|---|---|---|---|---|
| `VR01ApiDown` | critical | `up{job="vr01-api"} == 0` | 15s | Khong scrape duoc Inspection API | Kiem tra container api (make logs). San pham trong luc nay CHUA duoc kiem. |
| `VR01ModelUnavailable` | critical | `vr01_ready == 0` | 15s | He thong chua san sang: khong nhan anh moi | Xem vr01_not_ready_reason. WARMUP_FAILED/BACKEND_UNAVAILABLE: kiem tra Triton; he thong tu nap lai model active khi Triton len. |
| `VR01RestartLoop` | critical | `changes(vr01_process_start_time_seconds[10m]) >= 3` | 0s | API khoi dong lai >= 3 lan trong 10 phut | Xem log api truoc moi lan restart; request do dang se la INDETERMINATE. |
| `VR01TechnicalFailureRatioHigh` | warning | `sum(rate(vr01_inspections_terminal_total{state=~"FAILED\|TIMEOUT\|INDETERMINATE"}[2m])) / clamp_min(sum(rate(vr01_inspections_terminal_total[2m])), 0.001) > 0.05 and sum(rate(vr01_inspections_terminal_total[2m])) > 0.05` | 30s | Hon 5% lan kiem ket thuc bang loi ky thuat (2 phut gan nhat) | Cac san pham do CHUA co ket luan. Xem Lich su > Loi ky thuat; kiem tra Triton/GPU. |
| `VR01LatencySLOBreach` | warning | `histogram_quantile(0.95, sum by (le) (rate(vr01_inspection_total_seconds_bucket[2m]))) > 5` | 1m | p95 thoi gian kiem > 5 s (2 phut gan nhat) | Xem vr01_queue_depth va vr01_inference_seconds theo model. |
| `VR01QueueSaturated` | warning | `vr01_queue_depth >= vr01_queue_capacity` | 30s | Hang doi day: request moi bi 429 | Giam toc do gui hoac kiem tra thoi gian suy luan. |
| `VR01AutoRollback` | warning | `increase(vr01_auto_rollback_total[10m]) > 0` | 0s | He thong da tu rollback sau khi chuyen recipe | Recipe moi loi lien tiep ngay sau cutover. Kiem lai cac san pham FAILED; khong kich hoat lai recipe do truoc khi tim ra nguyen nhan. |
| `VR01MemoryPressure` | warning | `vr01_process_resident_memory_bytes > 1.5e9` | 2m | RAM tien trinh API > 1,5 GB | Theo doi xu huong; neu tang deu la dau hieu ro ri bo nho. |
| `VR01StorageLow` | warning | `vr01_storage_free_bytes < 5e9` | 1m | O du lieu con duoi 5 GB | Don theo retention; duoi 64 MiB he thong tu ngung nhan request (503). |
| `VR01StorageErrors` | critical | `increase(vr01_storage_errors_total[5m]) > 0` | 0s | Ghi ledger that bai | He thong ngung nhan request moi. Kiem tra o dia. |

## 5. Log có cấu trúc và truy vết

`run/data/trace.jsonl` là JSON Lines, mỗi dòng một sự kiện:

| Trường | Có ở | Ý nghĩa |
|---|---|---|
| `at` | mọi dòng | Thời điểm, ISO-8601 UTC, mili giây |
| `event` | mọi dòng | Tên sự kiện, ví dụ `request.admitted`, `inference.started`, `inference.finished`, `request.terminal`, `request.rejected`, `request.cancelled`, `activation.committed`, `lifecycle.loaded`, `lifecycle.unloaded`, `http.access`, `audit` |
| `trace_id` | sự kiện gắn với một request HTTP | Nối các dòng của cùng một request; cũng được gửi sang inference server |
| `request_id`, `product_id` | sự kiện của một lần kiểm | Định danh nghiệp vụ |
| `model`, `recipe` | admitted, inference, lifecycle | Tên, version và digest đã pin |
| `state`, `decision`, `reason`, `score` | `request.terminal` | Kết quả cuối |
| `queue_ms`, `inference_ms`, `total_ms`, `duration_ms` | sự kiện tương ứng | Thời gian từng pha |
| `code`, `error` | sự kiện lỗi | Mã lỗi hoặc mô tả lỗi của backend |

Từ một `request_id`, lấy toàn bộ đường đi (ledger + log + audit + các lần kiểm khác của cùng sản phẩm):

```bash
make trace ID=<request_id>
```

Không ghi vào log: token, private key, nội dung ảnh (chỉ có SHA-256). Bộ test quét token trong mọi file dữ liệu sau mỗi test. Log không chứa thông tin cá nhân; `submitted_by` là định danh thiết bị/tài khoản kỹ thuật.

**Retention của log:** `trace.jsonl` xoay vòng khi đạt 64 MiB, giữ 5 file cũ (trần khoảng 384 MiB), file cũ nhất bị xóa. Giá trị là đề xuất, chỉnh bằng giới hạn `trace_max_bytes` và `trace_keep_files`. `make backup` sao lưu cả các file đã xoay vòng. Đề xuất retention chung (14 ngày hoặc 10 GiB) ở W2-02 vẫn chờ Operations chốt.

## 6. Giới hạn

- Ngưỡng cảnh báo là đề xuất cho lab, chưa được Operations duyệt.
- Chưa có Alertmanager: cảnh báo hiện trên Prometheus và Grafana, chưa gửi đi đâu.
- Metric CPU/RAM là của tiến trình API và của Triton tự báo; chưa có metric mức container/node (cAdvisor, node exporter).
- Grafana cho xem không cần đăng nhập và chỉ mở trên loopback; chưa phù hợp để mở ra mạng nhà máy.
