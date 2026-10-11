# VR-01 MVP — Inspection API + lifecycle + Triton (W3-01 → W3-05)

Trạng thái 11/10/2026: **bản đầu, đã chạy với Triton thật (CPU) trên VPS amd64**. Chưa GPU, chưa Kubernetes, chưa được mentor review.

## Cấu trúc

| Thư mục | Nội dung |
|---|---|
| `backend/` | `inspection_api.py` (business API hai cổng + lifecycle controller), `openapi.v1.yaml` (hợp đồng, bản 1.2.0-draft.1), `requirements.txt` (pin version) |
| `packages/` | Chuẩn ModelPackage/Recipe của W2-05: validator, schema, 2 package + 2 recipe mẫu |
| `tools/` | `build_triton_repo.py` (package → Triton model repository), `init_lab.py` (token, chứng chỉ TLS lab, model repository) |
| `deploy/` | `Dockerfile`, `docker-compose.yml`, `.env.sample` |
| `tests/` | `run_tests.py` (một lệnh chạy mọi test), `smoke.py` (smoke flow qua HTTPS), `load_cutover.py` (chuyển recipe dưới tải liên tục), `local_stack.py` (chạy thử không cần Docker, inference server giả) |
| `docs/API.md`, `TEST-REPORT.md` | Sinh tự động từ spec và từ raw evidence |
| `run/` | Dữ liệu lúc chạy: ledger, ảnh, token, chứng chỉ. Không đưa vào repo |

## Quick start

**Máy cần có:** Linux amd64 (đã chạy trên Ubuntu 26.04), tối thiểu 2 vCPU, 4 GB RAM và khoảng 30 GB ổ trống (image Triton 20 GB sau khi bung). Cần Docker có Compose v2, `make`, `git` và `python3`. Các lệnh dưới đây chạy bằng `root` (hoặc thêm `sudo` và cho user vào nhóm `docker`). Trên Ubuntu mới cài:

```bash
apt-get update && apt-get install -y docker.io docker-compose-v2 make git python3
```

**Lấy mã nguồn và vào thư mục `mvp/`** (mọi lệnh `make` bên dưới chạy trong thư mục này):

```bash
git clone https://github.com/ndt0126/vin-vr-01-mvp.git && cd vin-vr-01-mvp/mvp
```

**Bật stack:**

```bash
make start
```

Lệnh này build image API, tạo token + chứng chỉ TLS lab + model repository trong `run/`, bật Triton và API, rồi chờ tới khi cả hai healthy. Lần đầu phải tải image Triton (khoảng 7 GiB nén; vài phút tùy đường truyền). Thành công khi lệnh thoát với mã 0 và hai dòng cuối là `Container vr01-mvp-triton-1  Healthy` và `Container vr01-mvp-api-1  Healthy`. Cảnh báo `buildx isn't installed` của Compose là vô hại.

**Smoke flow** (stack phải đang chạy). Dòng cuối mong đợi: `SMOKE PASS  18/18  -> run/smoke-report.json`.

```bash
make smoke
```

**Toàn bộ test trong container** (không cần Triton, chạy được khi stack đang bật hoặc tắt). Dòng cuối mong đợi bắt đầu bằng `MVP tests: PASS  85/86 passed, static 11/11` (1 test bỏ qua vì image không cài `onnxruntime`); báo cáo ghi ở `run/test-report-container.json`.

```bash
make test
```

**Dừng** (giữ dữ liệu trong `run/`):

```bash
make stop
```

Lệnh khác: `make backup`, `make restore BACKUP=run/backup/<tên>`, `make load`, `make logs`, `make down`, `make digests`, `make clean` (xóa `run/`).

## Observability (W4-01, W4-02) — bản đầu, chưa chạy trên stack thật

```bash
make obs-start
```

Bật thêm Prometheus (`http://127.0.0.1:9091`) và Grafana (`http://127.0.0.1:3000`, chỉ xem). API có cổng `/metrics` riêng (9090, chỉ trong mạng Compose) với 30 metric: request theo trạng thái/kết luận/mã lỗi, độ trễ từng pha, hàng đợi, vòng đời model, readiness kèm lý do, recipe/model đang active kèm digest, RAM/CPU tiến trình, ổ trống. Có 10 luật cảnh báo, dashboard 18 panel, log JSON xoay vòng có trần dung lượng, và `make trace ID=<request_id>` để lấy toàn bộ đường đi của một request. Chi tiết: `docs/OBSERVABILITY.md` (sinh tự động).

Đã kiểm (11/10, laptop): 6 test metrics/log trong bộ 79 test; `make alerts-test` (promtool) chứng minh 5 cảnh báo chính bật khi có sự cố và tắt khi hết; Prometheus và Grafana thật chạy trong Docker, scrape được API chạy với inference server **giả**, truy vấn ra số và dashboard được nạp. **Chưa kiểm:** trên stack Compose có Triton thật (scrape Triton, cảnh báo bật/tắt bằng sự cố thật); đã có sẵn bước `tests/real_session.py --phase obs`.

## Kubernetes (W4-03) và runbook (W4-05) — đã viết, chưa chạy trên cluster

- `deploy/k8s/`: manifests kustomize (base + overlay CPU, GPU, offline), script dựng kubeadm lab, nạp image, bài kiểm 10 bước, và bộ script gói offline cho lớp ứng dụng. Đã chạy thử 10/10 bước trên một cluster k3s trong Docker với inference server **giả**. **Chưa chạy trên kubeadm, chưa chạy với Triton thật, gói offline chưa thử.** Xem `deploy/k8s/README.md`.
- `docs/RUNBOOK.md`: cài/bật/dừng, đổi và rollback model, sao lưu và khôi phục, nâng cấp, cây xử lý sự cố, gói chẩn đoán, giới hạn đã biết. Mỗi quy trình ghi rõ đã chạy thật, mới chạy trên laptop, hay chưa diễn tập. **Chưa có ai khác tự làm theo runbook.**
- Kịch bản đã viết cho phiên VPS, chưa chạy trên Triton thật: tự rollback bằng fixture `model-bad` (qua golden nhưng lỗi trên ảnh sáng), ổ lưu ảnh đầy thật, nâng cấp và quay lại phiên bản app khi đang có tải, cắt mạng 10 giây (`tests/real_session.py --phase w4`); `tests/load_sweep.py` quét tải tới bão hòa.
- Công cụ mới: `tools/vr01ctl.py` (status, activate, rollback, history, audit, pending, result) và `make diag` (gói chẩn đoán không chứa secret).

## Phiên kiểm trên stack thật

`tests/real_session.py` gom các kịch bản cần Triton thật vào một lệnh: smoke, chuyển recipe dưới tải, hủy khi đang chạy và khi đang chờ, drain trước khi gỡ model, `kill -9` API khi có request dở, `kill -9` Triton khi đang có tải, sao lưu → giả lập mất dữ liệu → khôi phục, reboot cả máy. Nó cần `make start SLOW=1`, tức thêm fixture `model-slow` (cùng kết quả với `model-a`, cố ý chậm khoảng 1 giây; xem `tests/fixtures/slow/`).

**Đã chạy 11/10/2026** trên VPS Hetzner mới (amd64, Ubuntu 26.04, 2 vCPU / 3,8 GB, Triton 2.60.0, model chạy CPU), mã nguồn lấy bằng `git clone` repo công khai ở commit `c6922f1`: **13/13 bước đạt ngay lượt đầu**, không sửa gì giữa chừng. Log, báo cáo và bảng hash ở `evidence/vps-2026-10-11T0436Z/`.

| Bước | Kết quả chính |
|---|---|
| P1 smoke | 18/18 |
| P2 chuyển recipe A↔B dưới tải (10 request/giây × 60 giây) | 601 request: 0 thiếu, 0 trùng, 0 sai; 11/11 lần chuyển |
| P0, P3 model chậm | khoảng 0,83 giây mỗi lần suy luận trên máy này |
| P4 hủy khi đang chạy | `CANCELLED`; kết quả về muộn bị bỏ và có log; request kế tiếp chạy bình thường |
| P5 hủy khi đang chờ | request bị hủy không tới Triton; hai request kia hoàn tất |
| P6 chuyển recipe khi có request đang chạy | request chạy xong trên model cũ rồi model cũ mới bị gỡ |
| P7 `kill -9` API khi 1 đang chạy + 2 đang chờ | cả 3 thành `INDETERMINATE`; sẵn sàng lại sau 1,5 giây; recipe active giữ nguyên; kiểm lại bằng mã mới đạt |
| P8 `kill -9` Triton khi đang có tải | 501 request: 0 sai, 0 trùng. Trong lúc Triton chết, client nhận 20 lần 503 và gửi lại cùng mã; cuối cùng cả 501 hoàn tất |
| P9 sao lưu → giả lập mất dữ liệu → khôi phục | backup integrity ok (1.119 dòng); sau khi mất: tra request cũ 404; sau khôi phục: kết quả y hệt, recipe active đúng; khoảng 25 giây |
| P10, R1, R2 reboot cả máy | stack tự lên, recipe active và kết quả cũ còn nguyên, smoke 18/18 |
| `make test` trong container | 72/73 đạt, 1 bỏ qua |

**Ba kịch bản bổ sung, cùng ngày, cùng VPS, commit `9c8071a`** (4/4 bước đạt; `evidence/vps-2026-10-11T0452Z-extra/`):

| Bước | Kết quả chính |
|---|---|
| P9 (bản mới) `make backup` → giả lập mất dữ liệu → `make restore` | Bản sao lưu gồm ledger (1.124 dòng, integrity ok), `trace.jsonl` và 256 ảnh, có bảng hash. Sau khôi phục: kết quả y hệt, trace của request kiểm còn đủ (4/4 sự kiện), recipe active đúng; khoảng 24 giây |
| P11 execution timeout trên Triton thật | Hạ timeout xuống 0,3 giây (model chậm 0,83 giây): request thành `TIMEOUT` / `EXECUTION_TIMEOUT`; kết quả về muộn bị bỏ và có log; trạng thái không đổi; hệ thống vẫn sẵn sàng. Trả timeout về 10 giây thì request chậm chạy xong bình thường |
| P12 dừng hẳn Triton khoảng 24 giây khi đang có tải | `readyz` trả 503 suốt thời gian đó. 601 request: 597 hoàn tất, 4 bị từ chối sạch (client thử lại 5 giây rồi bỏ, **không** có record nào được tạo), 0 sai, 0 trùng; client nhận 217 lần 503. Bật lại Triton thì hệ thống tự nạp model và phục vụ tiếp |

Điều cần đọc kèm:

- Đây là **một lượt**, tải thấp (10 request/giây), model mẫu chạy vài mili giây trên CPU. Không phải số đo hiệu năng hay RTO cho máy đích.
- **Cần Internet** (cài Docker, clone, tải image): đây không phải air gap.
- Sao lưu: bản sao nằm trên **chính máy đó** (không bảo vệ khi hỏng ổ); chưa có lịch sao lưu tự động. Lượt P9 đầu tiên (sáng 11/10) cho thấy trace không nằm trong bản sao lưu; `make backup` đã sửa điểm này.
- P12: trong lúc Triton dừng, bên gửi bị chặn ở từng request (thử lại 5 giây), nên các request sau bị gửi trễ chứ không mất. Hành vi của camera thật khi bị chặn như vậy cần Integration xem.

`make start GPU=1` thêm cấu hình GPU cho Triton (`deploy/docker-compose.gpu.yml`); chưa chạy thử.

## Smoke flow kiểm gì

`readyz` → thiếu token 401 → viewer gửi ảnh 403 → operator gọi management 403 → không có route Triton trên business API → admin chọn recipe A → 2 ảnh ra OK/NG với lineage `model-a` → ảnh hỏng 422 → gửi lại cùng ID trả 200 replay → cùng ID khác sản phẩm 409 → admin chuyển recipe B → recipe cũ bị 409 → ảnh mới có lineage `model-b` → kết quả đã pin A không đổi → liệt kê theo state. Kết quả ghi ở `run/smoke-report.json`.

## Khác gì so với server tham chiếu W2-04

- Mọi UPDATE trạng thái có điều kiện trạng thái nguồn; dòng đã kết thúc không ghi đè được (W2-03 G1).
- Adapter so `id` của response với `request_id`; lệch thì `FAILED` / `BACKEND_ID_MISMATCH` (G2).
- Lưu và trả `captured_at` (G3); liệt kê theo `state` (G4); lưu ảnh gốc theo SHA-256 trong `run/data/images/` (G5).
- Lifecycle với Triton explicit model control: load candidate → golden check → cutover → drain request đã pin model cũ → unload model cũ. Candidate load/golden lỗi thì giữ recipe cũ. Sau cutover, 3 lỗi backend liên tiếp trong 60 giây thì tự rollback về recipe trước.
- **Hủy request** (`POST /v1/inspections/{id}/cancel`, vai trò operator): trạng thái kết thúc mới `CANCELLED`. Đang chờ thì không bao giờ tới inference server; đang chạy thì kết quả về sau bị bỏ và ghi log; hủy và hoàn tất cùng lúc thì đúng một bên thắng (bên thua nhận `409 ALREADY_TERMINAL`).
- Recipe/model active được khôi phục từ ledger khi khởi động lại. Nếu inference server mất model (khởi động lại), readiness tự nạp lại đúng model active.

Hợp đồng đang ở 1.2.0-draft.1. Các thay đổi đều là bổ sung: `captured_at` trong result, tham số `state` cho danh sách, reason `BACKEND_ID_MISMATCH`, và (11/10) operation `cancelInspection` với state `CANCELLED`, reason `CANCELLED_BY_CLIENT`, mã lỗi `ALREADY_TERMINAL`. Lưu ý cho client cũ: `state` giờ có thêm giá trị `CANCELLED`; client phải coi mọi state lạ là "chưa có kết luận".

## Đã kiểm chứng (10/10/2026)

**Lượt 10/10 (bản code ngày 10/10: smoke khi đó có 16 bước, bộ test 65):** VPS Hetzner amd64, Ubuntu 26.04.1, 4 vCPU / 8 GB, Docker 29.1.3, Triton 2.60.0 (image `25.08-py3`), model chạy CPU. Log và báo cáo ở `evidence/vps-2026-10-10/` (không gồm token và private key).

| # | Kịch bản | Kết quả |
|---|---|---|
| 1 | `make down` → `make start` → `make smoke` | start exit 0, smoke 16/16 |
| 2 | `make start` lần nữa khi stack đang chạy | exit 0, smoke 16/16 |
| 3 | Chỉ khởi động lại Triton (explicit mode nên mất hết model đã nạp) | API tự nạp lại đúng model active, `readyz` 200 sau vài giây, recipe vẫn `recipe-b`, smoke 16/16 |
| 4 | `kill -9` tiến trình API từ host | Docker khởi động lại container, recipe active vẫn `recipe-b`, smoke 16/16 |
| 5 | `make stop` → `make start` | recipe active vẫn `recipe-b`, smoke 16/16 |
| 6 | `make test` trong container | 64/65 đạt, 1 bỏ qua (image không có `onnxruntime`); kiểm tĩnh OpenAPI 11/11 |
| 7 | Chạy lại từ đầu với image pin theo digest (`.env.sample`) | start exit 0, smoke 16/16 |

Triton nạp được file ONNX và `config.pbtxt` do `build_triton_repo.py` sinh ra; golden check qua Triton ra đúng 0,375 và 0,3125. Log Triton có đúng trình tự nạp model mới rồi gỡ model cũ khi chuyển recipe.

**Lỗi tìm thấy nhờ chạy thật, đã sửa và có test:**

1. `make start` lần hai xóa rồi tạo lại thư mục model repository, làm Triton đang chạy mất repository ("model not found"). Giờ thư mục được giữ nguyên, nội dung không đổi thì không đụng tới.
2. Khi model active không còn được nạp (Triton khởi động lại, hoặc nạp lỗi lúc boot), API kẹt ở not-ready. Giờ readiness tự nạp lại đúng model active và chạy lại golden; không tự đổi sang recipe khác.

Ghi chú vận hành: `docker kill` được Docker coi là dừng thủ công nên container **không** tự khởi động lại; kịch bản 4 dùng `kill -9` lên PID từ host.

**Laptop macOS arm64 (sau lượt VPS, bản 11/10 có cancellation):** bộ test trên host 73/73; smoke 18/18 với inference server giả (`tests/local_stack.py`).

**Chuyển recipe dưới tải liên tục (`make load`, mới chạy với inference server giả):** 3 lượt, mỗi lượt 1.001 request ở 50 request/giây, chuyển recipe mỗi giây (19 lần): 0 thiếu, 0 trùng, 0 sai recipe/model/ảnh/điểm, 19/19 lần chuyển đạt. Lượt đầu tiên của bài này (trước khi sửa) lộ lỗi thứ 3:

3. Request được pin vào model cũ đúng lúc chuyển có thể chạy **sau khi** model cũ đã bị gỡ, và kết thúc `FAILED` (1/401 request). Nguyên nhân: việc đếm request theo model diễn ra sau thời điểm pin. Đã sửa (đếm ngay trong lúc pin) và có test hồi quy. **Bản chạy trên VPS là bản trước khi sửa lỗi này**; bản đã sửa chưa chạy với Triton thật.

Số liệu chi tiết và file nguồn: `TEST-REPORT.md` (sinh bằng `make report`). Tài liệu API: `docs/API.md` (sinh bằng `make docs`, test kiểm nó khớp spec).

## Chưa kiểm chứng

- **GPU:** model mới chạy `KIND_CPU`. `KIND_GPU` chỉ được ghi vào `config.pbtxt`; Compose chưa có cấu hình GPU cho Triton.
- **Máy sạch bởi người khác:** ngày 11/10 có hai lượt do agent AI độc lập (không phải người) chỉ đọc README, mỗi lượt trên một VPS mới 2 vCPU / 4 GB. Lượt 1 phải đoán 3 bước và bắt được lỗi `make test`; sau khi sửa, **lượt 2 chạy trọn Quick start không cần can thiệp nào** (`make start`, smoke 18/18, test 72/73), ở commit `c83b893`. Biên bản: `evidence/person-b-2026-10-11/` và `evidence/person-b-2026-10-11-run2/`. Chưa có **người** reviewer tự làm.
- Tải cao, soak dài, đầy ổ, mất điện thật.
- Hủy không giải phóng GPU: inference đang chạy vẫn chạy hết (đã thấy trên Triton thật ở bước P4).
- Chưa có UI.

## Giới hạn

- **Không phải air gap.** Quick start cần Internet để cài Docker, clone và tải image. MVP này chưa được đóng gói để cài offline; bộ cài offline đã thử của dự án (r4.x, kubeadm) dùng app cũ.

- Hai model mẫu là hàm tuyến tính trên ảnh thu về 2×2 (deterministic stub), không phải model QC. OK/NG/REVIEW ở đây không nói gì về chất lượng sản phẩm.
- Package khai báo tham số (`model.json`); file ONNX được sinh từ tham số đó. Chuẩn package chưa mang trực tiếp file ONNX/TensorRT.
- Auth là bearer token lab, chứng chỉ TLS tự ký 30 ngày. SQLite, 1 worker, 1 node. Chưa mTLS/PKI.
- Đây là Compose cho lab. Triển khai Kubernetes thuộc W4-03.
