# W2-02 — Failure domain, sizing, retention và backup (MVP một node)

Phiên bản: **draft-2, 06/10/2026**. Trạng thái: **GIẢ ĐỊNH ĐỂ REVIEW — CHỜ QC / OPERATIONS / IT CHỐT**.

Mọi con số có nhãn:

- **[ĐO]** — có evidence trong repo, ghi nguồn.
- **[GĐ]** — giả định để tính; phải thay bằng số thật của nhà máy. W4-03/W4-05 đo lại.

## 1. Failure domain — hỏng một thứ thì cái gì chết theo

*Failure domain* là phạm vi bị ảnh hưởng khi một thành phần hỏng. MVP chỉ có **một node, một GPU, một ổ dữ liệu**, nên phải nói thẳng: **node, GPU hoặc ổ dữ liệu hỏng thì toàn bộ trạm dừng kiểm tra AI**. Không có HA. Lớp bảo vệ là: phát hiện nhanh, không trả kết quả sai, dữ liệu đã nhận không mất, phục hồi theo runbook.

| # | Sự cố | Ảnh hưởng | Phát hiện | Hệ thống phản ứng (theo W2-01) | Phục hồi | Thời gian |
|---|---|---|---|---|---|---|
| FD1 | Process/container ứng dụng crash | Dừng nhận request tới khi pod chạy lại | Liveness/readiness | Request đang PROCESSING → `INDETERMINATE` khi khởi động lại (F12); không đoán OK/NG | Kubernetes tự restart container | **[ĐO]** 12–30 s trong fault test v2 A6000 (25/09) — không phải SLA |
| FD2 | CUDA OOM khi load/infer/A+B | Request lỗi đó `FAILED`; có thể mất readiness | Readiness 503, log OOM | Admission ≤8, batch 1, giữ dự trữ VRAM 900 MiB; không tự đổi model (F10) | Nhả VRAM, restart worker | **[ĐO]** item 4 r8 PASS 3 ca OOM mỗi topology (04/10), có helper hỗ trợ |
| FD3 | GPU/driver lỗi (Xid, mất GPU) | **Toàn bộ inference dừng** — chỉ có một GPU | Readiness 503 (F8), `nvidia-smi` lỗi | Từ chối request mới 503; dữ liệu cũ vẫn đọc được | Reboot node; nếu phần cứng hỏng → thay GPU | Chưa đo |
| FD4 | Đầy ổ dữ liệu | API không ghi được ledger; kubelet có thể **evict** pod | Cảnh báo dung lượng; lỗi ghi | 503, không trả kết quả chưa lưu bền (F9) | Dọn theo retention; mở rộng ổ | Ngăn bằng ngưỡng mục 3 |
| FD5 | **Hỏng ổ dữ liệu** | Mất ledger, ảnh, package trên máy | I/O error, SMART | Như FD4 | Thay ổ, cài lại theo runbook r4.x, **restore từ backup ngoài máy** | **[GĐ]** ≤60 phút full-node restore (đề xuất, context mục 2 câu 5); mất dữ liệu kể từ lần backup gần nhất |
| FD6 | Mất điện / reboot | Dừng tới khi node lên lại | — | Request đã trả 202 không mất (`synchronous=FULL`) | Tự khởi động, không cần đăng nhập | **[ĐO]** r3 trên GPU A: sau reboot gateway 10/10 PASS. **Lỗ hổng đã biết:** 05/10 model active không giữ qua reboot (W2-01 F13) — W3 phải sửa |
| FD7 | Hỏng OS / kubelet / etcd / chứng chỉ kubeadm | App dừng dù phần cứng ổn | Node NotReady | — | Sửa hoặc cài lại node + restore | Chứng chỉ kubeadm mặc định hạn **1 năm** — cần lịch gia hạn |
| FD8 | Chứng chỉ TLS gateway hết hạn | Client không kết nối được | Client báo lỗi TLS | — | Cấp lại cert (PKI nhà máy, offline) | Cảnh báo trước 30 ngày **[GĐ]** |
| FD9 | Mất mạng trạm | Không gửi ảnh mới được | Client timeout | Kết quả đã có vẫn lưu, đọc lại theo `request_id` (F14) | Sửa mạng | — |
| FD10 | Đồng hồ lệch (air gap, không NTP Internet) | Sai thời gian audit; có thể lỗi hiệu lực TLS | So với nguồn giờ nội bộ | — | Cần nguồn NTP nội bộ nhà máy | **Câu hỏi mở cho IT** |

Kết luận cho mentor: MVP chấp nhận **downtime khi hỏng phần cứng**, nhưng **không chấp nhận** trả nhầm kết quả hoặc mất request đã nhận. Muốn giảm FD5 thì cần quyết định phần cứng (RAID1 cho ổ dữ liệu) — đây là việc của IT, không giải được bằng phần mềm trên một node.

## 2. Sizing tài nguyên

| Tài nguyên | Số hiện có | Nhãn | Ghi chú |
|---|---|---|---|
| GPU | 1 GPU NVIDIA cho 1 pod inference | [ĐO] manifest lab `nvidia.com/gpu: 1` | Lab đã chạy RTX 5060 Ti và A6000 48 GiB; GPU đích chưa chọn |
| VRAM | ≥ VRAM(model A) + VRAM(model B) + workspace batch 1 + **900 MiB** dự trữ | [ĐO] dự trữ 900 MiB từ policy item 4 | A và B cùng load khi switch (D05). Model QC thật chưa có nên VRAM thật **chưa đo** |
| RAM pod ứng dụng | request 8 GiB, limit 24 GiB | [ĐO] manifest `update-w105-v2.yaml` | Đặt cho ResNet lab; đo lại với model thật |
| RAM node | RAM pod + Kubernetes/OS + page cache | [GĐ] ≥ 32 GiB | Đề xuất 64 GiB cũ chưa phải cấu hình đã duyệt |
| Image container | Triton base `25.08-py3`: **6,94 GiB nén** | [ĐO] `docs/Tuan_1c/SIZE-AUDIT.md` | Image app, CNI, control plane: **chưa đo**. Dự trữ [GĐ] 40 GiB cho image store |
| Package model | Hai weights ResNet lab: **~401 MiB** | [ĐO] SIZE-AUDIT | Giữ 3 revision mỗi model để rollback → [GĐ] ~1,2 GiB với model cỡ này |
| Ảnh đầu vào | PCB1: 1.104 ảnh = 296.703.568 byte → **trung bình ~262 KiB/ảnh**; trần 4 MiB | [ĐO] SIZE-AUDIT; trần từ W2-01 | Ảnh camera thật có thể lớn hơn nhiều |
| Một dòng ledger + audit | [GĐ] ~2 KiB/request | GĐ | Đo bằng `ls -l` DB sau test tải W4 |

### Ví dụ tính dung lượng (minh họa, **không phải** số nhà máy)

Giả định [GĐ]: **20.000 ảnh/ngày**, tỉ lệ NG + REVIEW + lỗi kỹ thuật **5%**, ảnh trung bình 262 KiB như PCB1.

| Hạng mục | Công thức | Kết quả |
|---|---|---|
| Ảnh mới mỗi ngày | 20.000 × 262 KiB | ~5,0 GiB/ngày |
| Ảnh OK giữ 7 ngày | 95% × 5,0 × 7 | ~33 GiB |
| Ảnh NG/REVIEW/lỗi giữ 90 ngày | 5% × 5,0 × 90 | ~23 GiB |
| Ledger online 90 ngày | 20.000 × 2 KiB × 90 | ~3,4 GiB |
| Log giới hạn cứng | — | 10 GiB [GĐ] |
| Image + package + staging (2× bundle) | — | ~60 GiB [GĐ] |
| **Tổng dùng** | | **~130 GiB** |
| **Ổ dữ liệu đề xuất** | tổng ÷ 0,7 (giữ ≥30% trống) | **≥ 200 GiB** cho kịch bản này |

Nếu **lưu mọi ảnh 30 ngày ở trần 4 MiB**: 20.000 × 4 MiB × 30 ≈ **2,3 TiB**. Con số này cho thấy retention ảnh là yếu tố quyết định dung lượng ổ, nên cần QC chốt trước khi IT mua ổ.

Ledger giữ 1 năm online sẽ khoảng 14 GiB, **vượt trigger T5 (10 GiB) của ADR D09**. Vì vậy đề xuất: ledger chính giữ 90 ngày; dữ liệu cũ hơn tách ra file archive SQLite read-only theo tháng, vẫn tra được bằng tool offline.

## 3. Retention và ngưỡng dung lượng (đề xuất)

| Loại dữ liệu | Giữ trên máy | Lý do | Chốt bởi |
|---|---|---|---|
| Ledger request/kết quả/lineage | 90 ngày online + archive tháng | Truy vết sản phẩm | QC |
| Audit (login, activate, rollback, export) | ≥ 1 năm (archive) | Yêu cầu audit | Security/IT |
| Ảnh kết luận OK | 7 ngày | Tốn dung lượng nhất, giá trị truy vết thấp | QC |
| Ảnh NG / REVIEW / lỗi kỹ thuật | 90 ngày | Cần cho khiếu nại, huấn luyện lại | QC |
| Log ứng dụng | 14 ngày **và** trần 10 GiB, cái nào tới trước | Debug | Operations |
| Package model | 3 revision gần nhất mỗi model + revision đang active | Rollback (D07) | Mentor |

Ngưỡng ổ dữ liệu: **70%** cảnh báo; **85%** từ chối lưu ảnh OK mới nhưng vẫn ghi ledger; **90%** dừng nhận request (503, F9) trước khi kubelet evict pod (kubelet mặc định evict khi `nodefs.available < 10%`).

Log/ảnh không được chứa token hoặc secret.

## 4. Backup: cái gì, bao lâu, để ở đâu

| Dữ liệu | Cách backup | Tần suất | Ghi chú |
|---|---|---|---|
| SQLite ledger/audit | SQLite online backup API → `integrity_check` → SHA-256 | 15 phút [GĐ] + trước mỗi activate/rollback | Theo ADR D09 |
| Recipe, site config, active revision | Nằm trong ledger + file config có revision | Cùng ledger | |
| Package model | **Không cần backup liên tục**: bất biến, có trên media release (USB đã ký) | Theo release | Chỉ cần backup manifest SHA |
| Chứng chỉ TLS, token | Backup **riêng, mã hóa**, giữ theo quy trình PKI | Khi đổi | Không đặt cùng backup dữ liệu thường, không ghi log |
| Ảnh NG/REVIEW | Copy theo retention | Hằng ngày [GĐ] | Ảnh OK không backup [GĐ] |

**Đích backup — chưa chốt, cần IT chọn một:**

| Phương án | Ưu | Nhược |
|---|---|---|
| NAS/file server nội bộ nhà máy (SMB/NFS/SSH) | Tự động, RPO ngắn | Cần mở thêm luồng N18 trong [network matrix](W2-02-NETWORK-MATRIX.md) |
| Ổ rời luân phiên theo quy trình | Không cần thêm mạng; hợp air gap | Thủ công, RPO dài (ngày) |
| Máy thứ hai trong cùng mạng quản trị | Có thể restore nhanh | Thêm phần cứng |

Nói thẳng về RPO: đề xuất cũ "metadata RPO = 0 sau admission" **chỉ đúng với crash process hoặc mất điện** (nhờ `synchronous=FULL`). Khi **hỏng ổ**, RPO bằng khoảng thời gian giữa hai lần backup, trừ khi ổ dữ liệu có RAID1. Backup đặt **trên cùng ổ** không bảo vệ được FD5.

### Restore drill — điều kiện để backup được tính là "đạt"

1. Lấy backup từ đích ngoài máy, kiểm SHA-256.
2. Trên máy sạch hoặc máy thử: cài theo runbook r4.x → restore DB → khởi động.
3. Kiểm: `integrity_check` OK; số record khớp; tra 5 `request_id` ngẫu nhiên ra đúng state/decision/model digest/recipe revision; active revision đúng; gửi 1 ảnh mới được kết quả.
4. Ghi thời gian từng bước để so với RTO đề xuất (app ≤15 phút, full-node ≤60 phút).

Trạng thái: **chưa có restore drill trên Kubernetes.** Mới có scratch backup/restore trên fixture CPU (Tuần 1b) và backup integrity OK trên GPU A (28/09). Việc này để xác nhận ở W4-05.

## 5. Câu hỏi cần chốt

| # | Câu hỏi | Đầu mối |
|---|---|---|
| S1 | Sản lượng ảnh/ngày, kích thước ảnh camera thật | QC / Integration |
| S2 | Retention ảnh OK / NG / REVIEW và ledger | QC |
| S3 | Đích backup và có RAID1 cho ổ dữ liệu không | IT |
| S4 | Nguồn NTP nội bộ | IT/OT |
| S5 | GPU, RAM, dung lượng ổ của máy đích | IT |
