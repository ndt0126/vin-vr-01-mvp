# W2-04 — Business REST API (Câu hỏi đặt ra #5)

Bản **1.0.0-draft.1, 06/10/2026**. Trạng thái: **đã nộp, chờ mentor/integration review**.

Đọc [W2-04-API-CONTRACT.md](W2-04-API-CONTRACT.md) trước. Hợp đồng máy đọc được nằm ở `openapi.v1.yaml`.

Kiểm toàn bộ bằng một lệnh (Python ≥ 3.11):

```bash
python3 -m pip install -r requirements.txt
python3 -I verify_w2_04.py --output reviewer-result.json --evidence-dir evidence
```

Kết quả PASS chỉ có nghĩa là spec nhất quán và server tham chiếu trong lab đúng hợp đồng. Đây không phải nghiệm thu. Giới hạn xem mục 13 của tài liệu.

`reference_api.py` dùng validator và package mẫu của W2-05 ở `../` (trong repo) hoặc `../W2-05/` (trong gói ZIP), và không sửa các file đó. `demo_walkthrough.py` sinh lại `examples/`.

## Ghi chú 11/10/2026

Thư mục này là **bản draft-1 đã nộp (06/10)** và được giữ nguyên. Hợp đồng hiện hành là `mvp/backend/openapi.v1.yaml` bản **1.2.0-draft.1**, bổ sung so với bản ở đây: `captured_at` trong result, lọc danh sách theo `state`, reason `BACKEND_ID_MISMATCH`, và operation `cancelInspection` với state `CANCELLED`. Server chạy thật là `mvp/backend/inspection_api.py`; `reference_api.py` ở đây chỉ còn dùng làm chuẩn so sánh cho `check_w2_03.py`. Bảng tóm tắt API hiện hành: `mvp/docs/API.md`.
