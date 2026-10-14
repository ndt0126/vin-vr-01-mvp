# W5-04 — Kết quả UAT tự động

Sinh bởi `tools/make_uat_result.py` từ raw evidence trong thư mục này. Mã nguồn: `abede1b98496c9ea06c0db074e126bf71cfaadd2 w4-gpu-2026-10-12-7-gabede1b`.

**Phạm vi:** đây là các bài tự động chạy trên stack thật (Triton + API + UI qua trình duyệt headless). Phần "người dùng nội bộ thao tác trên UI" của W5-04 cần một buổi UAT có người; chưa có trong bảng này.

| # | Kịch bản | Kết quả | Bằng chứng (bước=kết quả) |
|---|---|---|---|
| A1 | Simulator gửi một sản phẩm kèm ảnh: đúng một kết quả, đúng sản phẩm/ảnh/recipe/model | ĐẠT (tự động) | P1=PASS; SMOKE=PASS |
| A2 | Gửi nhiều sản phẩm liên tiếp: không thiếu, không trùng | ĐẠT (tự động) | P2=PASS |
| A3 | UI hiện kết quả, lịch sử và trạng thái khớp API | ĐẠT (tự động) | E02=PASS; E04=PASS |
| B1 | Ảnh hỏng/sai định dạng/quá lớn bị từ chối trước khi ghi nhận | ĐẠT (tự động) | TEST=PASS |
| B2 | Gửi lại cùng request_id, cùng nội dung: trả bản ghi cũ | ĐẠT (tự động) | TEST=PASS; SMOKE=PASS |
| B3 | Cùng request_id, nội dung khác: 409 | ĐẠT (tự động) | TEST=PASS |
| B4 | Recipe cũ ngay sau khi đổi: 409, gửi lại đúng recipe, không sai phiên bản | ĐẠT (tự động) | P2=PASS |
| C1 | Suy luận quá thời gian: TIMEOUT, kết quả muộn bị bỏ | ĐẠT (tự động) | P11=PASS; P11b=PASS |
| C2 | Hàng đợi đầy: 429, không treo | ĐẠT (tự động) | TEST=PASS |
| C3 | Restart API khi có request đang chạy/chờ: INDETERMINATE, không tự chạy lại | ĐẠT (tự động) | P7=PASS |
| C4 | Restart Triton khi có tải: không sai/trùng, tự nạp lại model | ĐẠT (tự động) | P8=PASS; P12=PASS |
| C5 | Reboot cả máy: recipe giữ nguyên, tự sẵn sàng | ĐẠT (tự động) | R1=PASS; R2=PASS |
| C6 | Hủy lần kiểm đang chờ/đang chạy: CANCELLED, kết quả muộn bị bỏ | ĐẠT (tự động) | P4=PASS; P5=PASS; E08=PASS |
| D1 | Chuyển recipe khi có tải: mỗi kết quả đúng model đã ghim | ĐẠT (tự động) | P2=PASS; P6=PASS |
| D2 | Model mới không qua golden: giữ model cũ | ĐẠT (tự động) | TEST=PASS |
| D3 | Model mới lỗi 3 lần: tự rollback, có audit; UI cảnh báo | ĐẠT (tự động) | P14=PASS; E07=PASS |
| D4 | Rollback thủ công: lịch sử ghi người, lúc, lý do | ĐẠT (tự động) | E05=PASS |
| E1 | viewer/operator gọi chuyển recipe: 403, có audit | ĐẠT (tự động) | E06=PASS; TEST=PASS |
| E2 | Không token/token sai: 401 | ĐẠT (tự động) | E01=PASS; TEST=PASS |
| E3 | UI viewer/operator không hiện nút quản trị, không gọi management API | ĐẠT (tự động) | E02=PASS; E04=PASS |
| U1 | (bổ sung) UI báo chưa sẵn sàng trong 10 s khi dừng Triton thật | ĐẠT (tự động) | E09=PASS |
| U2 | (bổ sung) UI dùng được ở màn hẹp 390 px | ĐẠT (tự động) | E10=PASS |
| U3 | (bổ sung) UI vẫn đúng sau toàn bộ bài sự cố/nâng cấp | ĐẠT (tự động) | E2E_AGAIN=PASS |
| U4 | (bổ sung) UI vẫn đúng sau reboot cả máy | ĐẠT (tự động) | E2E_REBOOT=PASS |

Mã bằng chứng: P*/R* = `tests/real_session.py` (`run/session-*.json`), E* = `tests/e2e/ui.e2e.mjs` (`run/w5/e2e*/e2e-results.json`, ảnh chụp cùng thư mục), SMOKE = `make smoke`, TEST = `make test` trong container.
