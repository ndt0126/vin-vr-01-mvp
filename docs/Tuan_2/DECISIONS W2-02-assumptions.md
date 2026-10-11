# Decision record — W2-02

Bản nháp 29/09/2026, **sửa 06/10/2026 theo item 14** (review mentor 30/09). Các quyết định là đề xuất để review, chưa có phê duyệt của mentor.

Sửa ngày 06/10:

- Thêm **D09** (trước đây bị thiếu số): metadata store MVP = SQLite, chi tiết ở [ADR D09](ADR-D09-STORAGE-SQLITE-MVP.md).
- **D06** bị thay thế một phần bởi D09. Giữ dòng D06 để truy vết, không xóa, không đánh số lại.
- **D10** sửa cho khớp W2-01: dữ liệu là PCB1 public (VisA, CC BY 4.0) + synthetic, không chỉ "dữ liệu tự tạo".
- Thêm **D13** (tách MVP và target).
- Thêm cột **Trace W2-01**: mỗi quyết định phục vụ mục/tình huống nào trong [W2-01](W2-01/W2-01-USE-CASE-PCB1.md). F1–F16 là bảng normal/failure W2-01 §5.

Quy tắc đánh số: số đã cấp không dùng lại. Quyết định bỏ thì đổi trạng thái thành "rút lại" hoặc "thay thế bởi Dxx".

| ID / trạng thái | Lựa chọn và lý do | Giới hạn / điều kiện xem lại | Trace W2-01 |
|---|---|---|---|
| D01 — đề xuất | Một Linux server air gap + NVIDIA GPU + Kubernetes. Mentor 30/09 tạm chọn upstream kubeadm single-node. | Version/BOM/runtime/CNI production chờ IT duyệt | §1 (1 server + 1 GPU) |
| D02 — đề xuất | Chia UI, business, lifecycle/config, broker, serving, storage và observability theo trách nhiệm. | Ranh giới **logic**. MVP gộp nhiều trách nhiệm vào một pod/process (D13) | §4 happy path |
| D03 — đề xuất | Business API ổn định; chỉ adapter/broker biết API Triton. Triton là ứng viên serving tái sử dụng từ lab. | MVP: adapter là module trong API, không phải service riêng (D13) | §3 quy tắc 2 (pin model/recipe), F16 |
| D04 — đề xuất | UI và CLI dùng cùng API/quyền. CLI dành cho tác vụ phù hợp, đặc biệt debug/analysis. | — | §2 actor/consumer (QC UI) |
| D05 — đề xuất | Một inference pod sở hữu GPU; load A+B cùng lúc khi đủ VRAM. | Item 4 đã đo OOM/coexist trên lab; VRAM model thật chưa đo | F8, F10, F16 |
| D06 — **thay thế một phần bởi D09** (06/10) | ~~Một instance PostgreSQL cho metadata/audit~~ → xem D09. **Còn hiệu lực:** persistent volume riêng cho ảnh/model/log. | PostgreSQL chuyển thành target architecture | F9, F14 |
| D07 — đề xuất | Package bất biến theo SHA manifest; recipe riêng chứa threshold và reference package; site config riêng chứa limits/policy. | Recipe đổi phải có revision mới và audit. Rollback cần khôi phục cả bộ package + recipe/config tương thích | §2 `recipe_version`, F6, F13, F16 |
| D08 — đề xuất | Gói không chứa script thực thi; chỉ khai báo adapter/transforms đã build sẵn trong platform. | Trước khi cho model mới chạy trên máy nhà máy, phải kiểm gói trong môi trường cách ly, quyền và tài nguyên giới hạn | §1 (ModelPackage W2-05) |
| **D09 — đề xuất (mới 06/10)** | Metadata store MVP = **SQLite WAL, `synchronous=FULL`, một writer**, file trên ổ cục bộ. Khớp code đã chạy và evidence lab. | Chuyển PostgreSQL khi gặp trigger T1–T6 trong [ADR D09](ADR-D09-STORAGE-SQLITE-MVP.md); có đường migration | F4, F5, F9, F12, F13, F14; platform gate 3 |
| D10 — giả định có chủ đích (sửa 06/10) | PCB1 từ VisA (public, CC BY 4.0, ghi attribution) + synthetic; model anomaly hoặc stub; camera/QC/PLC/MES simulator. | Đủ review platform/integration; **không** đo accuracy QC, tương thích camera hoặc throughput production | §1 phạm vi |
| D11 — đề xuất | Cài/activate tách bước: validate → stage/warm/golden → đổi revision → drain → unload. | W2-03/04 xác định timeout, request đang chạy khi crash, retry và phục hồi activation | F13, F16 |
| D12 — chờ mentor | Ngưỡng lỗi, tốc độ, thời gian chờ, retention, dung lượng, quyền người dùng và quy trình đưa gói qua air gap. | Giả định tạm cho retention/sizing ở [W2-02-FAILURE-SIZING-BACKUP.md](W2-02-FAILURE-SIZING-BACKUP.md) | §7 Q1–Q6 |
| **D13 — đề xuất (mới 06/10)** | Tách **MVP architecture** và **target architecture**. MVP: một pod gồm gateway TLS + API/lifecycle + adapter + Triton, SQLite, hostPath, health/log. Hoãn: PostgreSQL, broker + mTLS riêng, observability stack, adapter PLC/MES/camera thật, ingress, HA. | Danh sách hoãn và điều kiện đưa lại ở [W2-02-MVP-VA-TARGET.md](W2-02-MVP-VA-TARGET.md) §3 | §1 phạm vi MVP |
