# W5-01 — Kịch bản demo kết quả Tuần 3–4 (khoảng 20 phút)

Trạng thái: **nháp ngày 11/10/2026, chưa diễn tập, chưa có lịch.** Người xem: mentor và stakeholder (QC, vận hành). Mục đích của buổi: cho thấy MVP làm được gì, rồi thu vấn đề UI/tính năng còn thiếu để chốt phạm vi Tuần 5.

## Chuẩn bị (trước buổi, khoảng 15 phút)

- Một máy Linux amd64 có Docker và Internet (VPS 4 vCPU là đủ; demo chạy model trên CPU). Không cần GPU: phần GPU trình bày bằng báo cáo.
- `git clone` repo công khai, `cd mvp`, `make start SLOW=1`, `make obs-start`, `make smoke` (phải ra 18/18).
- Grafana chỉ nghe ở `127.0.0.1:3000` trên máy demo; nếu demo từ laptop thì mở SSH tunnel tới cổng đó.
- Mở sẵn 3 cửa sổ: terminal, Grafana, prototype UI `docs/Tuan_2/W2-06/prototype.html`.
- Nói ngay từ đầu: model là hàm mẫu, không phải model QC; OK/NG trong demo không nói gì về chất lượng sản phẩm.

## Trình tự

| Phút | Cho xem | Lệnh / màn hình | Điều người xem cần thấy |
|---|---|---|---|
| 0–2 | Hệ thống gồm gì | Mục "Cấu trúc" trong `mvp/README.md` | Hai cổng (kiểm tra / quản trị), ledger, Triton nằm sau API |
| 2–5 | Một lượt kiểm trọn vẹn | `make smoke`, rồi `python3 tools/vr01ctl.py result <request_id>` | Kết quả có request_id, sản phẩm, SHA-256 của ảnh, recipe và model kèm digest |
| 5–8 | Truy vết | `make trace ID=<request_id>` | Từ một mã ra toàn bộ đường đi: nhận → chờ → suy luận → kết thúc |
| 8–11 | Chuyển model khi đang chạy | `make load` ở một cửa sổ; cửa sổ kia `python3 tools/vr01ctl.py activate recipe-b --reason "demo"` rồi `... rollback --reason "demo"` | Tải không dừng; báo cáo cuối: 0 thiếu, 0 trùng, 0 sai model; `vr01ctl history` ghi ai chuyển, lúc nào, vì sao |
| 11–14 | Sự cố | `docker kill vr01-mvp-triton-1`, xem `vr01ctl status` và Grafana; rồi `docker start vr01-mvp-triton-1` | Hệ thống báo "chưa sẵn sàng" kèm lý do, cảnh báo bật; bật lại thì tự nạp model và sẵn sàng. `vr01ctl pending` liệt kê lần kiểm chưa có kết luận |
| 14–16 | Kết quả GPU và Kubernetes | `mvp/docs/W4-04-REPORT.md` (bảng quét tải, bảng sự cố), `mvp/deploy/k8s/README.md` | Số đo đến từ đâu và giới hạn của chúng |
| 16–20 | UI dự kiến và thu ý kiến | `prototype.html`: màn trạng thái, gửi ảnh thử, lịch sử, hộp thoại chuyển recipe | Hỏi theo danh sách dưới đây; ghi vào backlog |

Bước 8–11 cần diễn tập trước: `make load` tự chuyển recipe theo chu kỳ, nên phải xem nó có chạy được cùng lúc với lệnh chuyển bằng tay hay không; nếu không thì chỉ dùng `make load`.

## Câu hỏi thu ý kiến (ghi câu trả lời ngay trong buổi)

1. Trong 5 mục Must của nháp backlog (`W5-DANH-SACH-VIEC-2026-10-11.md`, mục 3), mục nào không cần, mục nào thiếu?
2. Người vận hành cần thấy gì đầu tiên khi nhìn màn hình: trạng thái hệ thống hay kết quả lần kiểm gần nhất?
3. Khi một lần kiểm không có kết luận (lỗi kỹ thuật), người vận hành phải làm gì với sản phẩm đó?
4. Ai được phép chuyển recipe, và có cần người thứ hai xác nhận không?
5. Cần xem lại ảnh đã kiểm không, và giữ bao lâu?

## Điều không demo và vì sao

- Máy đích của nhà máy và air gap: chưa có trên MVP này.
- Soak 8 giờ: trình bày bằng báo cáo và biểu đồ, không chạy trực tiếp.
- UI thật: chưa có; mới là prototype dữ liệu giả.
