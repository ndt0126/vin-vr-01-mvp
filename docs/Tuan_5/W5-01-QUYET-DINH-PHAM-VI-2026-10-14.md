# W5-01 — Phạm vi Tuần 5 và các quyết định tạm, 14/10/2026

**Bối cảnh:** chương trình phải chốt toàn bộ trước 16/10/2026. Mentor không liên lạc được trong thời gian này, chưa có buổi demo hay design review nào với stakeholder. Vì vậy mình **tự chốt phạm vi và các mặc định** dưới đây để kịp làm và test trong tuần. Mỗi quyết định đều ghi rõ ai cần xác nhận lại.

**Đây không phải phê duyệt của mentor hay stakeholder.** Tiêu chí của W5-01 ("mentor/stakeholder duyệt phạm vi tuần 5") vẫn **chưa đạt**. Nếu sau này mentor đổi phạm vi thì làm theo mentor.

## 1. Phạm vi đã chốt (tự chốt)

Nguyên tắc chọn theo ghi chú của mentor ở W5-01: *chỉ nhận các mục có thể demo và test trong tuần.*

| ID | Mục | Hạng | Lý do nhận / không nhận | Trạng thái 14/10 |
|---|---|---|---|---|
| B1 | Trạng thái sẵn sàng + lý do, recipe/model kèm digest | Must | Mentor nhấn mạnh trạng thái và traceability (W2-06) | Đã làm, có E2E |
| B2 | Gửi ảnh, OK/NG/REVIEW; lỗi kỹ thuật "CHƯA CÓ KẾT LUẬN"; hủy; kiểm lại | Must | Ghi chú W5-02: operator làm flow chính không cần dòng lệnh | Đã làm, có E2E |
| B3 | Lịch sử + chi tiết truy vết | Must | Ghi chú W5 sheet: mọi kết quả trace được request ID, model, config | Đã làm, có E2E |
| B4 | Chuyển recipe/rollback có lý do, chỉ admin | Must | Thao tác recovery (ghi chú W2-06) | Đã làm, có E2E |
| B5 | Test âm tính theo vai trò | Must | Ghi chú W5-03: không lộ load/unload cho viewer/inference | Đã làm, có E2E |
| B6 | Số đếm trong ngày | Should | Rẻ, dùng ngay dữ liệu ledger | Đã làm, có unit test |
| B7 | Lịch sử chuyển recipe + cảnh báo tự rollback | Should | Rẻ; cảnh báo tự rollback là thông tin vận hành quan trọng | Đã làm, có E2E |
| B8 | Ổ đĩa/VRAM/restart trên UI | Không nhận | Đã có trên Grafana (W4-02); thêm vào UI không đổi được quyết định của operator | — |
| B9 | Xem lại ảnh đã kiểm | Không nhận | Cần quyết định retention ảnh và quyền xem ảnh (chờ QC/IT) | — |
| B10 | Overlay vùng lỗi | Không nhận | Model mẫu chỉ trả điểm | — |
| B11 | Đăng nhập người dùng | Không nhận | Phụ thuộc định danh/PKI nhà máy (câu 6 của mentor) | — |

## 2. Mặc định đang dùng cho 8 câu của phiếu design review W2-06

| # | Câu hỏi | Mặc định mình dùng trong UI | Ai cần xác nhận |
|---|---|---|---|
| R1 | "CHƯA CÓ KẾT LUẬN" có đủ rõ không | Dùng chữ đó, màu xanh tím khác hẳn đỏ NG/xanh OK, kèm câu "không coi là OK hay NG"; test E07 kiểm UI không bao giờ hiện OK/NG cho lỗi kỹ thuật | QC |
| R2 | Operator tự bấm "Kiểm lại"? | Cho phép; lần kiểm lại là request mới có `retry_of` nên truy vết được | QC |
| R3 | REVIEW ai xử lý | UI chỉ hiện REVIEW + "cần người kiểm lại"; chưa có màn xác nhận kết luận của người | QC |
| R4 | Chuyển recipe trên màn trạm? | Chỉ vai trò admin thấy; thao tác đi qua cổng quản trị 9443, có thể chặn bằng mạng nếu IT muốn | Operations / IT |
| R5 | Admin không gửi được ảnh | Giữ như API (chỉ operator gửi ảnh) | Mentor |
| R6 | Thứ tự U1–U5 | U1 (số đếm) và U5 (lịch sử chuyển, tự rollback) đã làm; U2–U4 không nhận (mục 1) | Mentor |
| R7 | Ngôn ngữ, kích thước màn | Tiếng Việt; bố cục chạy được từ 390 px (test E10) tới màn desktop; nút cao ≥ 56 px cho cảm ứng | Operations |
| R8 | Đăng nhập theo thiết bị hay theo người | Theo token của thiết bị/vai trò (bản lab); đăng nhập theo người là backlog | Security / IT |

## 3. Hệ quả cho các việc còn lại của Tuần 5

- **W5-02/W5-03:** làm theo mục 1. Ghi "chờ duyệt" trên hệ thống của trường.
- **W5-04:** UAT gồm (a) bài tự động trên stack thật có GPU, (b) một lượt người B là agent AI cài từ release và chạy test giao diện. **Chưa có UAT với người dùng nội bộ là người**, nên ghi rõ là thiếu.
- **W5-05:** release candidate `0.5.0-rc1` + tài liệu bàn giao `mvp/docs/RELEASE-0.5.0-rc1.md`.
- **Design review W2-06:** chưa có buổi review; phiếu `docs/Tuan_2/W2-06/PHIEU-REVIEW.md` vẫn để trống. Mục 2 ở trên là mặc định của mình, không phải biên bản.
