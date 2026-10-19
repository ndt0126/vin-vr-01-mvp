# VR-01 MVP — Inspection API + lifecycle + Triton (W3-01 → W3-05)

Trạng thái 19/10/2026 (bản `0.5.0-rc2`, có giao diện trạm): **bản lab, đã chạy với Triton thật trên VPS amd64, cả CPU và GPU NVIDIA (RTX A6000), cả Compose và kubeadm**. Soak 8 giờ trên GPU đã xong (12/10). Mentor review 16/10: chấp nhận W2–W5; rc2 chỉ sửa các điểm nhỏ mentor nêu (Python 3.10, test flaky, 503 ngắn sau cutover), xem `docs/RELEASE-0.5.0-rc2.md`. Chưa chạy trên máy đích của nhà máy, chưa air gap đầy đủ.

## Cấu trúc

| Thư mục | Nội dung |
|---|---|
| `backend/` | `inspection_api.py` (business API hai cổng + lifecycle controller), `openapi.v1.yaml` (hợp đồng, bản 1.3.0-draft.1), `requirements.txt` (pin version) |
| `ui/` | Giao diện trạm (W5-02): HTML + JavaScript thuần, do API phục vụ tại `https://<máy>:8443/ui/`, không cần build |
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

Nếu máy **đã có Docker** (ví dụ image máy GPU của nhà cung cấp cài sẵn Docker CE và NVIDIA Container Toolkit; kiểm bằng `docker compose version`), **không** cài `docker.io` vì sẽ xung đột với Docker CE; chỉ cài phần còn thiếu:

```bash
apt-get update && apt-get install -y make git python3
```

**Lấy mã nguồn và vào thư mục `mvp/`** (mọi lệnh `make` bên dưới chạy trong thư mục này):

```bash
git clone https://github.com/ndt0126/vin-vr-01-mvp.git && cd vin-vr-01-mvp/mvp
```

**Máy có GPU NVIDIA** (đã có driver và NVIDIA Container Toolkit): trước lần `make start` đầu tiên, bật cấu hình GPU cho Triton. Máy không có GPU thì bỏ qua bước này.

```bash
make env && sed -i 's/^TRITON_INSTANCE_KIND=.*/TRITON_INSTANCE_KIND=KIND_GPU/; s/^VR01_GPU=.*/VR01_GPU=1/' deploy/.env
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

**Toàn bộ test trong container** (không cần Triton, chạy được khi stack đang bật hoặc tắt). Dòng cuối mong đợi bắt đầu bằng `MVP tests: PASS  108/114 passed, static 11/11` (6 test bỏ qua vì image không cài `onnxruntime`); báo cáo ghi ở `run/test-report-container.json`.

```bash
make test
```

Chạy test ngay trên host (không Docker): cần **Python ≥ 3.10** (đã thử 3.10.0 và 3.12.7) và `pip install -r backend/requirements.txt`; cài thêm `onnxruntime numpy` để chạy cả 6 test model ảnh. Dòng cuối mong đợi `MVP tests: PASS  114/114 passed, static 11/11`.

```bash
make test-local
```

**Dừng** (giữ dữ liệu trong `run/`):

```bash
make stop
```

Lệnh khác: `make backup`, `make restore BACKUP=run/backup/<tên>`, `make load`, `make logs`, `make down`, `make digests`, `make clean` (xóa `run/`).

## Giao diện trạm (W5-02, W5-03) — bản đầu 14/10/2026, phạm vi chờ mentor duyệt

Mở `https://<máy>:8443/ui/` (trên chính máy chạy stack: `https://localhost:8443/ui/`) rồi dán token của một vai trò trong `run/auth/lab-tokens.secret.json`. Chứng chỉ là chứng chỉ lab tự ký nên trình duyệt sẽ cảnh báo; tài khoản admin còn phải mở `https://<máy>:9443/healthz` một lần để trình duyệt chấp nhận cổng quản trị.

| Mục backlog | Màn hình | Vai trò |
|---|---|---|
| B1 trạng thái sẵn sàng + lý do, recipe/model đang chọn kèm digest | Tổng quan, chip trên đầu (tự kiểm mỗi 5 giây) | mọi vai trò |
| B2 gửi ảnh (3 ảnh mẫu hoặc ảnh từ máy), hiện OK/NG/REVIEW; lỗi kỹ thuật hiện "CHƯA CÓ KẾT LUẬN"; hủy; kiểm lại bằng `retry_of` | Kiểm tra | operator |
| B3 lịch sử lọc theo trạng thái/sản phẩm, chi tiết có request_id, trace, recipe, model, SHA-256 ảnh | Lịch sử | mọi vai trò |
| B4 chuyển recipe và rollback qua hộp thoại bắt buộc ghi lý do | Recipe và model | admin |
| B5 viewer/operator không thấy màn quản trị, UI không gọi cổng 9443 | — | — |
| B6 số đếm OK/NG/REVIEW/chưa có kết luận từ 00:00 | Tổng quan | mọi vai trò |
| B7 lịch sử chuyển recipe, cảnh báo khi hệ thống tự rollback | Tổng quan | mọi vai trò |

API thêm cho UI (hợp đồng 1.3.0, chỉ bổ sung, không phá client cũ): `GET /v1/me`, `GET /v1/stations/{id}/summary`, `GET /v1/stations/{id}/activations`, và `GET /v1/inspections` không cần bộ lọc. Cổng quản trị trả header CORS chỉ cho trang cùng hostname (hoặc danh sách `--ui-origin`); xác thực vẫn bằng token, không dùng cookie.

**Test:** `tests/test_ui.py` (11 test phía server, nằm trong `make test`) và test E2E bằng trình duyệt thật `tests/e2e/ui.e2e.mjs` (10 kịch bản E01–E10, Playwright):

```bash
make e2e-setup
make e2e
```

`make e2e-setup` cần Node.js ≥ 18, npm và Internet (tải Playwright + Chromium); trên Ubuntu cài bằng `apt-get install -y nodejs npm`. `make e2e` chạy trên stack đang bật, đổi recipe trong lúc chạy và trả về `recipe-a` khi xong; kết quả và ảnh chụp màn hình ở `run/e2e/`. Kịch bản E07 (lỗi kỹ thuật + tự rollback) và E08 (hủy) cần các fixture `model-bad`, `model-slow`: bật stack bằng `make start SLOW=1`; với `make start` thường hai kịch bản này được bỏ qua (SKIP) kèm lý do.

**Giới hạn:** token lab nằm trong trình duyệt (sessionStorage của tab), chưa có đăng nhập người dùng (B11, chờ quyết định định danh/PKI); chưa thử trên màn cảm ứng thật; chưa kiểm accessibility đầy đủ; phạm vi B1–B7 là đề xuất của mình, **chưa được mentor/stakeholder duyệt** (W5-01).

## Phiên GPU Tuần 5 (14/10/2026) — tóm tắt

Máy RTX A6000 thuê, Compose, Triton `KIND_GPU`, bản `0.5.0-rc1`. Người B (agent AI) cài từ README không cần can thiệp. UAT tự động theo checklist W5-04: **24/24 đạt**; giao diện E2E 10/10 trước sự cố, sau sự cố/nâng cấp và sau reboot cả máy; dừng Triton thật thì UI báo chưa sẵn sàng sau 1,3–2,8 s. Phiên lộ 3 lỗi ở fixture/script kiểm và UI (không ở API), đã sửa và chạy lại đạt. Chi tiết: `evidence/vps-w5-2026-10-14T0649Z/README.md`, `docs/RELEASE-0.5.0-rc1.md`.

## Phiên VPS Tuần 4 (11/10/2026, CPU) — tóm tắt

Trên một VPS mới 4 vCPU / 8 GB, Triton thật, model chạy CPU. Chi tiết, số liệu và giới hạn: `evidence/vps-w4-2026-10-11T0754Z/README.md`.

- **Runbook (W4-05):** một agent AI độc lập làm trọn 8 việc theo runbook, không can thiệp (`evidence/person-b-2026-10-11-runbook/`).
- **Observability (W4-01, W4-02):** scrape API và Triton; cảnh báo model-unavailable bật 20 giây sau khi dừng Triton và tắt sau 4–6 giây; truy vết một request từ `request_id`.
- **Độ bền:** tự rollback khi model mới lỗi 3 lần; nâng cấp và quay lại image app dưới tải (901 request, 0 sai/mất); cắt mạng 10 giây (0 mất/trùng); ổ ảnh đầy thật (503 sạch, tự phục vụ lại).
- **Kubernetes (W4-03):** kubeadm v1.34.12 + Calico: bài kiểm 10/10, reboot node tự lên lại, gói offline lớp ứng dụng cài được khi IPv4 và IPv6 đều bị chặn (7/7).
- **Model ảnh thật** (`triton-onnx-v1`): golden qua Triton đạt, khoảng 104 ms/lần; quét tải bão hòa ở khoảng 8 request/giây với 1 worker.
- Lượt chính có 4 bước hỏng, đều do script kiểm của tác giả (2 bước) hoặc bước cắt mạng chưa chặn IPv6 (2 bước); đã sửa và chạy lại đạt. **Chưa chạy GPU; kubeadm cài có Internet; gói offline chưa ký.**

## Phiên GPU (W4-04, W4-03 trên GPU) — 11/10/2026

Trên một VPS thuê có RTX A6000 48 GB (NVIDIA, có Internet). Chi tiết, số liệu và giới hạn: `evidence/vps-gpu-2026-10-11T0905Z/README.md`.

- **Compose trên GPU: 16/16** (`tests/real_session.py --phase gpu`), sau khi sửa hai lỗi lộ ra ở lượt đầu (10/16). Model nặng chạy `KIND_GPU` thật (590 ms mỗi lần ở mức `gpu-xl`, VRAM 4,6 GB); chuyển qua lại hai model nặng dưới tải 5 phút: 256 request, 9/9 lần chuyển, 0 sai, 0 trùng.
- **Hết VRAM:** lúc nạp model và khi nạp model thứ hai cạnh model đang chạy, kích hoạt bị từ chối 422, recipe cũ vẫn phục vụ, không cần restart (dùng `tests/vram_hog.py` chiếm VRAM).
- **Quét tải model nặng:** trần khoảng 1,66 req/s với một instance; quá trần thì hàng đợi dài ra rồi trả 429.
- **Kubernetes có GPU: 10/10** với `deploy/k8s/lab-kubeadm-gpu.sh` (kubeadm + NVIDIA device plugin) và overlay `lab-gpu`.
- **Soak 8 giờ** không restart định kỳ: 19.528 request, 0 sai, 0 trùng, 95/95 lần chuyển model, p95 612 ms, không container nào restart, VRAM không đổi. Công cụ kết luận REVIEW: RAM của API tăng trong giờ đầu rồi phẳng; RAM container Triton còn tăng khoảng 7,7 MiB mỗi giờ, 8 giờ chưa đủ để kết luận.
- **Hết VRAM giữa lúc suy luận (G6):** request đó `FAILED`, model vẫn phục vụ request kế tiếp, Triton không restart.
- **Quét số instance × mức đồng thời (gọi thẳng Triton):** 1, 2 hay 4 instance đều cho khoảng 1,7 req/s; GPU đã bận 100% với một instance.
- **Reboot node Kubernetes có GPU:** lượt đầu hỏng vì swap bật lại sau reboot (script tắt swap không khớp `fstab` ngăn bằng tab; đã sửa); lượt hai tự lên lại sau 192 giây, smoke 18/18.
- **Gói offline trên node GPU** (overlay `offline-gpu`): cài được khi Internet bị cắt, Triton chạy trên GPU; lượt tự động hỏng do lỗi swap ở trên, lượt chạy lại tay đạt với hai điểm cần đọc trong README của evidence.
- Báo cáo tổng hợp: `docs/W4-04-REPORT.md`.

## Observability (W4-01, W4-02)

```bash
make obs-start
```

Bật thêm Prometheus (`http://127.0.0.1:9091`) và Grafana (`http://127.0.0.1:3000`, chỉ xem). API có cổng `/metrics` riêng (9090, chỉ trong mạng Compose) với 30 metric: request theo trạng thái/kết luận/mã lỗi, độ trễ từng pha, hàng đợi, vòng đời model, readiness kèm lý do, recipe/model đang active kèm digest, RAM/CPU tiến trình, ổ trống. Có 10 luật cảnh báo, dashboard 18 panel, log JSON xoay vòng có trần dung lượng, và `make trace ID=<request_id>` để lấy toàn bộ đường đi của một request. Chi tiết: `docs/OBSERVABILITY.md` (sinh tự động).

Đã kiểm (11/10, laptop): 6 test metrics/log trong bộ 79 test; `make alerts-test` (promtool) chứng minh 5 cảnh báo chính bật khi có sự cố và tắt khi hết; Prometheus và Grafana thật chạy trong Docker, scrape được API chạy với inference server **giả**, truy vấn ra số và dashboard được nạp. Trên stack có Triton thật (11/10): 6/6 bước của `tests/real_session.py --phase obs` đạt. **Chưa có:** Alertmanager, metric mức container/node, ngưỡng do Operations duyệt.

## Kubernetes (W4-03) và runbook (W4-05)

- `deploy/k8s/`: manifests kustomize (base + overlay CPU, GPU, offline), script dựng kubeadm lab, nạp image, bài kiểm 10 bước, và bộ script gói offline cho lớp ứng dụng. Đã chạy 10/10 bước trên **kubeadm thật với Triton thật** (11/10), reboot node, và gói offline 7/7 với Internet bị chặn. Chưa có GPU, lớp nền Kubernetes vẫn cài online, gói chưa ký. Xem `deploy/k8s/README.md`.
- `docs/RUNBOOK.md`: cài/bật/dừng, đổi và rollback model, sao lưu và khôi phục, nâng cấp, cây xử lý sự cố, gói chẩn đoán, giới hạn đã biết. Mỗi quy trình ghi rõ đã chạy thật, mới chạy trên laptop, hay chưa diễn tập. Một agent AI độc lập đã làm trọn runbook không can thiệp; chưa có người vận hành tự làm.
- Kịch bản đã chạy trên Triton thật ngày 11/10: tự rollback bằng fixture `model-bad` (qua golden nhưng lỗi trên ảnh sáng), ổ lưu ảnh đầy thật, nâng cấp và quay lại phiên bản app khi đang có tải, cắt mạng 10 giây (`tests/real_session.py --phase w4`); `tests/load_sweep.py` quét tải tới bão hòa.
- **Model ảnh thật theo chuẩn package** (`docs/MODEL-PACKAGES.md`): backend `triton-onnx-v1` mà schema W2-05 đã khai báo nay được hiện thực (validator, tiền xử lý RGB theo package đã pin, gửi tensor dạng binary sang Triton, model repository). `make start HEAVY=cpu|gpu|gpu-xl` thêm fixture `model-heavy`: mạng tích chập sâu với trọng số tất định, là tải tính toán thật cho bài hiệu năng, **không phải model QC**. Đã kiểm trên laptop (10 test) và trên Triton thật bản CPU (golden đạt, quét tải); **chưa chạy GPU**.
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

`make start GPU=1` (hoặc `VR01_GPU=1` trong `deploy/.env`) thêm cấu hình GPU cho Triton (`deploy/docker-compose.gpu.yml`); đã chạy ở phiên GPU 11/10.

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

- **Máy đích của nhà máy:** mới chạy trên GPU NVIDIA thuê (RTX A6000, cấu hình lab tham chiếu của dự án). Cấu hình máy đích (GPU, OS, driver) chưa được IT duyệt, nên chưa có lượt chạy nào trên đúng máy đó.
- Xu hướng RAM của container Triton trong soak (tăng khoảng 7,7 MiB mỗi giờ) chưa có kết luận; cần soak 24 giờ.
- **Máy sạch bởi người khác:** ngày 11/10 có hai lượt do agent AI độc lập (không phải người) chỉ đọc README, mỗi lượt trên một VPS mới 2 vCPU / 4 GB. Lượt 1 phải đoán 3 bước và bắt được lỗi `make test`; sau khi sửa, **lượt 2 chạy trọn Quick start không cần can thiệp nào** (`make start`, smoke 18/18, test 72/73), ở commit `c83b893`. Biên bản: `evidence/person-b-2026-10-11/` và `evidence/person-b-2026-10-11-run2/`. Chưa có **người** reviewer tự làm.
- Mất điện thật; tải cao với model QC thật (mới quét tải bằng model tự sinh).
- Hủy không giải phóng GPU: inference đang chạy vẫn chạy hết (đã thấy trên Triton thật ở bước P4).
- UI bản đầu (14/10): chưa thử trên màn cảm ứng thật, chưa có người dùng thật thao tác (UAT có người), chưa kiểm accessibility đầy đủ.

## Giới hạn

- **Không phải air gap.** Quick start cần Internet để cài Docker, clone và tải image. MVP này chưa được đóng gói để cài offline; bộ cài offline đã thử của dự án (r4.x, kubeadm) dùng app cũ.

- Hai model mẫu là hàm tuyến tính trên ảnh thu về 2×2 (deterministic stub), không phải model QC. OK/NG/REVIEW ở đây không nói gì về chất lượng sản phẩm.
- Package khai báo tham số (`model.json`); file ONNX được sinh từ tham số đó. Chuẩn package chưa mang trực tiếp file ONNX/TensorRT.
- Auth là bearer token lab, chứng chỉ TLS tự ký 30 ngày. SQLite, 1 worker, 1 node. Chưa mTLS/PKI.
- Compose và manifests Kubernetes đều là bản lab một node.
