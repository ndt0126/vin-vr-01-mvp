# Phiếu design review — W2-06 UI/UX trạm QC

Trạng thái: **CHƯA ĐIỀN. Buổi review chưa diễn ra.** Không ghi kết quả vào đây trước khi có buổi review thật.

| Mục | Nội dung |
|---|---|
| Ngày, giờ | |
| Người tham gia (tên, vai trò) | |
| Bản được review | `prototype.html` + `W2-06-UI-UX.md` draft-1 (10/10/2026) |
| Người ghi biên bản | |

## Kịch bản đi qua trong buổi review (khoảng 30 phút)

1. Operator: gửi ảnh → OK. Gửi ảnh → NG. Gửi ảnh → REVIEW.
2. Operator: gặp lỗi kỹ thuật → đọc màn hình → kiểm lại.
3. Viewer: tìm một sản phẩm trong Lịch sử → mở truy vết → đọc được model/recipe nào đã chấm.
4. Admin: chuyển recipe → golden lỗi → đọc thông báo. Chuyển lại → thành công. Rollback.
5. Viewer: hệ thống chưa sẵn sàng → mở Sức khỏe → biết phải làm gì.

## Câu hỏi cần quyết

| # | Câu hỏi | Quyết định | Ai quyết |
|---|---|---|---|
| R1 | Chữ "CHƯA CÓ KẾT LUẬN" cho lỗi kỹ thuật có đủ rõ để không nhầm với NG không? | | QC |
| R2 | Sản phẩm lỗi kỹ thuật: operator được tự bấm "Kiểm lại", hay phải có QC xác nhận? | | QC |
| R3 | REVIEW: ai xử lý, có cần màn hình xác nhận kết luận của người xem không? | | QC |
| R4 | Chuyển recipe/rollback trên màn hình cảm ứng tại trạm có được phép không, hay chỉ từ máy quản trị? | | Operations / IT |
| R5 | Admin không gửi được ảnh kiểm tra (theo API hiện tại) có phù hợp không? | | Mentor |
| R6 | Thứ tự ưu tiên các điểm còn thiếu U1–U5 cho Tuần 5 | | Mentor |
| R7 | Ngôn ngữ giao diện (Việt / Anh / cả hai), kích thước màn hình tại trạm | | Operations |
| R8 | Đăng nhập trên màn hình: theo thiết bị hay theo từng người? | | Security / IT |

## Nhận xét theo màn hình

| Màn hình | Nhận xét | Mức (phải sửa / nên sửa / ghi nhận) |
|---|---|---|
| Tổng quan | | |
| Kiểm tra | | |
| Lịch sử | | |
| Recipe và model | | |
| Sức khỏe | | |

## Kết luận

| | |
|---|---|
| Kết quả (chấp nhận / chấp nhận có điều kiện / cần làm lại) | |
| Việc phải làm trước khi code UI (W5-02) | |
| Chữ ký / xác nhận | |
