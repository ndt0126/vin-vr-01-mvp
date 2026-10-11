# Phiên GPU 11/10/2026 — Compose trên GPU, Kubernetes có GPU, soak 8 giờ

Trạng thái: **phần 1 (Compose) và phần 2 (Kubernetes) đã xong; phần 3 (soak 8 giờ) ĐANG CHẠY**, bắt đầu 09:48:08 UTC, dự kiến xong khoảng 17:48 UTC. Kết quả soak sẽ được ghi vào mục 4 khi có; trước lúc đó không có kết luận nào về soak.

## 1. Máy và phạm vi

| | |
|---|---|
| GPU | NVIDIA RTX A6000, 49.140 MiB, driver 580.126.16 |
| Máy | VPS thuê, 6 vCPU, 32 GB RAM, Ubuntu 24.04.4, kernel 6.17 |
| Docker / toolkit | Docker 29.2.1, NVIDIA Container Toolkit 1.18.2 |
| Triton | 2.60.0 (image 25.08-py3, pin digest), model chạy `KIND_GPU` |
| Mã nguồn | bắt đầu ở `b1454ce`; hai bản sửa trong phiên: `3e938bb`, `31f2d9a` (xem mục 5) |

Giới hạn cần đọc trước:

- Đây là **GPU NVIDIA trên cloud**, cài có Internet. Không phải máy AMD của nhà máy, không phải air gap.
- Model nặng là mạng tích chập **tự sinh** (trọng số tất định, không phải model QC). Số đo cho biết hệ thống chịu tải ra sao, không phải hiệu năng của model thật.
- Mọi con số chỉ có nghĩa trên máy này.

## 2. Phần 1 — Compose trên GPU: 16/16

File: `compose/session-gpu-report.json`, `compose/session-gpu.log`.

| Bước | Kết quả |
|---|---|
| P1 smoke | 18/18 |
| G1 model nặng chạy trên GPU thật | `tritonserver` có trong `nvidia-smi --query-compute-apps` (932 MiB), config `KIND_GPU`, Triton báo bộ nhớ GPU > 0; một lần suy luận 89 ms |
| G2 chọn mức nặng | mức `gpu` (512², 48 lớp): 88 ms; mức `gpu-xl` (1024², 64 lớp): **590 ms** → dùng `gpu-xl`, VRAM 4.622 MiB |
| P18 model ảnh thật | golden đạt (mong đợi 0,479788, thực tế 0,479756); điểm đổi theo ảnh tối/vừa/sáng |
| G3 chuyển qua lại hai model nặng khi có tải, 5 phút | 256 request, 9/9 lần chuyển, 0 sai model, 0 trùng; p50 609 ms, p95 689 ms, khoảng hở dài nhất 1,27 s |
| G4 hết VRAM lúc nạp model | chiếm 47.673 MiB (còn 199 MiB) → kích hoạt bị từ chối 422, recipe cũ vẫn phục vụ, không cần restart; trả VRAM xong kích hoạt lại được |
| G5 hết VRAM khi nạp model thứ hai cạnh model đang chạy | bị từ chối 422, model đang chạy không bị ảnh hưởng |
| P13a–f observability | Prometheus thấy API và Triton; cảnh báo model-unavailable bật sau 24 s, tắt sau 6 s; dashboard 18 panel |
| P14 tự rollback | 3 lỗi liên tiếp sau khi chuyển → tự quay về recipe cũ |
| P7 kill -9 API (1 đang chạy + 2 đang chờ) | cả 3 thành INDETERMINATE, sẵn sàng lại sau 1 s, gửi lại bằng mã mới thì COMPLETED |
| P8 kill -9 Triton khi có tải | 501 request, 0 sai, 0 trùng, 6/6 lần chuyển |

Ghi chú về G4/G5: log Triton có lỗi cấp phát bộ nhớ của ONNX Runtime (`BFCArena::AllocateRawInternal`) đúng lúc đó, nên lý do từ chối là hết VRAM thật. Model nạp được nhưng **golden check** thất bại vì không cấp được bộ nhớ, và API trả mã `ACTIVATION_GOLDEN_FAILED`. Chưa tái hiện được OOM **giữa lúc đang suy luận** với model đã warm-up: bộ nhớ đã được cấp từ lần golden.

### Quét tải model nặng (`compose/load-sweep-gpu-heavy-report.md`)

| Tốc độ gửi (req/s) | Hoàn tất (req/s) | p95 (ms) | Bị từ chối |
|---|---|---|---|
| 0,5 | 0,52 | 605 | — |
| 1,0 | 1,01 | 609 | — |
| 1,5 | 1,50 | 616 | — |
| 1,75 | 1,66 | 2.617 | — |
| 2,0 | 1,66 | 4.759 | 7 × 429 |
| 4,0 | 1,65 | 4.822 | 87 × 429 |

Trần là khoảng 1,66 req/s (một instance, mỗi lần 0,59 s). Quá trần, hàng đợi dài ra rồi hệ thống trả 429; không có request nào bị mất hay sai.

## 3. Phần 2 — Kubernetes có GPU: 10/10

File: `k8s/k8s-report.txt`, `k8s/gpu-in-k8s.txt`, `k8s/kubeadm-gpu-install.log`.

kubeadm v1.34.12 single-node, containerd 2.2.1, NVIDIA device plugin; overlay `lab-gpu`.

- Node khai báo `nvidia.com/gpu: 1`; container Triton xin `limits nvidia.com/gpu: 1`; trong pod `nvidia-smi` thấy RTX A6000; cả hai model `KIND_GPU`; `tritonserver` có trong compute-apps của máy.
- K1–K10 đạt: deploy từ namespace sạch (13 s), smoke 18/18 qua NodePort, NetworkPolicy (Triton 8000 và metrics 9090 đóng với pod khác), xóa pod tự phục hồi (11 s, giữ recipe đang chọn), cập nhật (12 s) và rollback (14 s) phiên bản, đổi và rollback model.

Chưa làm trên GPU: reboot node, gói offline (hai việc này đã làm ở phiên CPU `vps-w4-2026-10-11T0754Z`).

## 4. Phần 3 — Soak 8 giờ

Cấu hình (`compose/soak-started.json`): 28.800 s, 0,678 req/s (khoảng 40% thời gian GPU bận), chuyển qua lại `recipe-heavy` ↔ `recipe-heavy-b` mỗi 300 s, không restart định kỳ, lấy mẫu mỗi 30 s (VRAM, nhiệt độ, RAM, số lần container restart, metrics).

Kết quả: **chưa có** (đang chạy).

## 5. Lượt đầu hỏng và hai lỗi đã sửa

Lượt đầu của phần 1 chỉ đạt 10/16 (`compose/attempt1/`). Nguyên nhân và cách sửa:

1. **API giữ giới hạn cũ sau khi đổi kho package.** API đọc kho package và `site-config` một lần lúc khởi động. Bước G2 đổi model nặng từ 512² sang 1024² mà API không được khởi động lại, nên nó từ chối model mới (`E_LIMIT: input larger than max_decoded_pixels`). Sửa ở `3e938bb`: `make start` tự khởi động lại API khi nội dung kho package đổi. Bài G4 của lượt đầu vì thế không hợp lệ (bị từ chối vì giới hạn, không phải vì hết VRAM).
2. **Bài kill API dùng model chạy quá nhanh trên GPU.** `model-slow` xong trước khi kịp kill. Sửa: trên GPU bài này dùng model nặng.
3. **Công cụ quét tải đặt trùng mã request** giữa bước 1,0 và 1,5 req/s (lỗi của công cụ test, không phải của API; API trả 409 đúng). Sửa ở `31f2d9a`; kết quả ở mục 2 là lượt chạy lại.

Soak cũng đã tự khởi động một lần ngay sau lượt đầu (40 giây, tải 0,267 req/s vì chưa có số đo G2); mình dừng nó, chạy lại các bài ngắn rồi mới bắt đầu soak chính thức. Dữ liệu 40 giây đó nằm trong `compose/attempt1/`.

Một lỗi do thao tác tay của người chạy (không phải lỗi hệ thống): đổi mức model nặng trong khi recipe dùng nó đang active → API báo `ACTIVE_RECIPE_UNVERIFIED` và không nhận request (đúng thiết kế: không chạy model đã bị đổi dưới chân). Khôi phục bằng cách đưa đúng model cũ về lại.
