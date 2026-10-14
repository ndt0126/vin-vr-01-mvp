# Phiên Tuần 5 trên GPU — 14/10/2026 (W5-02, W5-04, W5-05)

**Máy:** DeployGPU `d7741cfd…` (masscompute us-central-2), RTX A6000 48 GB, Ubuntu 24.04.4, kernel 6.17.0-14, driver 580.126.16, Docker CE 29.2.1, NVIDIA Container Toolkit 1.18.2; 6 vCPU, 31 GB RAM. Có Internet, **không phải air gap**, không phải máy đích của nhà máy. Thuê từ 06:35 UTC, **terminated 07:23 UTC** sau khi kéo về đủ 220/220 file khớp `MANIFEST.sha256`; chi phí provider ghi 0,55 USD.

**Cấu hình:** `make start SLOW=1 HEAVY=gpu`, `TRITON_INSTANCE_KIND=KIND_GPU`, `VR01_GPU=1`; bản app `0.5.0-rc1`. Model thật chạy GPU; fixture `model-slow` chạy CPU (xem lượt 1).

## Trình tự

0. **Người B** (agent AI độc lập, chỉ README, commit `df28aab`): cài không can thiệp, smoke 18/18, giao diện 8 PASS/1 FAIL/1 SKIP do hai chỗ README sai. Biên bản ở `../person-b-2026-10-14-w5/`.
1. **Lượt 1** (commit `f89aafc`, raw ở `run/w5-run1/`): lộ 3 vấn đề, **đều ở fixture/script kiểm, không phải ở API**:
   - `model-slow` trên GPU chỉ mất 91 ms (cần ≥ 300 ms) → P3, P11 và E08 không bắt được trạng thái đang chạy. Đã sửa: fixture chậm luôn chạy CPU (`tools/build_triton_repo.py`, có test).
   - P17 (cắt mạng 10 s): client tải tính lại `captured_at` mỗi lần gửi lại → lần gửi lại có payload khác → server **đúng hợp đồng** trả 409 `IDEMPOTENCY_CONFLICT`; client bỏ cuộc nên đếm 1 "sai" + 1 "trùng". Trace server: request được nhận một lần, COMPLETED/OK. Đã sửa client **và UI** (nút "Gửi lại" của UI có cùng lỗi): giữ nguyên `captured_at` khi gửi lại.
   - Hai lỗi trên được sửa ở commit `abede1b`.
2. **Lượt 2** (commit `abede1b`): start, smoke, e2e 10/10, `phase main` 14/15 (P3 hỏng vì script kiểm không gửi lại khi gặp 503: ngay sau một lần chuyển model, Triton báo chưa sẵn sàng vài ms, API trả 503 có thể thử lại và không tạo bản ghi), `phase w4` 12/12, `make test` 106/112 (6 skip vì image không có onnxruntime), e2e lần 2 10/10, lưu trạng thái → **reboot cả máy** → R1, R2 đạt, e2e sau reboot 10/10.
3. **Chạy lại `phase main`** (commit `5e31175`, chỉ đổi script kiểm: gửi lại cùng body khi 503/429): **15/15 PASS**, 2 lần gửi lại vì 503.

## Kết quả chính (lượt 2 + chạy lại main)

| Nhóm | Kết quả |
|---|---|
| UAT tự động (`UAT-RESULT.md`) | **24/24 dòng đạt** (checklist W5-04 A1–E3 + U1–U4) |
| Giao diện E2E | 10/10 ba lần (trước sự cố, sau toàn bộ bài sự cố/nâng cấp, sau reboot); video + ảnh trong `run/w5/e2e*/` |
| Dừng Triton thật → UI báo chưa sẵn sàng | 2,8 s / 1,3 s / 1,3 s (tiêu chí ≤ 10 s) |
| Chuyển recipe dưới tải (P2) | 601 request, 0 thiếu/sai/trùng, 11/11 lần chuyển, khoảng cách hoàn tất cũ→mới tối đa 0,225 s (chu kỳ gửi 0,1 s) |
| `kill -9` Triton dưới tải (P8) | 501/501 COMPLETED, 0 sai/trùng |
| Triton tắt ~24 s dưới tải (P12) | 599 COMPLETED, 2 bị từ chối không tạo bản ghi, 0 sai/trùng, readyz 503 suốt thời gian tắt |
| Cắt mạng 10 s (P17, lượt 2) | 401/401 COMPLETED, 0 sai/trùng, 6 lỗi gửi được gửi lại cùng mã |
| Reboot cả máy (R1/R2) | stack tự lên, sẵn sàng sau 8,3 s kể từ khi kiểm, recipe và kết quả cũ y nguyên, smoke 18/18 |
| Còn lại | P4/P5 hủy, P6 drain, P7 kill API, P9 backup/restore, P11 timeout, P13 observability, P14 tự rollback, P15 đầy ổ, P16 nâng cấp/quay lại image, P18 model ảnh ONNX: đều PASS |

## Giới hạn

Một lượt, tải thấp, model mẫu (không phải QC); không air gap; máy thuê không phải máy đích; người B và UAT đều là tự động/AI, **chưa có người dùng nội bộ**. Hiện tượng 503 vài ms ngay sau khi chuyển model là hành vi đúng hợp đồng (client gửi lại được, không mất dữ liệu) nhưng vẫn là gián đoạn ngắn; đã ghi thành câu hỏi cho Operations từ 12/10.

**Lỗi bố trí evidence:** script cũ `cp -r` vào thư mục đã có, nên kết quả E2E của lượt 2 nằm ở `run/w5/e2e/e2e/` và `run/w5/e2e-again/e2e/`; thư mục ngoài là bản của lượt 1. Không di chuyển file (để MANIFEST khớp); `tools/make_uat_result.py` chọn bản mới nhất theo thời gian; script đã sửa cho lần sau.
