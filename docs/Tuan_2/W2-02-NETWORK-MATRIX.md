# W2-02 — Network matrix: port, protocol, trust flow (MVP một node)

Phiên bản: **draft-2, 06/10/2026**. Trạng thái: **CHỜ MENTOR / IT-OT XÁC NHẬN**.

Mỗi dòng trả lời: **ai gọi ai, qua cổng nào, giao thức gì, xác thực bằng gì, có đi qua ranh giới tin cậy không**. IT nhà máy dùng bảng này để mở firewall; cái gì không có trong bảng thì mặc định **chặn**.

Cột **Nguồn số liệu** cho biết port lấy từ đâu:

- **M** = manifest/script đã chạy trên GPU A (`docs/Tuan_1c/release_r4.6/update-w105-v2.yaml`, `docs/Tuan_1c/USB_DIR/app/run_triton_service.sh`).
- **C** = contract W2-04 (`docs/Tuan_2/W2-04/openapi.v1.yaml`, `reference_api.py`), **chưa** deploy lên Kubernetes.
- **K** = mặc định của upstream kubeadm, **chưa đo** trên máy đích. Phải kiểm bằng `ss -ltnp` khi cài W4.

## 1. Vùng tin cậy (trust zone)

| Zone | Gồm | Mức tin |
|---|---|---|
| Z0 — Ngoài nhà máy | Nơi build gói, Internet | Không tin. **Không có đường mạng** tới target; chỉ đi qua USB/media theo quy trình |
| Z1 — Mạng trạm | Camera/replay tool, QC UI, MES/PLC simulator | Tin có điều kiện: phải có TLS + token đúng vai trò |
| Z2 — Mạng quản trị | Máy admin (CLI/UI quản trị, SSH) | Tin cao hơn, nhưng vẫn qua TLS + token admin hoặc SSH key |
| Z3 — Trong node | Host OS, kubelet, API server, etcd | Chỉ admin có root |
| Z4 — Trong pod ứng dụng | Gateway, API/lifecycle, Triton | Traffic giữa container đi qua `127.0.0.1` của pod, không ra card mạng |

## 2. Bảng luồng

| # | Nguồn → Đích | Port / proto | Xác thực | Zone | Nguồn số liệu | Ghi chú |
|---|---|---|---|---|---|---|
| N1 | Image source → Gateway inference | **8443/TCP**, HTTPS (TLS ≥1.2, lab kiểm 1.3) | Bearer token vai trò `operator` | Z1→Z4 | M (8443), C | Submit ảnh, đọc status/result |
| N2 | QC UI → Gateway inference | 8443/TCP HTTPS | Token `viewer` (đọc) / `operator` | Z1→Z4 | M, C | UI tĩnh phục vụ offline, không CDN |
| N3 | MES/PLC simulator → Gateway inference | 8443/TCP HTTPS | Token `viewer` | Z1→Z4 | C | Pull theo `request_id` (W2-01 Q4 còn mở: pull hay push) |
| N4 | Admin → Gateway management | **9443/TCP** HTTPS | Token `admin` | Z2→Z4 | **C — chưa có trong manifest lab** | Package/validate/activate/rollback/audit. Chỉ mở cho mạng quản trị |
| N5 | Gateway → API/controller | 8092/TCP HTTP, `127.0.0.1` | Không (cùng pod) | Z4 | M (`--upstream-port 8092`) | Không ra ngoài pod |
| N6 | API/adapter → Triton HTTP | 8100/TCP HTTP KServe v2, `127.0.0.1` | Không (cùng pod) | Z4 | M (`--http-port=8100`) | Chỉ adapter biết URL này |
| N7 | Triton gRPC / metrics | 8101, 8102/TCP | — | Z4 | M | **MVP không dùng.** NetworkPolicy chặn từ ngoài pod. Đề xuất W3: tắt hẳn (`--allow-grpc=false`, `--allow-metrics=false`) hoặc giữ chỉ cho debug |
| N8 | Service `vr01-https` (ClusterIP) | 443 → targetPort 8443 | — | Z3→Z4 | M | Chỉ nội bộ cluster; lab truy cập qua `kubectl port-forward` tới `127.0.0.1:18443` |
| N9 | Admin → SSH host | 22/TCP | SSH key, không mật khẩu | Z2→Z3 | Lab | Chỉ cho debug/cài đặt; user thường không cần shell (W2-02 D04) |
| N10 | kubectl/kubelet → kube-apiserver | 6443/TCP TLS | Client cert kubeadm | Z3 | K | Chỉ trong node; **không** mở cho Z1 |
| N11 | apiserver → kubelet | 10250/TCP TLS | Cert | Z3 | K | Chỉ trong node |
| N12 | etcd | 2379–2380/TCP | Cert | Z3 | K | Chỉ `127.0.0.1`/IP node |
| N13 | scheduler / controller-manager | 10259, 10257/TCP | — | Z3 | K | Mặc định bind localhost |
| N14 | Calico (CNI v3.32.2) | BGP 179, VXLAN 4789/UDP… | — | Z3 | M (phiên bản), K (port) | **Một node nên không có traffic CNI giữa các node.** Chỉ cần nếu thêm node — ngoài MVP |
| N15 | Pod ứng dụng → bất kỳ đâu | Egress | — | Z4→* | M (`egress: []`) | **Chặn hết.** Model/package đọc từ hostPath, không tải gì qua mạng |
| N16 | Node → Internet | Mọi port | — | Z3→Z0 | M (`egress_guard_persist.sh`) | Chặn kết nối mới ra WAN, giữ qua reboot (r3: probe `1.1.1.1:80` bị chặn) |
| N17 | Gói cài đặt/model → node | USB/media, không phải mạng | Chữ ký + SHA-256 trên trust store | Z0→Z3 | M (release r4.x) | Vào quarantine/staging trước, kiểm xong mới lên kho đã duyệt |
| N18 | Backup → đích ngoài máy | **Chưa chốt** (SMB/NFS/SSH tới NAS, hoặc ổ rời) | Do IT chọn | Z3→Z2 | — | Xem [W2-02-FAILURE-SIZING-BACKUP.md](W2-02-FAILURE-SIZING-BACKUP.md) mục 4 |

## 3. Đưa 8443/9443 ra mạng trạm — đề xuất cho MVP

Hiện **chưa có** đường nào từ máy khác trong LAN vào gateway: Service là ClusterIP, lab chỉ dùng port-forward. Phương án:

| Phương án | Ưu | Nhược | Đề xuất |
|---|---|---|---|
| `hostPort: 8443/9443` trên pod | Port giống hệt contract; đơn giản | Gắn với node (không sao: chỉ một node) | **Chọn cho MVP** |
| `NodePort` | Chuẩn Kubernetes | Port 30000–32767, khác contract; client phải đổi | Dự phòng |
| Ingress controller | Nhiều host name, TLS tập trung | Thêm image/thành phần vào gói offline | Target |

Kèm theo: firewall host (nftables) chỉ cho **8443 từ subnet trạm**, **9443 + 22 từ subnet quản trị**; mọi port khác trên IP LAN bị chặn. Subnet cụ thể chờ IT/OT (W2-04 A1).

## 4. Việc phải làm để bảng này thành "đã kiểm"

1. Thêm container port 9443 + `hostPort` vào manifest, cập nhật NetworkPolicy cho 9443.
2. Trên máy đích sau khi cài: chạy `ss -ltnp` và `nft list ruleset`, lưu output làm evidence; đối chiếu với từng dòng N1–N16, đổi cột nguồn **K → đo được**.
3. Test âm: từ subnet trạm gọi 9443, 6443, 8100 → phải bị chặn; từ pod ứng dụng `curl` ra ngoài → bị chặn.
