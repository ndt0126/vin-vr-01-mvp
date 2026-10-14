# Tuần 5 (19–23/10/2026) — danh sách việc, lập ngày 11/10

Trạng thái: **danh sách chuẩn bị, chưa làm việc nào, chưa gửi mentor.** Nguồn yêu cầu: sheet `Công việc`, dòng 33–37 (W5-01 → W5-05), hạn chung 23/10.

## 1. Ràng buộc quyết định thứ tự

W5-01 ghi: *"Không bắt đầu code cho mục chưa có acceptance criteria"* và điều kiện đạt là *mentor/stakeholder duyệt phạm vi tuần 5*. Mentor ghi thêm: *"Chỉ nhận các mục có thể demo và test trong tuần."*

Hệ quả: **không viết UI thật trước khi phạm vi được duyệt.** Việc làm trước được là chuẩn bị để buổi chốt phạm vi diễn ra nhanh: bản nháp backlog có tiêu chí nghiệm thu, và kịch bản demo Tuần 3–4.

## 2. Từng việc: làm trước được gì, chờ gì

| Mã | Yêu cầu tóm tắt | Làm trước được (không cần ai duyệt) | Phải chờ |
|---|---|---|---|
| W5-01 | Demo Tuần 3–4, thu vấn đề UI, xếp Must/Should/Could, chốt phạm vi | Kịch bản demo 20 phút trên MVP; bản nháp backlog ở mục 3 kèm ước lượng và tiêu chí nghiệm thu | Buổi demo với stakeholder; mentor duyệt phạm vi |
| W5-02 | UI thật cho các mục được duyệt, có component/E2E test | Chọn cách dựng UI (đề xuất ở mục 4); khung dự án và test E2E rỗng | Phạm vi W5-01; buổi design review W2-06 (chưa diễn ra) |
| W5-03 | Backend cho UI: endpoint/filter, role, audit, giữ tương thích | Liệt kê thay đổi API cho từng mục backlog (mục 3) dưới dạng bổ sung không phá client | Phạm vi W5-01 |
| W5-04 | Demo end-to-end và UAT nội bộ: simulator → backend → UI; test timeout, duplicate, sai input, restart, rollback | Camera/QC simulator (phần lớn đã có: `tests/load_cutover.py`, `tests/smoke.py`); checklist UAT soạn từ các bài đã có | UI của W5-02; lịch UAT với người dùng nội bộ |
| W5-05 | Release candidate, gói bàn giao, known limitations, backlog tiếp theo | Release notes và danh sách giới hạn (đã có rải trong README, runbook); kiểm lại "reviewer triển khai và smoke từ artifact" bằng một lượt người B | Kết quả UAT; quyết định về máy đích và air gap |

## 3. Bản nháp backlog cho W5-01

Xếp hạng là **đề xuất của mình**, chờ mentor và stakeholder quyết. Ước lượng tính theo ngày công của một người.

| ID | Mục | Hạng đề xuất | Ước lượng | Phụ thuộc | Tiêu chí nghiệm thu đề xuất |
|---|---|---|---|---|---|
| B1 | Màn hình trạng thái: sẵn sàng hay không kèm lý do, recipe/model đang chọn kèm digest | Must | 0,5 | API đã có | Dừng Triton → trong 10 giây màn hình báo "chưa sẵn sàng" kèm lý do; bật lại → về "sẵn sàng" |
| B2 | Gửi ảnh thử, hiện OK/NG/REVIEW; lỗi kỹ thuật hiện "chưa có kết luận" | Must | 1 | API đã có | Ảnh hợp lệ ra kết luận; ảnh sai định dạng ra thông báo lỗi; request `FAILED`/`TIMEOUT`/`CANCELLED` không bao giờ hiển thị giống OK hay NG |
| B3 | Lịch sử kiểm tra: lọc theo trạng thái, sản phẩm; xem chi tiết có request_id, model, recipe | Must | 1 | API đã có (lọc `state`, `product_id`) | Từ một dòng lịch sử mở được chi tiết có đủ request_id, phiên bản model và recipe |
| B4 | Chuyển recipe và rollback qua hộp thoại xác nhận có lý do; chỉ admin thấy nút | Must | 1 | API đã có | operator và viewer không thấy nút và bị 403 nếu gọi thẳng; thao tác được ghi audit |
| B5 | UI không gọi management API khi vai trò không được phép; test âm tính theo vai trò | Must | 0,5 | B4 | Bộ test: mỗi vai trò × mỗi endpoint management cho đúng 200/403 |
| B6 | Số đếm OK/NG/REVIEW/lỗi kỹ thuật theo khoảng thời gian (U1) | Should | 1 | Thêm lọc `decision` và khoảng thời gian vào API | Số trên màn hình bằng số đếm trực tiếp từ ledger trong cùng khoảng |
| B7 | viewer xem ai chuyển recipe lúc nào; cảnh báo "đã tự rollback" (U5) | Should | 0,5 | Endpoint đọc lịch sử chuyển recipe cho viewer (không lộ phần audit khác) | Sau một lần tự rollback, màn hình hiện cảnh báo và mục lịch sử tương ứng |
| B8 | Dung lượng ổ, VRAM, số lần restart trên màn hình (U2) | Should | 0,5 | Metrics đã có; cần endpoint tóm tắt cho UI | Ổ gần đầy thì màn hình cảnh báo trước khi API trả 503 |
| B9 | Xem lại ảnh đã kiểm (U3, phần ảnh) | Could | 1 | API đọc ảnh theo request_id, có phân quyền | Mở lại đúng ảnh của request; SHA-256 khớp ledger |
| B10 | Overlay vùng lỗi (U3, phần overlay) | Ngoài phạm vi | — | Cần model trả bản đồ bất thường; model mẫu chỉ trả điểm | — |
| B11 | Đăng nhập người dùng trên màn hình (U4) | Ngoài phạm vi | — | Cần quyết định về định danh/PKI của nhà máy | — |

Must cộng lại khoảng 4 ngày công, vừa một tuần nếu tính cả test và UAT. Should chỉ nhận khi Must xong trước thứ Tư.

## 4. Quyết định cần mentor trước khi bắt đầu W5-02

1. **Dựng UI bằng gì.** Đề xuất của mình: trang tĩnh HTML + JavaScript thuần do chính API phục vụ, test E2E bằng Playwright. Lý do: không thêm bước build và không thêm image vào gói cài; prototype W2-06 đã là một file HTML. Nếu đội có chuẩn frontend riêng thì mình theo chuẩn đó.
2. **Trình duyệt và thiết bị đích.** Prototype giả định màn cảm ứng tại trạm; cần biết kích thước và trình duyệt.
3. **Token của UI.** UI chạy trong trình duyệt nên token lab nằm ở phía client. Dùng tạm cho MVP có chấp nhận được không, hay cần một lớp phiên đăng nhập (khi đó B11 thành Must)?
4. **Ai dự demo và UAT, vào ngày nào.** W5-01 và W5-04 đều cần người ngoài mình.
5. **Buổi design review W2-06** chưa diễn ra; 8 câu trong phiếu review ảnh hưởng trực tiếp tới B2 và B4.

## 5. Việc tồn từ các tuần trước ảnh hưởng tới W5-05

- Chưa chạy trên máy đích của nhà máy (cấu hình chưa được IT duyệt); chưa air gap đầy đủ cho MVP (lớp nền Kubernetes vẫn cài online, gói offline chưa ký).
- "Reviewer triển khai và smoke từ artifact bàn giao": mới có agent AI làm, chưa có người.
- W2-01 còn 6 câu hỏi cho QC/integration chưa được trả lời; retention ở W2-03 chờ QC/IT chốt.
