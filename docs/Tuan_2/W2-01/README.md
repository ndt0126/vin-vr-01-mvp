# VIN–VR–01 — Item 13: Use case W2-01 (PCB1 visual anomaly)

Ngày tạo: 06/10/2026. Trạng thái: **ĐÃ NỘP — CHỜ QC/INTEGRATION XÁC NHẬN**.

## Nội dung

| File | Vai trò |
|---|---|
| `W2-01-USE-CASE-PCB1.md` | Specification: phạm vi, actor/trigger/input/output, happy path (sequence), bảng normal/failure F1–F16, bảng trạng thái, tiêu chí, câu hỏi chờ QC |
| `usecase-pcb1.json` | Bản máy đọc được của các bảng trong spec |
| `check_w2_01.py` | Lệnh kiểm cho reviewer |
| `lab/` | Snapshot controller lab (`server-runner-v2`) cùng unit test, dùng để chạy probe |
| `reviewer-result.json` | Kết quả lúc đóng gói, để đối chiếu |
| `MANIFEST.sha256` | Checksum mọi file trong gói |

## Cách kiểm

Chỉ cần Python 3.10+ (đã chạy trên 3.12), không cần GPU, Docker, Internet hay SSH:

```bash
shasum -a 256 -c MANIFEST.sha256
```

```bash
python3 -I check_w2_01.py --output reviewer-result.json
```

Lệnh thứ hai kiểm 3 điều:

1. Spec tự nhất quán: state terminal không có chuyển tiếp ra ngoài; lỗi kỹ thuật không được mang OK/NG/REVIEW; từ chối trước admission không tạo record; bảng Markdown và JSON khớp nhau.
2. Mỗi nhãn ✅/⚠️/❌ của lab được một probe xác nhận bằng hành vi quan sát được, chạy controller lab với backend giả.
3. 10 unit test của controller lab đều PASS.

## Cách đọc kết quả

`PASS` nghĩa là spec nhất quán và các nhãn trạng thái lab là đúng sự thật. `PASS` **không** có nghĩa là W2-01 đã được chấp nhận, cũng không có nghĩa là hệ thống đã đáp ứng spec. Lab hiện có:

- **10 PASS:** 400, 413, dedup, 409, 429, FAILED, INDETERMINATE sau restart, đọc lại theo ID, 404, pin model khi cutover.
- **2 PARTIAL:** N1 có COMPLETED nhưng chưa có OK/NG/REVIEW; F8 readiness trả 503 nhưng submit chưa bị chặn theo readiness.
- **5 GAP:** F3 (422 ảnh không giải mã được), F6 (sai recipe/sản phẩm), F9 (storage lỗi → 503), F11 (TIMEOUT), F13 (giữ model active qua restart).

Các GAP là việc của W3. Probe chứng minh hành vi hiện tại **khác** spec, để không ai hiểu nhầm là đã làm xong.
