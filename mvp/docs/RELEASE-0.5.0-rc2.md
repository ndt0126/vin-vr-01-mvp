# VR-01 MVP 0.5.0-rc2 (19/10/2026)

Bản vá nhỏ sau review mentor ngày 16/10/2026. Phần lớn vẫn giống rc1 (`docs/RELEASE-0.5.0-rc1.md`): thành phần, cách cài, 9 giới hạn và backlog 7 mục.
**Không có phiên GPU/VPS mới cho rc2.** Mọi số đo trên GPU vẫn là của phiên 14/10 chạy bản rc1.

## Thay đổi so với rc1

| Mục review | Thay đổi | Kiểm |
|---|---|---|
| STT 17: Python 3.10 | `backend/metrics.py`: bỏ f-string lồng dấu backslash (chỉ hợp lệ từ 3.12). `backend/inspection_api.py`: thêm `parse_rfc3339()` để chuẩn hóa hậu tố `Z` và phần lẻ giây trước `fromisoformat()` (3.10 không đọc được hai dạng này); `_is_datetime` và tham số `since` của `/summary` cùng dùng hàm này | `make test-local` 114/114 trên Python 3.10.0 và 3.12.7 (macOS arm64) |
| STT 17: test flaky | `TestCutoverUnderLoad` không dừng cứng sau 30 lần cutover (~0,9 s) nữa. Test chạy tới khi đủ **cả** ≥30 cutover **và** ≥100 request (trần 15 s), bất biến kiểm tra giữ nguyên | 5/5 lượt đạt khi cả 8 nhân CPU bị chiếm 100% (Python 3.10) |
| STT 18: 503 ngắn sau cutover | `READY_GRACE_S = 2.0`: trong 2 s sau khi `activate()` vừa qua load + golden, readiness không gắn `WARMUP_FAILED` chỉ vì Triton báo "model chưa ready" thoáng qua. Lỗi thật vẫn bị bắt: request FAILED → tự rollback; hết 2 s thì readiness kiểm và tự nạp lại như cũ | 2 test mới: trong grace vẫn 200/202, không nạp lại; hết grace thì tự nạp lại (`lifecycle.model_restored`) |
| Phiên bản | `0.5.0-rc1` → `0.5.0-rc2` trong Compose, `deploy/.env.sample`, overlay Kubernetes và script K8s | `make test` trong container 108/114 (6 bỏ qua vì image không có onnxruntime) |
| STT 16: tag | Tag `mvp-0.5.0-rc2` gồm cả `docs/Tuan_5/` và thư mục evidence `run/` (đã đưa lên ở commit `20ea9b2`/`bfabe6c` ngày 16/10). Tag `mvp-0.5.0-rc1` giữ nguyên, không dời | Xem mục kiểm evidence dưới đây |

## Kiểm evidence trong tag (sha256 so với MANIFEST của từng thư mục)

| Thư mục | Kết quả |
|---|---|
| `vps-2026-10-11T0436Z` | 43/43 |
| `vps-2026-10-11T0452Z-extra` | 10/10 |
| `vps-w4-2026-10-11T0754Z` | 85/85 |
| `vps-gpu-2026-10-11T0905Z` | 156/156 |
| `vps-w5-2026-10-14T0649Z` | 218/220. Hai file không khớp là `run/w5/e2e/e2e/video/E01-1.webm` và `run/w5/e2e-again/e2e/video/E01-1.webm` |

## Che kubeadm token sau tag (19/10, commit trên `main` sau `mvp-0.5.0-rc2`)

- Hai log `vps-gpu-2026-10-11T0905Z/k8s/kubeadm-gpu-install.log` và `vps-w4-2026-10-11T0754Z/k8s/kubeadm-install.log` có dòng `kubeadm join … --token`. Đã che phần bí mật thành `<ID>.<REDACTED>`, giống cách làm ở Item 11.
- Mỗi thư mục có thêm `REDACTIONS.txt` ghi hash gốc (khớp MANIFEST) và hash sau khi che. Vì vậy trên `main`, `vps-gpu` cho 155/156 và `vps-w4` cho 84/85, và file lệch chính là file đã che. MANIFEST gốc giữ nguyên.
- Token đã hết hạn (bootstrap token chỉ sống 24 giờ) và cả hai máy đã bị terminate. Tag `mvp-0.5.0-rc2` vẫn chứa bản chưa che; không viết lại lịch sử git để khỏi làm hỏng các tag đã công bố.

## Chưa kiểm cho rc2

- Bản rc2 chưa chạy với Triton thật, GPU hay Kubernetes. Phần code đổi chỉ chạm readiness sau cutover, cách parse thời gian và metrics, và đều đã có unit test.
- Grace period chưa được đo lại trên GPU (số lần 503 trong soak sẽ giảm tới mức nào). Việc đo đưa vào lần chạy trên máy đích.
