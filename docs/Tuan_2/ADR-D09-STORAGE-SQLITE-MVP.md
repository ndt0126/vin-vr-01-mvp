# ADR D09 — Metadata store cho MVP: giữ SQLite, có điều kiện chuyển PostgreSQL

| | |
|---|---|
| Ngày | 06/10/2026 |
| Trạng thái | **Đề xuất — chờ mentor duyệt** |
| Thay thế | Phần "một instance PostgreSQL cho metadata/audit" của **D06** (29/09). Phần "persistent volume riêng cho ảnh/model/log" của D06 giữ nguyên |
| Liên quan | W2-01 F4, F5, F9, F12, F13, F14 và platform gate 3; W2-03 (state machine); W2-04 (`reference_api.py`); W4-03/W4-05 (xác nhận khi triển khai) |

> ADR (Architecture Decision Record) là một trang ghi lại: bối cảnh → các phương án → quyết định → hệ quả → khi nào phải xem lại. Mục đích là sau này ai hỏi "sao lại chọn thế này" thì có câu trả lời, và quyết định cũ không bị xóa im lặng.

## 1. Bối cảnh — vì sao phải có ADR này

Mentor 30/09 chỉ ra: tài liệu W2-02 (D06) chọn PostgreSQL, nhưng mọi code đã chạy đều dùng SQLite. Giấy và code mâu thuẫn.

Nơi đang dùng SQLite (đã kiểm trong repo 06/10):

| Nơi | File | Ghi chú |
|---|---|---|
| Controller runner v1/v2 | `server-runner-v1/controller.py:24-26` | `ledger.sqlite`, WAL, `synchronous=FULL` |
| Bản Kubernetes trên GPU A (28/09) | hostPath `/var/lib/vr01-w105` trong `docs/Tuan_1c/release_r4.6/update-w105-v2.yaml` | Sau reboot: SQLite backup integrity OK, 2 record COMPLETED |
| Reference API W2-04 | `docs/Tuan_2/W2-04/reference_api.py:282-285` | WAL, `synchronous=FULL`, một lock ghi; tài liệu W2-04 đã ghi "ADR W2-02 còn mở" |

Yêu cầu dữ liệu của MVP (từ W2-01): 1 trạm, 1 ảnh/request, ghi bền request **trước** khi infer, pin model/recipe, idempotency theo `request_id`, mỗi request kết thúc đúng một state terminal kể cả sau restart, lưu active revision qua restart.

## 2. Các phương án

| Tiêu chí | A. SQLite WAL (giữ) | B. PostgreSQL 1 instance trong cluster |
|---|---|---|
| Số writer | Một process ghi; đủ cho 1 trạm, `max_inflight` nhỏ | Nhiều writer, nhiều service |
| Thành phần thêm vào gói air gap | Không (thư viện có sẵn trong Python) | Thêm image Postgres pin digest, StatefulSet/PVC, secret mật khẩu DB, TLS DB, quy trình nâng version |
| Evidence đã có | Đã chạy fault/OOM/reboot/backup trên lab (bảng mục 1; item 3, item 4, GPU A) | **Chưa deploy lần nào** |
| Backup/restore | Sao một file bằng SQLite online backup API; đã làm scratch backup/restore trên fixture CPU (Tuần 1b) | `pg_dump`/base backup; chưa có runbook |
| Phân quyền trong DB | Không có; chỉ quyền file + process | DB role riêng cho API/lifecycle/đọc báo cáo |
| Rủi ro chính | Ghi đồng thời nhiều process → khóa; file đặt trên NFS/mạng → hỏng | Thêm điểm lỗi, thêm việc vận hành mà một trạm chưa cần |

## 3. Quyết định

**Chọn A cho MVP: giữ SQLite**, với các ràng buộc bắt buộc:

1. **Một process ghi duy nhất** (process API + lifecycle). Process khác (audit, báo cáo, backup) chỉ mở **read-only** (`mode=ro`) hoặc dùng online backup API.
2. `journal_mode=WAL` + `synchronous=FULL` (đã có trong `server-runner-v1/controller.py:25-26` và `reference_api.py:284-285`): commit xong là đã xuống đĩa, mất điện không mất request đã trả 202.
3. File DB nằm trên **ổ cục bộ** của node (hostPath/local PV), **không** đặt trên NFS/SMB.
4. Ghi request ở trạng thái RECEIVED **xong mới** trả 202 và mới đưa vào infer (W2-01 F9: storage lỗi → 503, không trả kết quả chưa lưu bền).
5. Backup bằng online backup API ra file mới, kiểm `PRAGMA integrity_check`, tính SHA-256, rồi chuyển ra đích ngoài máy (xem [W2-02-FAILURE-SIZING-BACKUP.md](W2-02-FAILURE-SIZING-BACKUP.md)). **Chỉ tính là đạt khi restore test thành công**, không chỉ có checksum.
6. Truy cập DB chỉ qua một lớp repository trong code (không rải SQL khắp nơi), để migration sau này chỉ đổi một chỗ.

## 4. Khi nào phải chuyển PostgreSQL (trigger xem lại)

Chỉ cần **một** điều kiện đúng là mở lại ADR này:

| # | Trigger | Vì sao SQLite không còn hợp |
|---|---|---|
| T1 | Từ 2 trạm trở lên ghi vào cùng server, hoặc chạy hơn 1 replica API | Nhiều writer tranh khóa |
| T2 | Service thứ hai cần **ghi** metadata (ví dụ tách lifecycle thành deployment riêng) | Như trên |
| T3 | IT/Security yêu cầu phân quyền ở mức DB hoặc audit ở mức DB | SQLite không có role |
| T4 | Đo được p95 ghi ledger > 50 ms, hoặc lỗi `database is locked` trong test tải W4 | Hiệu năng *(ngưỡng đề xuất, chưa đo)* |
| T5 | File DB dự kiến > 10 GiB trong thời gian retention | Backup/restore một file lớn chậm *(ngưỡng đề xuất)* |
| T6 | Cần HA hoặc replication | Ngoài phạm vi MVP |

## 5. Đường migration nếu chuyển

1. Schema viết bằng SQL chuẩn (không dùng kiểu riêng của SQLite); khóa chính `request_id` dạng text; thời gian lưu ISO-8601 UTC.
2. Script `export` (SQLite → CSV/JSON có SHA-256) và `import` (→ PostgreSQL), chạy **offline** trong cửa sổ bảo trì: dừng nhận request → drain → export → import → kiểm → bật lại.
3. Tiêu chí kiểm sau migration: số record mỗi bảng bằng nhau; mọi `request_id` có cùng state/decision/model digest/recipe revision; active revision giống; audit đủ dòng. Lệnh kiểm phải chạy được offline.
4. Giữ file SQLite cũ read-only cho đến khi restore test của PostgreSQL đạt.

## 6. Hệ quả

- Tài liệu W2-02: mọi chỗ ghi PostgreSQL được hiểu là **target**; sơ đồ MVP dùng SQLite.
- D06 chuyển trạng thái "thay thế một phần bởi D09"; không xóa D06.
- W2-03/W2-04 tiếp tục dùng SQLite; không còn ghi "ADR còn mở" khi mentor đã duyệt ADR này.
- Mất khả năng phân quyền theo DB role; bù bằng: chỉ process API mở file ghi, quyền file `0600`, hostPath chỉ pod ứng dụng mount.
- W4-03/W4-05 phải đo lại: kích thước DB thật, thời gian backup/restore, có lỗi lock hay không.
