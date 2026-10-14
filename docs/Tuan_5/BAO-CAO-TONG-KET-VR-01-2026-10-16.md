# VIN – VR – 01: Báo cáo tổng kết (21/09 – 16/10/2026)

Trạng thái: **bản gửi mentor, soạn 14/10/2026** (hạn chốt chương trình 16/10). Release: https://github.com/ndt0126/vin-vr-01-mvp/releases/tag/mvp-0.5.0-rc1

## 1. Kết quả trong một đoạn

Mình đã làm một MVP kiểm tra chất lượng bằng AI cho **một trạm, một luồng PCB1, hai model mẫu**. Luồng chạy được: chọn recipe → nhận ảnh + mã sản phẩm → model đúng phiên bản (Triton) → OK/NG/REVIEW → lưu lịch sử và truy vết. Hệ thống có API hai cổng (kiểm tra / quản trị), vòng đời model (nạp → golden → chuyển → drain → gỡ, tự rollback), metrics/dashboard/cảnh báo, manifests Kubernetes, runbook và **giao diện trạm**. MVP đã chạy với Triton thật trên CPU và trên GPU NVIDIA thuê (RTX A6000), cả Docker Compose và kubeadm, có soak 8 giờ. **Chưa** chạy trên máy đích của nhà máy, **chưa** air gap đầy đủ, model mẫu **không phải** model QC, và **chưa có deliverable nào được mentor chấp nhận ngoài W1-01/04/06**.

## 2. Theo từng tuần

| Tuần | Đã có | Bằng chứng chính | Còn thiếu |
|---|---|---|---|
| 1 (21–25/09) | Thử Triton/Seldon CPU, AMD (DirectML), NVIDIA; soak 8 h RTX 5060 Ti PASS cả hai topology; đề xuất vận hành/bảo mật; bộ cài Kubernetes offline r3→r4.6 trên A6000 | `server-runner-v1/reports/`, `server-runner-v2/reports/`, release `w1-05-airgap-r4.x` | Soak A6000 periodic 8 h FAIL (giữ nguyên verdict); W1-02/03/05 "Cần sửa" |
| 2 (28/09–02/10) | Use case PCB1, kiến trúc MVP/target + ADR SQLite, state machine, OpenAPI hai cổng, chuẩn ModelPackage/Recipe, prototype UI | `docs/Tuan_2/`, ZIP item 5/13/14 | Q1–Q6 cho QC chưa trả lời; design review W2-06 chưa diễn ra |
| 3 (05–09/10) | MVP chạy độc lập: API + lifecycle + Triton, hủy request, backup/restore, test tái tạo; người B (agent AI) cài theo README không cần can thiệp | Repo https://github.com/ndt0126/vin-vr-01-mvp, `mvp/evidence/vps-2026-10-11*`, `person-b-*` | Người kiểm độc lập là AI, không phải người |
| 4 (12–16/10) | 30 metric + 10 cảnh báo + dashboard; kubeadm CPU/GPU 10/10; soak GPU 8,03 h: 19.528 request, 0 thiếu/sai/trùng, 95/95 cutover; OOM 3 ca; gói offline lớp ứng dụng; runbook | `mvp/docs/W4-04-REPORT.md`, `mvp/evidence/vps-gpu-2026-10-11T0905Z/` | RAM Triton +7,7 MiB/h chưa kết luận (cần soak 24 h); gói offline chưa ký |
| 5 (dồn vào 14/10) | Giao diện trạm B1–B7, API 1.3.0 cho UI, E2E trình duyệt có video, UAT tự động 24/24 trên GPU, release candidate `mvp-0.5.0-rc1` | `mvp/ui/`, `mvp/tests/e2e/`, `mvp/evidence/vps-w5-2026-10-14T0649Z/`, `mvp/docs/RELEASE-0.5.0-rc1.md`, `docs/Tuan_5/` | Phạm vi tự chốt (mentor không liên lạc được); UAT có người, demo trực tiếp, design review chưa có |

## 3. Kết quả Tuần 5 trên stack thật (14/10, RTX A6000 thuê, Triton KIND_GPU)

| Kiểm | Kết quả |
|---|---|
| Người B (agent AI, chỉ đọc README) cài trên máy GPU sạch | Không can thiệp; smoke 18/18. Lộ 2 lỗi README (số test, fixture của một kịch bản UI); trước lượt đó mình đã tự bắt thêm 2 lỗi README có thể chặn cài (xung đột `docker.io` với Docker CE, thiếu cách cài Node). Đều đã sửa |
| UAT tự động theo checklist W5-04 | **24/24 dòng đạt** — luồng chính, sai đầu vào, timeout, hàng đợi đầy, restart API/Triton, reboot cả máy, hủy, chuyển/rollback/tự rollback, phân quyền, giao diện |
| Giao diện E2E (trình duyệt thật) | 10/10 ba lần: trước sự cố, sau toàn bộ bài sự cố/nâng cấp, sau reboot cả máy. Có video từng kịch bản thay cho buổi demo trực tiếp |
| Trạng thái sẵn sàng trên UI | Dừng Triton thật → UI báo "chưa sẵn sàng" kèm lý do sau 1,3–2,8 s (tiêu chí ≤ 10 s) |
| Không thiếu/trùng/sai phiên bản | Chuyển recipe dưới tải 601 request, kill -9 Triton 501, Triton tắt 24 s, cắt mạng 10 s: 0 sai, 0 trùng |
| Release | `mvp-0.5.0-rc1`; clone sạch từ tag chạy 112/112 test |

**Lỗi tìm được và đã sửa trong phiên** (đều ở fixture/script kiểm và UI, không ở API): (1) fixture model chậm trên GPU chỉ 91 ms nên các bài hủy/timeout không bắt được trạng thái đang chạy → fixture chạy CPU; (2) client tải **và nút "Gửi lại" của UI** tính lại `captured_at` khi gửi lại → server trả 409 đúng hợp đồng → giữ nguyên payload khi gửi lại; (3) script kiểm không gửi lại khi gặp 503 ngắn ngay sau lần chuyển model → gửi lại như client đúng hợp đồng. Chạy lại sau sửa đều đạt.

**Một điểm cần anh/Operations quyết:** ngay sau mỗi lần chuyển model, Triton báo chưa sẵn sàng vài ms và API trả 503 (không tạo bản ghi, client gửi lại được). Không mất dữ liệu, nhưng vẫn là gián đoạn ngắn; mình chưa tối ưu vì cần biết mức chấp nhận.

## 4. Những gì mình KHÔNG khẳng định

- Không khẳng định accuracy OK/NG: model mẫu là hàm tuyến tính/mạng tự sinh, ảnh là VisA public hoặc ảnh tổng hợp.
- Không khẳng định air gap: cài MVP cần Internet; bộ cài offline r4.x (W1-05) dùng app cũ; gói offline của MVP chưa ký, lớp nền kubeadm cài online.
- Không khẳng định downtime 0 ms: khoảng cách hoàn tất cũ→mới đo được ≤ 2,1 s ở tải thấp, bị chặn bởi nhịp gửi.
- "Đã nộp", "100%" hay "PASS" của runner không có nghĩa là mentor đã chấp nhận.

## 5. Những gì chưa làm được trước 16/10 và vì sao

- **Duyệt phạm vi W5, demo, design review, UAT có người:** không liên lạc được mentor/stakeholder trong thời gian còn lại. Mình tự chốt phạm vi và mặc định, ghi rõ ai cần xác nhận (`docs/Tuan_5/W5-01-QUYET-DINH-PHAM-VI-2026-10-14.md`); thay buổi demo bằng video trên Triton thật; người kiểm độc lập là agent AI.
- **Máy đích + air gap cho MVP:** chưa có cấu hình máy đích được IT duyệt.

## 6. Việc bàn giao cho giai đoạn sau

Theo thứ tự ưu tiên trong `mvp/docs/RELEASE-0.5.0-rc1.md` mục 6: máy đích thật + offline có ký → model/dataset QC → PKI/định danh → UAT có người + màn cảm ứng → soak 24 h + backup ra ngoài máy → gửi cảnh báo ra kênh vận hành → mở rộng.

Các quyết định đang chờ người có thẩm quyền: phạm vi W5 (`docs/Tuan_5/W5-01-QUYET-DINH-PHAM-VI-2026-10-14.md`), 8 câu design review, Q1–Q6 cho QC, BOM/OS/driver máy đích (IT), ngưỡng cảnh báo/RPO/RTO (Operations).
