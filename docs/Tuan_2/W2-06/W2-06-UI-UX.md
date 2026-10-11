# W2-06 — Thiết kế UI/UX cho trạm QC (cảm ứng + CLI)

Phiên bản: **draft-1, 10/10/2026**. Trạng thái: **BẢN NHÁP, CHƯA CÓ BUỔI DESIGN REVIEW, CHƯA GỬI MENTOR**. Hạn gốc 02/10; nộp trễ.

| File | Vai trò |
|---|---|
| `prototype.html` | Prototype bấm được, một file, mở bằng trình duyệt. Dữ liệu giả, không gọi API |
| `ui-spec.json` | Bản máy đọc được: màn hình, trạng thái, quyền, tác vụ, điểm API còn thiếu |
| `PHIEU-REVIEW.md` | Phiếu cho buổi design review (chưa điền) |
| `check_w2_06.py` | Lệnh kiểm tính nhất quán giữa ba file trên và OpenAPI của MVP |

Căn cứ: quyết định 29/09 (giao diện hỗ trợ **cả cảm ứng và dòng lệnh**, chọn theo tác vụ/quyền), phản hồi mentor câu 7, 9, 10, nhận xét K22 ("UI ưu tiên trạng thái, traceability và thao tác recovery"), W2-01, W2-03 và hợp đồng API `mvp/backend/openapi.v1.yaml`.

## 1. Nguyên tắc

1. **Trạng thái trước tiên.** Mọi màn hình đều cho thấy hệ thống có sẵn sàng không và recipe/model nào đang dùng.
2. **Lỗi kỹ thuật và lần kiểm đã hủy không bao giờ trông giống OK hay NG.** `FAILED`, `TIMEOUT`, `INDETERMINATE` hiện là "CHƯA CÓ KẾT LUẬN"; `CANCELLED` hiện là "ĐÃ HỦY". Cả hai có màu, ký hiệu và chữ riêng, kèm câu "sản phẩm này chưa được kiểm".
3. **Truy vết ngay tại chỗ.** Kết quả nào cũng kèm `request_id`, `product_id`, recipe, model + digest, SHA-256 ảnh và thời gian.
4. **Thao tác nguy hiểm phải xác nhận.** Chuyển recipe và rollback có hộp thoại nêu rõ từ đâu sang đâu, hệ quả, và bắt buộc nhập lý do.
5. **Dùng được bằng ngón tay.** Nút cao tối thiểu 56 px, không cần bàn phím cho luồng chính, không dựa vào hover. Trạng thái không chỉ phân biệt bằng màu (luôn có ký hiệu và chữ).
6. **UI không tự quyết thay hệ thống.** UI không tự chạy lại lần kiểm lỗi; "Kiểm lại" là thao tác của người, tạo `request_id` mới kèm `retry_of`.

## 2. Tác vụ, vai trò và kênh thực hiện

| ID | Tác vụ | Vai trò tối thiểu | Kênh | Màn hình |
|---|---|---|---|---|
| K1 | Xem hệ thống có sẵn sàng không, recipe/model nào đang active | viewer | Cảm ứng | Tổng quan |
| K2 | Gửi ảnh kiểm tra và xem OK/NG/REVIEW | operator | Cảm ứng | Kiểm tra |
| K3 | Kiểm lại sản phẩm bị lỗi kỹ thuật | operator | Cảm ứng | Kiểm tra |
| K9 | Hủy một lần kiểm đang chờ hoặc đang chạy | operator | Cảm ứng | Kiểm tra |
| K4 | Tra lịch sử theo sản phẩm, lọc NG/REVIEW/lỗi kỹ thuật | viewer | Cảm ứng | Lịch sử |
| K5 | Xem truy vết một lần kiểm | viewer | Cảm ứng | Lịch sử |
| K6 | Chuyển recipe/model có xác nhận | admin | Cảm ứng | Recipe và model |
| K7 | Rollback về recipe trước có xác nhận | admin | Cảm ứng | Recipe và model |
| K8 | Xem cảnh báo và hướng xử lý | viewer | Cảm ứng | Sức khỏe |
| C1 | Cài đặt, khởi động, dừng hệ thống | admin | CLI | — |
| C2 | Sao lưu, khôi phục, cập nhật, rollback bản phần mềm | admin | CLI | — |
| C3 | Thêm ModelPackage mới và kiểm package | admin | CLI | — |
| C4 | Đọc log, trace, truy vấn ledger khi debug | admin | CLI | — |
| C5 | Cấp, thu hồi token/chứng chỉ | admin | CLI | — |

Lý do chia: K1–K9 là việc hằng ngày tại trạm, làm bằng cảm ứng. C1–C5 là việc hiếm, cần quyền cao và đã có runbook dòng lệnh (bộ cài r4.x, `make start`), nên giữ ở CLI. Tiêu chí cũ "operator không cần command line" vẫn đúng cho K1–K9.

Lưu ý về quyền theo hợp đồng hiện tại: **admin không gửi ảnh kiểm tra** (403), để tách người đổi model khỏi luồng sản xuất. Vì vậy màn hình Kiểm tra chỉ mở cho operator.

## 3. Màn hình

| Màn hình | Ai mở được | Nội dung chính | API dùng |
|---|---|---|---|
| Tổng quan | viewer, operator, admin | Banner sẵn sàng/chưa sẵn sàng; recipe + model + digest + ngưỡng đang dùng; số đếm trong ca; lần kiểm gần nhất | `getReadiness`, `getActiveRecipe`, `listInspections` |
| Kiểm tra | operator | Chọn ảnh mẫu, mã sản phẩm, gửi; chữ kết quả lớn; thẻ truy vết; nút kiểm lại khi lỗi kỹ thuật; nút hủy khi đang kiểm | `getActiveRecipe`, `submitInspection`, `getInspectionStatus`, `getInspectionResult`, `cancelInspection` |
| Lịch sử | viewer, operator, admin | Lọc Tất cả / NG / REVIEW / Lỗi kỹ thuật; tìm theo mã sản phẩm; chi tiết kèm mọi lần kiểm của sản phẩm | `listInspections`, `getInspectionResult` |
| Recipe và model | admin | Recipe đang dùng, recipe có sẵn, chuyển, rollback, lịch sử thay đổi | `getStation`, `listRecipes`, `activateRecipe`, `rollbackRecipe`, `listAudit` |
| Sức khỏe | viewer, operator, admin | Trạng thái từng thành phần; cảnh báo kèm "cần làm gì" | `getReadiness` |

## 4. Bảng trạng thái màn hình

Mỗi dòng có trong `prototype.html`; chọn ở "Bảng điều khiển demo" cuối trang hoặc đi theo luồng bấm.

| Màn hình | Trạng thái | Khi nào | Người dùng thấy gì / làm được gì |
|---|---|---|---|
| `overview` | `loading` | Đang đọc trạng thái | Vòng chờ |
| `overview` | `ready` | `readyz` 200 | Banner xanh, recipe/model đang dùng, số đếm, nút xem sản phẩm cần xử lý |
| `overview` | `not_ready` | `readyz` 503 | Banner đỏ nêu lý do và câu "sản phẩm lúc này chưa được kiểm" |
| `overview` | `error` | Không gọi được API | Thông báo mất kết nối, nút thử lại; nói rõ kết quả đã lưu không mất |
| `inspect` | `idle` | Chờ thao tác | Chọn ảnh, mã sản phẩm, nút Gửi |
| `inspect` | `sending` | Đang POST | Form khóa, vòng chờ |
| `inspect` | `processing` | Đã nhận 202 | "Đã nhận, đang kiểm" + `request_id`; nói rõ mất mạng vẫn xem lại được |
| `inspect` | `result_ok` | `COMPLETED` + OK | Chữ OK lớn, điểm/ngưỡng, thẻ truy vết |
| `inspect` | `result_ng` | `COMPLETED` + NG | Chữ NG lớn, điểm/ngưỡng, thẻ truy vết |
| `inspect` | `result_review` | `COMPLETED` + REVIEW | Chữ REVIEW, "điểm sát ngưỡng, cần người xem" |
| `inspect` | `technical` | `FAILED` / `TIMEOUT` / `INDETERMINATE` | "CHƯA CÓ KẾT LUẬN", lý do, nút Kiểm lại (mã mới + `retry_of`) hoặc bỏ qua |
| `inspect` | `cancelled` | Operator bấm "Hủy lần kiểm này" khi đang `processing` | "ĐÃ HỦY", "không có kết luận, sản phẩm chưa được kiểm"; nút Kiểm lại. Nếu máy chủ đã xong trước (409 `ALREADY_TERMINAL`) thì hiện kết quả thật |
| `inspect` | `rejected` | 413 / 422 / 409 / 429 trước admission | Nêu mã và cách xử lý; 429 tự gửi lại cùng mã, các mã khác không tự gửi |
| `inspect` | `not_ready` | 503 | Banner đỏ, form khóa |
| `inspect` | `permission` | Không phải operator | Nêu vai trò cần có và những màn hình vẫn xem được |
| `history` | `loading` | Đang đọc | Vòng chờ, bộ lọc vẫn hiện |
| `history` | `list` | Có dữ liệu | Bảng: giờ, sản phẩm, kết quả, điểm, request; dòng kiểm lại ghi "kiểm lại của …" |
| `history` | `empty` | Không có dòng khớp | Thông báo và nút bỏ bộ lọc |
| `history` | `detail` | Chạm một dòng | Kết quả, mọi lần kiểm của sản phẩm, thẻ truy vết |
| `history` | `error` | Không gọi được API | Thông báo, nút thử lại |
| `recipe` | `loading` | Đang đọc | Vòng chờ |
| `recipe` | `view` | Bình thường | Recipe đang dùng, recipe có sẵn, nút Chuyển, nút Rollback, lịch sử thay đổi |
| `recipe` | `confirm_activate` | Bấm Chuyển | Hộp thoại: từ → sang, hệ quả, lý do bắt buộc, Hủy / Chuyển |
| `recipe` | `confirm_rollback` | Bấm Rollback | Hộp thoại: quay về recipe nào, lý do bắt buộc, Hủy / Rollback |
| `recipe` | `switching` | Đang nạp + golden | Vòng chờ; nói rõ hệ thống vẫn nhận ảnh bằng recipe hiện tại |
| `recipe` | `switched` | 200 `changed=true` | Banner xanh kèm kết quả golden và quy tắc tự rollback |
| `recipe` | `golden_failed` | 422 `ACTIVATION_GOLDEN_FAILED` | Banner đỏ "KHÔNG chuyển, recipe cũ vẫn đang dùng" |
| `recipe` | `busy` | 409 `TRANSITION_BUSY` | Banner vàng, thử lại sau |
| `recipe` | `permission` | Không phải admin | Chỉ xem recipe đang dùng, không có nút thao tác |
| `recipe` | `error` | Không gọi được API | Thông báo, nút thử lại |
| `health` | `loading` | Đang đọc | Vòng chờ |
| `health` | `healthy` | Không có cảnh báo | Banner xanh, bảng thành phần |
| `health` | `alerts` | Có cảnh báo | Mỗi cảnh báo: chuyện gì, từ lúc nào, **cần làm gì** |
| `health` | `error` | Không gọi được API | Thông báo, nút thử lại |

## 5. Điểm API còn thiếu để làm UI thật

Prototype hiển thị một số thông tin mà hợp đồng API hiện chưa cung cấp. Đây là đầu vào cho backlog W5-01.

| ID | UI cần | Hiện tại | Đề xuất làm ở |
|---|---|---|---|
| U1 | Số đếm OK/NG/REVIEW/lỗi kỹ thuật trong ca | Chỉ lọc được theo `state` và `product_id`; chưa lọc theo `decision` hay khoảng thời gian | W4-01 (metrics) / W5-03 |
| U2 | Dung lượng ổ, VRAM, số lần restart | `readyz` chỉ trả `ready` + `reasons` | W4-01 |
| U3 | Xem lại ảnh đã kiểm và overlay vùng lỗi | Ảnh gốc đã lưu nhưng chưa có API đọc ảnh; model mẫu chỉ trả điểm, không có bản đồ bất thường | W5-02 / W5-03 |
| U4 | Đăng nhập người dùng trên màn hình | Bearer token lab theo thiết bị; chưa có đăng nhập/đăng xuất, chưa PKI | W5-03 |
| U5 | viewer xem ai chuyển recipe, lúc nào; cảnh báo "đã tự rollback" | `listAudit` chỉ cho admin | W5-03 |

## 6. Tiêu chí nghiệm thu MVP (đề xuất)

Áp cho UI thật ở W5-02, đo bằng test E2E và buổi thử với người dùng:

1. Operator hoàn thành K2 (gửi ảnh → thấy kết quả) không cần bàn phím ngoài, không cần command line.
2. Cả 34 cặp màn hình/trạng thái ở mục 4 đều có trong UI thật và có test.
3. Trong mọi trạng thái lỗi kỹ thuật, UI không hiển thị chữ hoặc màu của OK/NG.
4. Từ một `request_id` hoặc `product_id`, viewer tới được thẻ truy vết đầy đủ trong tối đa 3 lần chạm.
5. Chuyển recipe và rollback không thực hiện được nếu chưa qua hộp thoại xác nhận và chưa nhập lý do; viewer/operator không thấy nút thao tác.
6. Khi mất kết nối, UI nói rõ và không hiển thị dữ liệu cũ như dữ liệu mới.
7. Vùng chạm tối thiểu 48 × 48 px; trạng thái phân biệt được khi in đen trắng.

Ngưỡng cụ thể (số lần chạm, thời gian phản hồi) là đề xuất, chờ buổi review chốt.

## 7. Design review

**Chưa tổ chức.** `PHIEU-REVIEW.md` là phiếu chuẩn bị sẵn; biên bản và quyết định sẽ được ghi sau buổi review thật. Người cần mời: mentor, một người đại diện QC (dùng màn hình hằng ngày), một người vận hành/IT (dùng CLI).

## 8. Cách kiểm

```bash
python3 -I check_w2_06.py --output reviewer-result.json
```

Lệnh kiểm tĩnh: prototype có đủ mọi cặp màn hình/trạng thái trong `ui-spec.json`; bảng ở mục 2, 4, 5 khớp JSON; API mà mỗi màn hình dùng có trong OpenAPI và đúng quyền; prototype không gọi mạng. Mở prototype:

```bash
open prototype.html
```

## 9. Giới hạn

- Đây là thiết kế và prototype với dữ liệu giả. **Chưa có UI thật**, chưa có test E2E, chưa thử trên màn hình cảm ứng thật, chưa thử với người dùng QC.
- Prototype đã được mở và duyệt qua 33 trạng thái × 3 vai trò của draft-1 (trạng thái `cancelled` thêm ngày 11/10 mới kiểm bằng lệnh kiểm tĩnh và một lượt mở lại) trên trình duyệt desktop (không lỗi JavaScript, không tràn ngang ở 1024 px). Chưa kiểm bằng công cụ accessibility.
- Số đếm, cảnh báo và overlay trong prototype dựa trên API chưa có (mục 5).
- PASS của lệnh kiểm chỉ là nhất quán tài liệu, không phải kết quả design review.
