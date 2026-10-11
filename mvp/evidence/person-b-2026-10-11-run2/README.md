# Lượt "người B" lần 2, 11/10/2026 — README đã sửa

**Ai:** một agent AI mới khác (không phải người), không biết dự án, chỉ đọc README của repo công khai, dùng terminal có ghi biên bản (`terminal.jsonl`). Được yêu cầu chép nguyên lệnh trong Quick start, không sửa gì.

**Máy:** VPS Hetzner vừa tạo lại, Ubuntu 26.04.1, 2 vCPU, 3,8 GB RAM, ổ 38 GB; chưa có Docker và make. Repo ở commit `c83b893`.

**Kết luận của người B: DONE_NO_INTERVENTION.** Mọi lệnh thay đổi hệ thống đều chép từ Quick start, và kết quả khớp điều README ghi.

| Lệnh trong Quick start | Kết quả | Khớp README? |
|---|---|---|
| `apt-get update && apt-get install -y docker.io docker-compose-v2 make git` | exit 0, khoảng 19 giây | README không ghi kết quả mong đợi |
| `git clone … && cd vin-vr-01-mvp/mvp` | exit 0 | README không ghi kết quả mong đợi |
| `make start` | exit 0, hai dòng cuối `Container vr01-mvp-triton-1  Healthy`, `Container vr01-mvp-api-1  Healthy`; khoảng 2 phút 9 giây | Khớp |
| `make smoke` | `SMOKE PASS  18/18  -> run/smoke-report.json` | Khớp |
| `make test` | exit 0, `MVP tests: PASS  72/73 passed, static 11/11` | Khớp |

Tổng khoảng 4,5 phút. Cuối lượt: ổ dùng 22 GB / 38 GB, RAM available 3,1 GB.

**Nhận xét của người B về tài liệu (không chặn, đã sửa trong README sau lượt này):** không nói cần quyền root/sudo; `python3` được nêu là cần nhưng không có trong lệnh `apt-get`; dòng cuối của `make test` có thêm phần đường dẫn mà README không trích.

**Phạm vi:** cần Internet (cài gói, clone, tải image), không phải air gap. Người chạy là AI, chưa phải kỹ thuật viên người.
