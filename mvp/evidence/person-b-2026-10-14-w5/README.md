# Lượt "người B" Tuần 5 — cài từ release trên máy GPU, 14/10/2026

**Ai:** một agent AI mới (không phải người), không biết dự án, chỉ đọc `mvp/README.md` của repo công khai ở commit `df28aab`, dùng terminal có ghi biên bản (`terminal.jsonl`, 26 lệnh). Không được đọc file trên laptop, không được sửa dự án.

**Máy:** DeployGPU `d7741cfd…`, RTX A6000 48 GB, Ubuntu 24.04.4, driver 580.126.16, image nhà cung cấp có sẵn Docker CE 29.2.1 + Compose 5.0.2 + NVIDIA Container Toolkit. Trước lượt này tác giả đã sửa 2 lỗi README có thể chặn người B (xem `PRE-RUN-FIXES.md`).

**Kết luận của người B:** cài xong **không can thiệp** (INTERVENTIONS: none), nhưng có 2 chỗ lệch với README.

| Việc | Lệnh theo README | Kết quả | Khớp README? |
|---|---|---|---|
| Cài gói | nhánh "máy đã có Docker": `apt-get install -y make git python3` | exit 0 | Khớp |
| Bật GPU | `make env && sed … KIND_GPU … VR01_GPU=1` | exit 0; `nvidia-smi -L` trong container Triton thấy A6000 | Khớp (README chưa nói cách xác nhận Triton dùng GPU) |
| `make start` | | exit 0, 172 s, hai dòng `Healthy` | Khớp |
| `make smoke` | | `SMOKE PASS 18/18` | Khớp |
| `make test` | | `PASS 105/111` (6 test bỏ qua vì thiếu onnxruntime) | **Lệch**: README ghi 107/111, mình đếm sai số test bỏ qua |
| Cài Node | `apt-get install -y nodejs npm` (theo README) | Node 18.19.1, npm 9.2.0 | Khớp |
| `make e2e-setup` | | exit 0, 35 s | Khớp |
| `make e2e` | | 8 PASS, 1 FAIL (E07), 1 SKIP (E08) | **Lệch**: README ghi fixture `model-bad` "luôn có" nhưng thực tế chỉ có khi `make start SLOW=1` |
| UI | `curl -k https://localhost:8443/ui/` | 200, title "VR-01 Trạm QC" | Khớp |

**Số đo đáng chú ý (Triton thật, GPU):** E09 dừng Triton thật → giao diện báo "chưa sẵn sàng" sau **2,8 giây** (tiêu chí ≤ 10 s); bật lại thì về "sẵn sàng".

**Đã sửa sau lượt này (commit `f89aafc`):** README ghi đúng số test; E07 tự SKIP kèm lý do khi thiếu fixture (như E08) và README nói rõ E07/E08 cần `make start SLOW=1`. Sau đó commit `abede1b` thêm 1 test nên số trong README thành 106/112. **README đã sửa chưa được một lượt độc lập khác chạy lại.**

**Phạm vi:** cần Internet (apt, clone, image, Playwright), không phải air gap. Người chạy là AI, chưa phải kỹ thuật viên người.

Raw: `terminal.jsonl`, `server-logs/` (log các bước, `smoke-report.json`, `test-report-container.json`, `e2e/` gồm ảnh chụp, video từng kịch bản và `e2e-results.json`).
