# Phiên VPS Tuần 4 — 11/10/2026 (CPU)

**Máy:** VPS Hetzner mới, amd64, Ubuntu 26.04, 4 vCPU, 7,7 GB RAM, ổ 75 GB. Triton 2.60.0 (image `25.08-py3`), mọi model chạy **CPU**. Mã nguồn lấy bằng `git clone` repo công khai.

Phiên có hai lượt: lượt chính (`tools/run_w4_session.sh`, commit `07b87ce`, 07:54–08:13 UTC) và lượt chạy lại các bước hỏng sau khi sửa (commit `0e191c8`, thư mục `rerun/`). Mỗi thư mục có `MANIFEST.sha256` đã đối chiếu với VPS; quét token trong evidence: không có.

## Kết quả

| Phần | Lượt chính | Sau khi sửa và chạy lại |
|---|---|---|
| Compose: observability, tự rollback, nâng cấp app, cắt mạng, đầy ổ, model nặng | 10/12 bước | 2 bước hỏng đều đạt (`rerun/compose/`) |
| Kubernetes kubeadm v1.34.12 + containerd 2.2.2 + Calico, Triton thật | **10/10** | — |
| Reboot node | pod tự lên, recipe active giữ nguyên, smoke 18/18 | — |
| Gói offline lớp ứng dụng | 5/7: cắt Internet **không kín** (chỉ chặn IPv4) | **7/7** với IPv4 + IPv6 đều bị chặn (`rerun/k8s-offline/`) |

### Compose (`compose/session-w4-report.json`, `rerun/compose/`)

| Bước | Kết quả |
|---|---|
| P13 Observability | Prometheus scrape được API và Triton; 1 request + 1 lần chuyển model thấy được qua metric sau 4 giây; `make trace` ra đủ đường đi của request; cảnh báo `VR01ModelUnavailable` **bật 20 giây sau khi dừng Triton, tắt 4–6 giây sau khi bật lại**; Grafana nạp dashboard 18 panel; `/metrics` không mở ra host |
| P14 Tự rollback | Model `model-bad` qua golden, 3 request ảnh sáng `FAILED/BACKEND_ERROR` → hệ thống tự về `recipe-a`; 3 request lỗi giữ lineage `model-bad`; request sau đó chạy bình thường |
| P16 Nâng cấp và quay lại image API khi đang có tải | `0.1.0 → 0.1.1-test → 0.1.0`, mỗi chiều khoảng 8,7 giây (gồm build + chờ healthy). 901 request: 0 sai, 0 trùng, 0 bị bỏ; client gặp 49 lỗi kết nối và gửi lại cùng mã; recipe active giữ nguyên |
| P17 Cắt mạng 10 giây (iptables) khi đang có tải | 401 request: 0 mất, 0 trùng; 5 lỗi kết nối phía client, gửi lại cùng mã |
| P15 Ổ lưu ảnh đầy thật (tmpfs 64 KiB) | 16 request được nhận trước khi đầy; sau đó `503 STORAGE_UNAVAILABLE`, `readyz` 503, request bị từ chối không có bản ghi; có chỗ lại thì phục vụ tiếp |
| P18 Model ảnh thật (`triton-onnx-v1`, mức `cpu`) | Golden qua Triton: 0,425518 mong đợi, 0,4255176 thực tế; điểm khác nhau theo ảnh (0,387 / 0,428 / 0,468); suy luận khoảng 104 ms |

Hai bước hỏng ở lượt chính, cả hai do script/công cụ của tác giả chứ không do hệ thống: P13b đọc số "trước" khi Prometheus chưa kịp scrape; P18 không thấy `recipe-heavy` vì một lần `make … SLOW=1` làm mất lựa chọn model nặng (lỗi gộp lựa chọn fixture, đã sửa).

### Quét tải (công cụ `load_sweep.py`, 1 worker, CPU)

| Model | Thời gian suy luận | Throughput tối đa chưa bão hòa | Bão hòa ở |
|---|---|---|---|
| `model-a` (hàm tuyến tính) | vài ms | khoảng 100 request/giây | 200 request/giây |
| `model-heavy` mức `cpu` (tích chập) | khoảng 0,1 giây | khoảng 8 request/giây | 16 request/giây |
| `model-slow` (cố ý chậm) | khoảng 0,5 giây | khoảng 1,8 request/giây | 4 request/giây |

Khi quá tải, hệ thống trả `429 QUEUE_FULL` chứ không treo; ở 400 request/giây throughput hoàn tất tụt còn khoảng 65 và client có 13 lỗi kết nối. **Đây là số của một VPS CPU 4 vCPU với 1 worker và model fixture, không phải năng lực của máy đích.**

### Kubernetes (`k8s/k8s-report.txt`)

Deploy từ namespace sạch 8 giây (image đã có trên node); cả hai container Ready; smoke 18/18 qua NodePort; từ một pod khác: cổng Triton 8000 đóng, API 8443 mở, metrics 9090 bị NetworkPolicy chặn; xóa pod → tự tạo lại sau 6 giây với đúng recipe active; cập nhật revision 11 giây; `rollout undo` 11 giây; đổi và rollback model; smoke lại 18/18. Sau reboot node: sẵn sàng khoảng 45 giây sau khi SSH lên lại.

### Gói offline (`rerun/k8s-offline/offline-report.txt`)

Gói 7,0 GB, 79 file. Trình tự: tạo gói → chặn Internet (IPv4 + IPv6, probe tới nvcr.io, Docker Hub, GitHub, 1.1.1.1 đều bị chặn) → xóa hai image khỏi node và xóa namespace → cài từ gói trong 122 giây → smoke 18/18 bằng công cụ trong gói → sự kiện của pod chỉ có "image already present", không có lần kéo nào → cuối bài Internet vẫn bị chặn.

## Giới hạn

- CPU, model fixture, tải thấp, một lượt. Không phải số đo hiệu năng hay RTO cho máy đích.
- kubeadm được cài **có Internet**; gói offline chỉ gồm lớp ứng dụng. Lớp nền offline (Kubernetes, containerd, driver) của dự án vẫn là bộ r4.x với app cũ.
- Gói offline **chưa ký**. Cắt Internet bằng iptables trên một máy vẫn mở SSH, không phải air gap vật lý.
- Cập nhật phiên bản trên Kubernetes là `Recreate`: có gián đoạn (khoảng 11 giây trong lượt này), không phải rolling update không downtime.
- Thời gian cảnh báo (20 giây) gồm `for: 15s` của luật và chu kỳ scrape 5 giây; ngưỡng chưa được Operations duyệt.
- Chưa chạy GPU.
