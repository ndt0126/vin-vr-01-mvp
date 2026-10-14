# W5-04 — Checklist UAT nội bộ (nháp)

Trạng thái: **nháp ngày 11/10/2026.** Cột "Đã kiểm tự động ở" cho biết hành vi phía backend đã được kiểm ở đâu; cột "UAT" để trống cho buổi UAT. Phần UI chưa kiểm được vì UI thật chưa có (chờ phạm vi W5-01).

Điều kiện đạt của W5-04: không có kết quả thiếu, trùng, cũ (stale) hay sai phiên bản; lỗi chặn phải đóng hoặc có chấp nhận rủi ro bằng văn bản.

## A. Luồng chính

| # | Kịch bản | Kết quả mong đợi | Đã kiểm tự động ở | UAT (đạt/không, ghi chú) |
|---|---|---|---|---|
| A1 | Simulator gửi một sản phẩm kèm ảnh | Có đúng một kết quả OK/NG/REVIEW, mang đúng mã sản phẩm, SHA-256 ảnh, recipe, model | `tests/smoke.py`; phiên Triton thật P1 | |
| A2 | Gửi nhiều sản phẩm liên tiếp | Số kết quả bằng số đã gửi, không thiếu, không trùng | `tests/load_cutover.py` | |
| A3 | UI hiện kết quả, lịch sử và trạng thái hệ thống | Khớp với `vr01ctl result` và `vr01ctl status` | Chưa có (UI chưa có) | |

## B. Sai lệch đầu vào

| # | Kịch bản | Kết quả mong đợi | Đã kiểm tự động ở | UAT |
|---|---|---|---|---|
| B1 | Ảnh hỏng, sai định dạng, quá lớn | Từ chối 400/413/422 trước khi ghi nhận; không có bản ghi | `tests/test_contract.py` | |
| B2 | Gửi lại cùng request_id, cùng nội dung | Trả lại bản ghi cũ, không chạy lại | `tests/test_contract.py`; smoke | |
| B3 | Cùng request_id, nội dung khác | 409, bản ghi cũ không đổi | `tests/test_contract.py` | |
| B4 | Gửi với recipe cũ ngay sau khi recipe đổi | 409, bên gửi lấy recipe mới và gửi lại cùng mã; không có kết quả sai phiên bản | `tests/load_cutover.py` | |

## C. Thời gian và sự cố

| # | Kịch bản | Kết quả mong đợi | Đã kiểm tự động ở | UAT |
|---|---|---|---|---|
| C1 | Suy luận quá thời gian cho phép | `TIMEOUT`, không có OK/NG; kết quả về muộn bị bỏ | Phiên Triton thật P11 | |
| C2 | Hàng đợi đầy | 429, không treo | `tests/load_sweep.py` | |
| C3 | Restart API khi có request đang chạy và đang chờ | Các request đó thành `INDETERMINATE`; không tự chạy lại; gửi lại bằng mã mới kèm `retry_of` | Phiên Triton thật P7 (CPU, GPU) | |
| C4 | Restart Triton khi có tải | Không sai, không trùng; API tự nạp lại model | Phiên Triton thật P8 (CPU, GPU) | |
| C5 | Reboot cả máy | Recipe đang chọn giữ nguyên, tự sẵn sàng lại | Phiên CPU (Compose và kubeadm) | |
| C6 | Hủy một lần kiểm đang chờ / đang chạy | `CANCELLED`; kết quả về muộn bị bỏ | Phiên Triton thật P4, P5 | |

## D. Chuyển và rollback

| # | Kịch bản | Kết quả mong đợi | Đã kiểm tự động ở | UAT |
|---|---|---|---|---|
| D1 | Chuyển recipe khi đang có tải | Mỗi kết quả ghi đúng model đã ghim lúc nhận | `tests/load_cutover.py`; GPU G3 | |
| D2 | Model mới không qua golden check | Giữ model cũ, báo lý do | `tests/test_mvp.py`; GPU G4, G5 | |
| D3 | Model mới lỗi 3 lần ngay sau khi chuyển | Tự rollback; có ghi audit | Phiên Triton thật P14 | |
| D4 | Rollback thủ công | Về recipe trước; lịch sử ghi người, lúc, lý do | smoke; `vr01ctl rollback` | |

## E. Phân quyền

| # | Kịch bản | Kết quả mong đợi | Đã kiểm tự động ở | UAT |
|---|---|---|---|---|
| E1 | viewer hoặc operator gọi chuyển recipe | 403, có ghi audit | `tests/test_contract.py` | |
| E2 | Không có token hoặc token sai | 401 | `tests/test_contract.py` | |
| E3 | UI của viewer/operator không hiện nút quản trị và không gọi management API | Đúng như mô tả | Chưa có (UI chưa có) | |

## Ghi lỗi trong buổi UAT

| Mã | Kịch bản | Mô tả | Mức (chặn / nặng / nhẹ) | Người ghi | Trạng thái sau sửa |
|---|---|---|---|---|---|
| | | | | | |
