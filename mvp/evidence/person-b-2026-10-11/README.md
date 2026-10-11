# Lượt "người B" 11/10/2026 — chạy độc lập theo README

**Ai:** một agent AI mới (không phải người), không biết dự án, chỉ được đọc README của repo công khai và dùng một terminal có ghi biên bản (`terminal.jsonl`, 13 lệnh). Không được hỏi tác giả, không được sửa mã nguồn.

**Máy:** VPS Hetzner mới, Ubuntu 26.04, 2 vCPU, 3,8 GB RAM, ổ 38 GB; chưa có Docker và make. Repo ở commit `3f2a610`.

**Phạm vi:** lượt này cần Internet (cài Docker, `git clone`, tải image). Nó kiểm "máy sạch + README" của W3-01, **không** phải bài cài air gap.

**Kết luận của người B: DONE_WITH_INTERVENTIONS**, kèm một lỗi:

| Bước | Kết quả |
|---|---|
| Cài Docker + make (README khi đó không ghi lệnh) | 16 giây |
| `git clone` (README khi đó không ghi) | khoảng 5 giây |
| `make start` | exit 0, cả hai container Healthy, khoảng 1 phút 57 giây gồm tải image Triton |
| `make smoke` | `SMOKE PASS  18/18` |
| `make test` | **exit 2**, `MVP tests: FAIL  72/73 passed`, lặp lại 2 lần. Không test nào hỏng; nguyên nhân: image không chứa `docs/` nên bước kiểm `docs/API.md` khớp spec báo sai |

**3 can thiệp ngoài README:** lệnh cài Docker/make, lệnh `git clone`, `cd mvp` trước khi `make start`.

**Chỗ README sai hoặc thiếu mà người B ghi nhận:** không có bước cài đặt và lấy mã nguồn; không ghi thư mục chạy; không ghi kết quả mong đợi của `make start`/`make test`; số liệu cũ (smoke 16/16, test 64/65) lệch với bản hiện tại (18/18, 72/73); phiên bản hợp đồng ghi hai giá trị (1.1.0 và 1.2.0); không ghi RAM/CPU tối thiểu.

**Sau lượt này (cùng ngày):** Dockerfile thêm `COPY docs docs`; `run_tests.py` in rõ bước nào FAIL; Quick start trong README viết lại có lệnh cài, lệnh clone, thư mục chạy, kết quả mong đợi và cấu hình tối thiểu. Bản README đã sửa **chưa** được một lượt độc lập khác chạy lại.

Cuối lượt: ổ còn 15 GB trống, RAM còn 3,1 GB available.
