# VR-01 MVP trên Kubernetes (W4-03)

Trạng thái 11/10/2026: **manifests đã chạy thử trên một cluster k3s trong Docker với inference server giả (10/10 bước). CHƯA triển khai lên kubeadm, chưa chạy với Triton thật.**

## Thiết kế

| Quyết định | Lý do |
|---|---|
| Kustomize (`kubectl apply -k`), không Helm | `kubectl` có sẵn kustomize, không thêm công cụ vào gói offline. Giá trị theo môi trường nằm ở `overlays/` |
| Một pod: `init` + `triton` + `api` | Khớp kiến trúc MVP của W2-02. Triton nghe trên loopback của pod (`--http-address=127.0.0.1`), không có Service hay hostPort tới cổng 8000, nên chỉ `api` gọi được |
| 1 replica, `strategy: Recreate` | Ledger là SQLite trên hostPath, chỉ một tiến trình được ghi. **Cập nhật phiên bản vì vậy có gián đoạn** (pod cũ dừng rồi pod mới mới lên); đây không phải rolling update không gián đoạn |
| PersistentVolume kiểu hostPath `/var/lib/vr01/run` + PVC, `Retain` | Một node. Dữ liệu sống qua việc xóa pod, xóa namespace và reboot. Dùng PV/PVC thay cho hostPath trực tiếp trong pod vì namespace đặt PodSecurity `baseline` (hostPath trực tiếp bị chặn; lỗi này lộ ra ở lần chạy thử đầu). Sau khi xóa namespace phải `kubectl delete pv vr01-run` rồi apply lại; dữ liệu trên ổ vẫn còn |
| Readiness của `api` = `GET /readyz` | Chỉ 200 khi recipe active đã xác minh digest **và** đúng model đó đang được nạp trên Triton. `startupProbe` cho phép tới 5 phút nạp model |
| NodePort 30443 (inference), 30943 (management) | Đơn giản cho lab một node. Cách mở cổng trên máy nhà máy chưa được IT chốt (W2-02 câu A1) |
| NetworkPolicy | Chỉ cho vào 8443 và 9443; metrics (9090, 8002) chỉ từ namespace có nhãn `vr01.io/monitoring=true`. Cần CNI hỗ trợ NetworkPolicy (Calico) |
| `api` chạy uid 10001, root filesystem chỉ đọc, bỏ hết capability | `init` chạy root chỉ để tạo thư mục trên hostPath rồi trao quyền |
| Token và chứng chỉ TLS do `init` sinh trên hostPath | **Chỉ cho lab.** Bản production phải dùng Secret cấp từ PKI nhà máy (chưa làm) |

`overlays/lab-cpu`: Triton chạy CPU. `overlays/lab-gpu`: thêm `nvidia.com/gpu: 1` và `KIND_GPU` (cần NVIDIA device plugin; chưa chạy thử).

## Triển khai (lab, node có Internet)

Trên một VPS Ubuntu mới, trong thư mục `mvp/`:

```bash
deploy/k8s/lab-kubeadm-cpu.sh
```

```bash
deploy/k8s/load-images.sh 0.1.0
```

```bash
kubectl apply -k deploy/k8s/overlays/lab-cpu && kubectl -n vr01 rollout status deploy/vr01-inspection --timeout=300s
```

```bash
python3 tools/vr01ctl.py --run-dir /var/lib/vr01/run --inference-port 30443 --management-port 30943 status
```

`lab-kubeadm-cpu.sh` dựng kubeadm single-node + containerd + Calico **có dùng Internet**. Nó không phải bộ cài air gap; bộ cài offline đã kiểm của dự án là r4.x (`docs/Tuan_1c`, kubeadm 1.36.5, GPU), và việc đưa MVP này vào bộ đó chưa làm.

## Cập nhật và rollback

| Việc | Lệnh |
|---|---|
| Cập nhật phiên bản app | Nạp image tag mới (`load-images.sh <tag>`), sửa `newTag` và annotation `vr01.io/release` trong overlay, `kubectl apply -k …` |
| Rollback phiên bản app | `kubectl -n vr01 rollout undo deploy/vr01-inspection` |
| Đổi / rollback model | `vr01ctl activate …` / `vr01ctl rollback …` (như bản Compose; xem `docs/RUNBOOK.md`) |
| Xem lịch sử | `kubectl -n vr01 rollout history deploy/vr01-inspection`; `vr01ctl history` |

## Bài kiểm

`deploy/k8s/k8s_check.sh` chạy 10 bước: deploy từ namespace sạch, hai container Ready, `vr01ctl status` và smoke qua NodePort, cổng Triton không vào được từ IP của pod, xóa pod rồi tự phục hồi với đúng recipe active, cập nhật sang revision mới, `rollout undo`, đổi và rollback model, smoke lại. Kết quả ghi vào `k8s-report.txt`.

## Gói offline cho lớp ứng dụng

- `make_offline_bundle.sh <thư mục>`: xuất hai image thành file tar, chép manifests và công cụ, ghi `SHA256SUMS`. Gói **chỉ gồm lớp ứng dụng**; Kubernetes, containerd và driver không nằm trong gói (lớp nền offline của dự án là bộ r4.x).
- `install_offline.sh <gói>`: kiểm hash (và chữ ký nếu có `SHA256SUMS.asc`), nạp image vào containerd, `kubectl apply -k overlays/offline-cpu` (image policy `Never`), chờ sẵn sàng.
- `k8s_offline_check.sh`: tạo gói, **cắt Internet** trên node, xóa image và namespace, cài lại từ gói, chạy smoke bằng công cụ trong gói, kiểm không có lần kéo image nào.

Gói hiện **chưa ký**: private key ký chỉ nằm ở laptop, nên chữ ký phải được tạo ở đó trên file `SHA256SUMS`.

## Đã kiểm và chưa kiểm

- **Kiểm tĩnh (laptop, 11/10):** `kubectl kustomize` render được 4 overlay; `kubeconform -strict` schema 1.34 hợp lệ; `tests/test_k8s_manifests.py` 7 test.
- **Chạy thử (laptop, 11/10):** cluster **k3s v1.34.1 trong Docker** + overlay `local-fake` (inference server giả thay Triton): `k8s_check.sh` đạt 10/10, ba lượt liên tiếp. Log ở `evidence/local-k3s-2026-10-11/`. Lần chạy thử này sửa được hai lỗi: pod bị PodSecurity chặn vì hostPath, và bài kiểm gọi cổng quản trị trước khi Service kịp cập nhật.
- **Chưa kiểm:** kubeadm thật, Triton thật trên Kubernetes, `lab-kubeadm-cpu.sh`, `load-images.sh`, ba script gói offline, overlay GPU, reboot node, thời gian gián đoạn thật khi cập nhật (trên cluster thử mỗi lần tạo lại pod mất 31–40 giây, phần lớn do inference server giả không xử lý tín hiệu dừng).

## Khác gì nếu dùng K3s

Manifests này không phụ thuộc bản phân phối: K3s chạy được với cùng `kubectl apply -k`. Khác biệt nằm ở phần nền: K3s gộp control plane vào một binary và có sẵn cách cài air gap, nên nhẹ và ít bước hơn cho một node; đổi lại nó dùng containerd, CNI (flannel, không có NetworkPolicy nếu không bật thêm) và cách nạp image riêng, khác bộ công cụ kubeadm mà đội vận hành đang dùng. Quyết định tạm của mentor ngày 30/09 vẫn là kubeadm single-node; K3s chỉ hợp lý khi IT nhận làm chủ hỗ trợ và có cùng bộ bằng chứng (cài sạch, GPU, restore, upgrade/rollback).
