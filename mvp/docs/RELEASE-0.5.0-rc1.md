# VR-01 MVP 0.5.0-rc1 — release candidate và gói bàn giao (W5-05)

Trạng thái: **release candidate của bản lab**, lập ngày 14/10/2026. Chưa được mentor/QC/IT nghiệm thu. Tên đúng là "release candidate cài thử nghiệm", không phải bản production.

Kết quả phiên chạy trên stack thật cho đúng bản này được ghi ở mục 4 sau khi phiên chạy xong. Chưa có phiên thì mục 4 ghi "chưa chạy".

## 1. Bản này gồm gì

| Thành phần | Phiên bản / định danh | Nguồn |
|---|---|---|
| Mã nguồn | git tag `mvp-0.5.0-rc1` của repo công khai https://github.com/ndt0126/vin-vr-01-mvp | thư mục `mvp/` |
| Image API | `vr01-mvp-api:0.5.0-rc1`, build từ `deploy/Dockerfile` trên máy cài (không phát hành qua registry) | `make start` |
| Python base | `python:3.12-slim@sha256:a6e34c59…edc11b1` | `deploy/.env.sample` |
| Triton | `nvcr.io/nvidia/tritonserver:25.08-py3@sha256:f8365515…f7a5` (Triton 2.60.0) | `deploy/.env.sample` |
| Prometheus / Grafana | `prom/prometheus:v3.5.0@sha256:63805ebb…`, `grafana/grafana:12.1.0@sha256:6ac590e7…` | `deploy/.env.sample` |
| Hợp đồng API | OpenAPI `1.3.0-draft.1` | `backend/openapi.v1.yaml`, `docs/API.md` |
| Model mẫu | `model-a`, `model-b` (hàm tuyến tính), fixture `model-slow`, `model-bad`, `model-heavy*` (mạng tích chập tự sinh, hash ghim) | `packages/`, `tools/make_heavy_fixture.py` |
| Manifests Kubernetes | kustomize base + overlay `lab-cpu`, `lab-gpu`, `offline-cpu`, `offline-gpu`; annotation `vr01.io/release: 0.5.0-rc1` | `deploy/k8s/` |

Image đầy đủ không đi kèm repo. Gói cài offline lớp ứng dụng tạo bằng `deploy/k8s/make_offline_bundle.sh` trên máy có Internet; gói này **chưa ký**.

## 2. Có những gì (theo deliverable)

| Tuần | Deliverable | Ở đâu |
|---|---|---|
| W2 | Use case, kiến trúc, state machine, API, ModelPackage, thiết kế UI | `docs/Tuan_2/` trong repo |
| W3 | Inspection API + lifecycle controller + Triton, test tái tạo | `backend/`, `tests/`, `TEST-REPORT.md` |
| W4 | Metrics/dashboard/cảnh báo, Kubernetes, tải/soak/sự cố, runbook | `docs/OBSERVABILITY.md`, `deploy/k8s/`, `docs/W4-04-REPORT.md`, `docs/RUNBOOK.md` |
| W5-02/03 | Giao diện trạm B1–B7 + API cho UI | `ui/`, README mục "Giao diện trạm", `tests/test_ui.py`, `tests/e2e/` |
| W5-04 | Checklist UAT + kết quả UAT tự động | `docs/Tuan_5/W5-04-UAT-CHECKLIST.md` (repo dự án), `tools/make_uat_result.py`, `evidence/vps-w5-*/UAT-RESULT.md` |
| W5-05 | Tài liệu này | `docs/RELEASE-0.5.0-rc1.md` |

## 3. Cài và kiểm từ artifact (cho reviewer)

Trên một máy Linux amd64 có Internet, làm đúng Quick start trong `README.md` nhưng clone đúng tag:

```bash
git clone --branch mvp-0.5.0-rc1 https://github.com/ndt0126/vin-vr-01-mvp.git && cd vin-vr-01-mvp/mvp
```

Sau đó `make start`, `make smoke` (mong đợi `SMOKE PASS 18/18`), mở `https://<máy>:8443/ui/`. Máy GPU: đặt `TRITON_INSTANCE_KIND=KIND_GPU` và `VR01_GPU=1` trong `deploy/.env` trước `make start`.

Kiểm đầy đủ như phiên của mình: `tools/run_w5_session.sh <user@IP> mvp-0.5.0-rc1` rồi `tools/w5_wait_and_pull.sh` (hai script nằm ở repo dự án, không nằm trong repo công khai), sinh bảng UAT bằng `python3 tools/make_uat_result.py <thư mục evidence>`.

## 4. Kết quả trên stack thật cho bản này

Chưa chạy (điền sau phiên VPS W5).

## 5. Giới hạn đã biết

1. **Không phải production, không phải air gap.** Cài cần Internet; gói offline lớp ứng dụng đã thử (11–12/10) nhưng chưa ký; lớp nền Kubernetes vẫn cài online. Bộ cài air gap r4.x của W1-05 dùng app cũ.
2. **Chưa chạy trên máy đích của nhà máy.** GPU đã chạy là RTX A6000 thuê (lab reference); cấu hình máy đích chờ IT.
3. **Model mẫu không phải model QC.** OK/NG/REVIEW không nói gì về chất lượng sản phẩm; nghiệm thu chất lượng cần dataset gán nhãn và ngưỡng do QC duyệt (câu 7 của mentor).
4. **Bảo mật lab:** token bearer (UI giữ token trong tab trình duyệt), chứng chỉ tự ký 30 ngày, chưa mTLS/PKI, chưa đăng nhập người dùng, chưa thu hồi chứng chỉ offline.
5. **Một node, một worker, SQLite.** Cập nhật trên Kubernetes là `Recreate` (có gián đoạn); hỏng máy là dừng trạm. Sao lưu thủ công, trên cùng ổ.
6. **Người kiểm độc lập là agent AI**, chưa phải kỹ thuật viên người; UAT có người dùng nội bộ chưa diễn ra.
7. Hủy request không giải phóng GPU; xu hướng RAM container Triton trong soak 8 giờ (+7,7 MiB/giờ) chưa kết luận.
8. Ngưỡng cảnh báo, retention, RPO/RTO là đề xuất, chờ Operations/QC/IT.
9. Phạm vi UI B1–B7 là đề xuất của mình, chưa được mentor/stakeholder duyệt (W5-01); chưa thử màn cảm ứng thật.

## 6. Backlog tiếp theo (đề xuất, xếp theo ưu tiên)

Chỉ nên mở rộng sau khi tiêu chí nghiệm thu MVP được đo (ghi chú của mentor ở W5-05).

| # | Việc | Vì sao trước | Phụ thuộc |
|---|---|---|---|
| 1 | Chạy lại bộ kiểm trên máy đích thật + gói offline có ký, lớp nền kubeadm offline | Đích là Linux air gap + NVIDIA; mọi số hiện có là lab | IT duyệt BOM/OS/driver |
| 2 | Model và dataset QC thật, ngưỡng OK/NG/REVIEW do QC duyệt | Hiện chưa có nghiệm thu chất lượng | QC Owner |
| 3 | Định danh người dùng + PKI (mTLS, cấp/thu hồi offline), thay token lab | Yêu cầu bảo mật của mentor (câu 6) | Security/PKI |
| 4 | UAT có người dùng nội bộ + màn cảm ứng thật, sửa UI theo biên bản | W5-04 mới có phần tự động | Lịch UAT |
| 5 | Soak 24 giờ để kết luận RAM Triton; sao lưu ra ổ/máy khác + restore drill | Rủi ro vận hành dài hạn | Operations |
| 6 | Gửi cảnh báo ra kênh vận hành (Alertmanager), ngưỡng do Ops duyệt | Hiện chỉ hiện trên Grafana | Operations |
| 7 | Mở rộng (PostgreSQL, nhiều trạm, nhiều worker, overlay vùng lỗi) | Chỉ khi các mục trên đạt | Kết quả 1–6 |
