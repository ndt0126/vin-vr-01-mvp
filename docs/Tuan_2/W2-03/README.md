# VIN–VR–01 — W2-03: Data flow và inspection state machine

Ngày tạo: 10/10/2026. Trạng thái: **BẢN NHÁP draft-1, CHƯA GỬI MENTOR** (hạn gốc 02/10, nộp trễ).

## Nội dung

| File | Vai trò |
|---|---|
| `W2-03-DATA-FLOW-STATE-MACHINE.md` | Data-flow diagram, bảng định danh xuyên suốt, bảng chuyển trạng thái T1–T8, quy tắc retry/duplicate/out-of-order/restart, bất biến I1–I8, điểm còn thiếu G1–G5, đề xuất retention |
| `state-machine.json` | Bản máy đọc được của các bảng trên |
| `check_w2_03.py` | Lệnh kiểm cho reviewer |
| `reviewer-result.json` | Kết quả lần chạy 10/10/2026, để đối chiếu |

Thư mục này dùng `../W2-04/reference_api.py` (server tham chiếu), `../W2-01/usecase-pcb1.json` và package/recipe mẫu W2-05 ở `../examples/`. Không file nào trong ba nơi đó bị sửa.

## Cách kiểm

Cần Python 3.10+ (đã chạy trên 3.12) và ba gói trong `../W2-04/requirements.txt`. Không cần GPU, Docker, Internet hay SSH. Chạy trên macOS/Linux, khoảng 10 giây.

```bash
python3 -I check_w2_03.py --output reviewer-result.json
```

## Cách đọc kết quả

`PASS` nghĩa là:

1. Bảng chuyển trạng thái tự nhất quán và Markdown khớp JSON.
2. Cả 8 chuyển trạng thái và 8 bất biến đều **quan sát được** trên server tham chiếu. Riêng phần phục hồi: server chạy như tiến trình riêng, bị `SIGKILL` khi 1 request đang infer và 2 request đang chờ, rồi khởi động lại trên cùng thư mục dữ liệu.
3. Cả 5 điểm còn thiếu G1–G5 đúng là vẫn còn thiếu.

`PASS` **không** có nghĩa là W2-03 đã được chấp nhận, và không nói gì về gateway/controller đang chạy trên Kubernetes (controller đó chưa theo state machine này). Bằng chứng dùng backend stub và inference server giả, chưa có Triton/GPU thật.
