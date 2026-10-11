# Phiên GPU 11/10/2026 — Compose trên GPU, Kubernetes có GPU, soak 8 giờ

Trạng thái: **đã xong cả bốn phần** (Compose, Kubernetes, soak 8 giờ, các bài sau soak). Máy đã trả lúc 18:29 UTC 11/10 (`TERMINATED.txt`), sau khi 156 file kết quả về laptop và khớp `MANIFEST.sha256`.

## 1. Máy và phạm vi

| | |
|---|---|
| GPU | NVIDIA RTX A6000, 49.140 MiB, driver 580.126.16 |
| Máy | VPS thuê, 6 vCPU, 32 GB RAM, Ubuntu 24.04.4, kernel 6.17 |
| Docker / toolkit | Docker 29.2.1, NVIDIA Container Toolkit 1.18.2 |
| Triton | 2.60.0 (image 25.08-py3, pin digest), model chạy `KIND_GPU` |
| Mã nguồn | bắt đầu ở `b1454ce`; hai bản sửa trong phiên: `3e938bb`, `31f2d9a` (xem mục 5); soak chạy ở `31f2d9a`; các bài sau soak ở `823d87c` |

Giới hạn cần đọc trước:

- Đây là **GPU NVIDIA trên cloud**, cài có Internet. Không phải máy AMD của nhà máy, không phải air gap.
- Model nặng là mạng tích chập **tự sinh** (trọng số tất định, không phải model QC). Số đo cho biết hệ thống chịu tải ra sao, không phải hiệu năng của model thật.
- Mọi con số chỉ có nghĩa trên máy này.
- Gói offline chỉ gồm lớp ứng dụng và chưa ký; Kubernetes, containerd, driver và device plugin đã cài sẵn có Internet. Cắt Internet bằng iptables, không phải air gap vật lý; sau reboot luật iptables mất nên Internet mở lại.

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

Reboot node và gói offline trên node GPU: xem mục 4b.

## 4. Phần 3 — Soak 8 giờ

File: `compose/soak-report.json`, `compose/soak-load-report.json`, `compose/soak-samples.jsonl` (964 mẫu), `compose/soak-journal.jsonl` (từng request), `compose/soak-charts.svg`.

Cấu hình (`compose/soak-started.json`): 28.800 s, 0,678 req/s (GPU bận khoảng 40%), chuyển qua lại `recipe-heavy` ↔ `recipe-heavy-b` mỗi 300 s, **không restart định kỳ**, lấy mẫu mỗi 30 s.

| | Kết quả |
|---|---|
| Thời gian | 8,03 giờ (09:48 → 17:49 UTC) |
| Request | 19.528 gửi, 19.528 hoàn tất; **0 thiếu hoặc sai, 0 trùng, 0 trạng thái kỹ thuật** |
| Chuyển model | **95/95**; khoảng hở dài nhất 1,67 s |
| Độ trễ toàn trình | p50 607 ms, p95 612 ms, lớn nhất 1.246 ms |
| Container | Không restart; tiến trình API không khởi động lại; 0 mẫu "chưa sẵn sàng" |
| Gửi lại phía client | 97 request phải gửi hai lần, đều đúng lúc chuyển model (95 lần 409 "recipe đã đổi", 20 lần 503 "chưa sẵn sàng"); không request nào mất |

Xu hướng tài nguyên (trung bình giờ đầu → giờ cuối):

| Chuỗi | Giờ đầu | Giờ cuối | Thay đổi | Độ dốc sau giờ đầu |
|---|---|---|---|---|
| RAM tiến trình API | 88,7 MiB | 98,2 MiB | +10,6% | −0,02 MiB/giờ |
| RAM container API | 73,5 MiB | 84,4 MiB | +14,7% | +0,17 MiB/giờ |
| RAM container Triton | 1.565,5 MiB | 1.641,6 MiB | +4,9% | **+7,7 MiB/giờ** |
| VRAM | 4.621 MiB | 4.621 MiB | 0% | −0,7 MiB/giờ |
| Nhiệt độ GPU | 59,0 °C | 58,7 °C | — | 0 |

Cách đọc:

- Công cụ `soak_report.py` kết luận **REVIEW**, không phải PASS, vì RAM của API giờ cuối cao hơn giờ đầu quá 10%. Phần tăng đó nằm trọn trong giờ đầu (tiến trình mới khởi động 6 giây trước soak); từ giờ thứ hai trở đi đường này phẳng.
- **RAM của container Triton vẫn tăng khoảng 7,7 MiB mỗi giờ sau giờ đầu.** 8 giờ không đủ để biết nó dừng hay tăng tiếp, và con số này gồm cả page cache của container. Đây là điểm chưa kết luận; cần soak dài hơn (24 giờ) để trả lời.
- VRAM không đổi. Trong lúc chuyển model VRAM lên tới 6.810 MiB (hai model cùng nạp) rồi về lại.
- Kết luận được phép: trong 8 giờ **không thấy rò rỉ rõ ràng ở API và VRAM**. Không được phép: "không rò rỉ".

## 4b. Các bài sau soak

Chạy bằng `tools/run_gpu_post_soak.sh` lúc 17:50 UTC, rồi chạy lại tay một phần (xem "Sự cố" bên dưới).

**G6 — hết VRAM giữa lúc suy luận: đạt** (`compose/session-gpu-post-report.json`). Model `model-vram` cấp bộ nhớ theo ảnh. Với VRAM bị chiếm còn 199 MiB: ảnh cần khoảng 4 GB → request đó `FAILED/BACKEND_ERROR`, không có kết luận OK/NG; ảnh nhẹ gửi ngay sau trên cùng model → `COMPLETED`; recipe đang chọn giữ nguyên, `readyz` 200, tiến trình Triton không đổi PID; trả VRAM rồi gửi lại ảnh nặng → `COMPLETED`. Sau lần đó Triton giữ 12,9 GB VRAM (bộ cấp phát của ONNX Runtime không trả lại), đáng lưu ý khi tính dung lượng.

**Quét theo số instance và mức đồng thời, gọi thẳng Triton** (`compose/triton-direct-sweep-report.json`): 12 ô, mỗi ô 20 giây, 0 lỗi, cùng ảnh ra cùng điểm ở mọi instance.

| Instance | Throughput (req/s) ở 1 / 2 / 4 / 8 luồng | p95 (ms) ở 1 / 2 / 4 / 8 luồng | VRAM (MiB) |
|---|---|---|---|
| 1 | 1,68 / 1,70 / 1,69 / 1,68 | 597 / 1.186 / 2.371 / 4.767 | 4.636 |
| 2 | 1,66 / 1,68 / 1,68 / 1,68 | 607 / 1.195 / 2.375 / 4.756 | 8.878 |
| 4 | 1,65 / 1,67 / 1,67 / 1,67 | 607 / 1.203 / 2.420 / 4.855 | 17.368 |

Thêm instance **không** tăng throughput: một instance đã dùng hết GPU (bận 100%). Thêm instance chỉ tốn VRAM (khoảng 4,2 GB mỗi instance), thêm luồng gửi chỉ làm request chờ lâu hơn. Với model này trên GPU này, trần 1,7 req/s là của GPU, không phải của API hay của việc chỉ có một instance. Bài này gọi thẳng Triton, không qua API và ledger.

**Kubernetes có GPU, lượt hai: 10/10** (`k8s/post-soak/k8s-report.txt`).

**Reboot node Kubernetes có GPU:** lượt đầu **hỏng**, lượt hai (sau khi sửa) đạt.

- Lượt đầu (`k8s/post-soak/after-reboot.txt`): sau reboot 452 giây API server vẫn không lên. Nguyên nhân: swap bật lại sau reboot nên kubelet từ chối chạy. Script dựng lab tắt swap trong `/etc/fstab` bằng mẫu tìm dấu cách, còn máy này ngăn cột bằng tab. Ở phiên CPU lỗi này không lộ vì máy đó không có swap. Sửa ở commit `ecaa036`.
- Lượt hai (`k8s/post-soak/after-reboot-2.txt`): sau khi tắt swap đúng cách, reboot lại → 192 giây sau lệnh reboot thì `readyz` 200, recipe đang chọn giữ nguyên, smoke 18/18, node khai báo 1 GPU, `tritonserver` chạy trên GPU. Pod cũ rơi vào `UnexpectedAdmissionError` (GPU chưa sẵn sàng lúc kubelet khởi động) và Deployment tự tạo pod mới.

**Gói offline lớp ứng dụng trên node GPU** (overlay `offline-gpu`):

- Lượt tự động (`k8s/post-soak/offline-report.txt`): 5/7. Tạo gói (7,1 GB, 89 file), cắt Internet (IPv4 + IPv6), xóa image đều đạt; bước cài và smoke hỏng vì Kubernetes đang chết do lỗi swap ở trên.
- Lượt chạy lại tay sau khi sửa swap (`k8s/post-soak/offline-rerun-report.txt`, script `post-rerun.sh`): Internet vẫn bị cắt; cài từ gói 184 giây; pod Triton được cấp 1 GPU và chạy `KIND_GPU`; không có lần kéo image nào; cuối bài Internet vẫn bị cắt. Báo cáo ghi 6/8 vì hai dòng cần giải thích:
  - R2 "image vắng mặt trước khi cài" FAIL: hai image đã được lượt tự động nạp **từ chính gói** trước khi nó hỏng ở bước triển khai, nên lần này không còn là cài lên node trắng image. Không có image nào đến từ Internet.
  - R4 smoke lần đầu 17/18: bước "gửi với recipe cũ ngay sau khi chuyển phải nhận 409" nhận 503 (hệ thống báo chưa sẵn sàng trong khoảnh khắc đang chuyển model). Hai lần smoke kế tiếp đạt 18/18 (`offline-smoke-rerun-2/3`). Cùng hiện tượng với 20 lần 503 lúc chuyển model trong soak: bên gửi cần gửi lại khi gặp 503.

**Sự cố khi chạy:** kết nối SSH từ laptop đứt giữa bước đầu ("Operation timed out"). G6 đã xong trước đó; bài quét instance bị ngắt ở ô 7/12 (`compose/triton-direct-sweep-interrupted.log`) và được chạy lại trọn vẹn ở chế độ tách khỏi SSH. Vì lệnh `make down` không kịp chạy, stack Compose còn sống trong lúc Kubernetes lượt hai chạy; hai stack dùng chung GPU nhưng không tranh cổng, và bài K8s vẫn đạt 10/10.

## 5. Lượt đầu hỏng và hai lỗi đã sửa

Lượt đầu của phần 1 chỉ đạt 10/16 (`compose/attempt1/`). Nguyên nhân và cách sửa:

1. **API giữ giới hạn cũ sau khi đổi kho package.** API đọc kho package và `site-config` một lần lúc khởi động. Bước G2 đổi model nặng từ 512² sang 1024² mà API không được khởi động lại, nên nó từ chối model mới (`E_LIMIT: input larger than max_decoded_pixels`). Sửa ở `3e938bb`: `make start` tự khởi động lại API khi nội dung kho package đổi. Bài G4 của lượt đầu vì thế không hợp lệ (bị từ chối vì giới hạn, không phải vì hết VRAM).
2. **Bài kill API dùng model chạy quá nhanh trên GPU.** `model-slow` xong trước khi kịp kill. Sửa: trên GPU bài này dùng model nặng.
3. **Công cụ quét tải đặt trùng mã request** giữa bước 1,0 và 1,5 req/s (lỗi của công cụ test, không phải của API; API trả 409 đúng). Sửa ở `31f2d9a`; kết quả ở mục 2 là lượt chạy lại.

Soak cũng đã tự khởi động một lần ngay sau lượt đầu (40 giây, tải 0,267 req/s vì chưa có số đo G2); mình dừng nó, chạy lại các bài ngắn rồi mới bắt đầu soak chính thức. Dữ liệu 40 giây đó nằm trong `compose/attempt1/`.

Một lỗi do thao tác tay của người chạy (không phải lỗi hệ thống): đổi mức model nặng trong khi recipe dùng nó đang active → API báo `ACTIVE_RECIPE_UNVERIFIED` và không nhận request (đúng thiết kế: không chạy model đã bị đổi dưới chân). Khôi phục bằng cách đưa đúng model cũ về lại.
