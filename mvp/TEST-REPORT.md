# VR-01 MVP — Test report

File này được **sinh tự động** bằng `tools/make_test_report.py` từ các file trong `evidence/`. Mỗi bảng ghi file nguồn và 16 ký tự đầu SHA-256 của file đó. Chạy lại lệnh sẽ ra cùng nội dung.

## Unit / contract / integration — local-2026-10-10

Nguồn: `evidence/local-2026-10-10/test-report.json` (sha256 7bc787cb144416f8…)

Kết luận: **PASS** · Python 3.12.7 · macOS-26.6-arm64-arm-64bit · 27.4 s · kiểm tĩnh OpenAPI 11/11 · API.md khớp spec: True

| Bộ test | Chạy | Đạt | Lỗi | Bỏ qua |
|---|---|---|---|---|
| `test_contract` | 45 | 45 | 0 | 0 |
| `test_mvp` | 22 | 22 | 0 | 0 |
| `test_models` | 6 | 6 | 0 | 0 |
| `test_observability` | 6 | 6 | 0 | 0 |
| `test_k8s_manifests` | 7 | 7 | 0 | 0 |
| `test_heavy` | 10 | 10 | 0 | 0 |

Backend stub và inference server giả. Không chứng minh Triton/GPU.

## Chuyển recipe dưới tải liên tục — local-2026-10-10

| Nguồn | Kết luận | Tải | Gửi | Có kết quả | Thiếu/sai | Trùng | Cutover đạt | Gap max (s) | 409 gửi lại | p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| `evidence/local-2026-10-10/load-1.json` (sha256 12f89fbfbbd745e8…) | **PASS** | 50.0/s × 20.0 s, chuyển mỗi 1.0 s | 1001 | 1001 | 0 | 0 | 19/19 | 0.027 | 19 | 1.724 |
| `evidence/local-2026-10-10/load-2.json` (sha256 0a2379fc5f73bc41…) | **PASS** | 50.0/s × 20.0 s, chuyển mỗi 1.0 s | 1001 | 1001 | 0 | 0 | 19/19 | 0.038 | 19 | 1.701 |
| `evidence/local-2026-10-10/load-3.json` (sha256 31bfa021bb8760f8…) | **PASS** | 50.0/s × 20.0 s, chuyển mỗi 1.0 s | 1001 | 1001 | 0 | 0 | 19/19 | 0.026 | 19 | 1.804 |

Gap = kết quả cuối của recipe cũ → kết quả đầu của recipe mới. Gap không thể nhỏ hơn chu kỳ gửi, nên đây **không** phải số đo downtime. "409 gửi lại" là request gặp đúng lúc recipe đổi: server chưa tạo record, client lấy recipe mới và gửi lại cùng `request_id`.

## Smoke flow — local-2026-10-10

Nguồn: `evidence/local-2026-10-10/smoke-report.json` (sha256 4c6d111a820fee0b…) (lượt smoke cuối của phiên)

Kết luận: **PASS**, 18/18 bước.

## Smoke flow — vps-2026-10-10

Nguồn: `evidence/vps-2026-10-10/smoke-report.json` (sha256 5842621c5fc1afb2…) (lượt smoke cuối của phiên)

Kết luận: **PASS**, 16/16 bước.

## Kịch bản trên Triton thật — vps-2026-10-10

Nguồn: `evidence/vps-2026-10-10/vps-session.log` (sha256 2919cbdba670af40…)

Môi trường: 29.1.3 · 2.40.3+ds1-0ubuntu1 · Ubuntu 26.04.1 LTS · 7.0.0-30-generic x86_64

| Kịch bản | Dòng kết quả trong log |
|---|---|
| 1 clean start: make down; make start | start exit=0<br>SMOKE PASS  16/16  -> run/smoke-report.json |
| 2 make start again while running (regression of repo bug) | start exit=0<br>SMOKE PASS  16/16  -> run/smoke-report.json |
| 3 restart Triton only (models unloaded in explicit mode) | readyz 200 after 3s<br>active: recipe-b@0.1.0<br>SMOKE PASS  16/16  -> run/smoke-report.json |
| 4 kill -9 API process from host | readyz 200 after 1s restarts=1<br>active: recipe-b@0.1.0<br>SMOKE PASS  16/16  -> run/smoke-report.json |
| 5 make stop; make start | start exit=0<br>active: recipe-b@0.1.0<br>SMOKE PASS  16/16  -> run/smoke-report.json |
| 6 make test | MVP tests: PASS  64/65 passed, static 11/11  -> /tmp/test-report.json |
| 7 digests | TRITON_IMAGE=nvcr.io/nvidia/tritonserver@sha256:f836551575df7c9fb71144073845c6b3911de57db91a8c95e0687a4d2ac9f7a5<br>api image id=sha256:b1530c740478348f5fa5c3208904b0de315b80f35fc7095173186c2bbc471783 |
| triton model events | 13<br>0<br>vr01-mvp-api-1 Up 26 seconds (healthy)<br>vr01-mvp-triton-1 Up 32 seconds (healthy) |
| 8 pinned digests: make down; make start; make smoke |  Container vr01-mvp-api-1  Healthy<br>PASS |

## Phiên kiểm trên Triton thật — vps-2026-10-11T0436Z

Nguồn: `evidence/vps-2026-10-11T0436Z/session-report.json` (sha256 954e40e9691b3b37…) · repo công khai commit `c6922f13151f`

Môi trường: Ubuntu 26.04 LTS · 7.0.0-15-generic x86_64 · 2 · Mem:            3814         682         795           4        2633        3131 · /dev/sda1        38G   22G   15G  60% / · Docker version 29.1.3, build 29.1.3-0ubuntu4.1 · 2.40.3+ds1-0ubuntu1

Kết luận: **PASS**, 13/13 bước.

| Bước | Kết quả | Số liệu ghi nhận |
|---|---|---|
| P1 smoke flow | PASS | {} |
| P2 cutover A<->B under continuous load | PASS | {"sent": 601, "missing_or_wrong": 0, "duplicates": 0, "cutovers": "11/11", "max_gap_s": 0.114, "p95_ms": 5.426} |
| P0 calibrate slow fixture for this machine | PASS | {"first_measure_ms": 840.3, "rounds": 64} |
| P3 slow fixture model runs on the inference server | PASS | {"inference_ms": 831.733, "score": 0.156863, "decision": "OK"} |
| P4 cancel while PROCESSING: late result discarded | PASS | {"cancel_http": 200, "state": "CANCELLED", "discarded_logged": true, "next_request": "COMPLETED"} |
| P5 cancel while queued: never sent to the inference server | PASS | {"cancel_http": 200, "finals": ["COMPLETED", "COMPLETED", "CANCELLED"], "inference_started_for_cancelled": false} |
| P6 cutover drains the in-flight request before unloading the old model | PASS | {"in_flight_final": "COMPLETED", "in_flight_model": "model-slow", "new_recipe_request": "COMPLETED", "old_model_unloaded_after_request_finished": true} |
| P7 kill -9 API with 1 running + 2 queued | PASS | {"before_kill": ["PROCESSING", "RECEIVED", "RECEIVED"], "after_restart": ["INDETERMINATE", "INDETERMINATE", "INDETERMINATE"], "ready_again_s": 1.5, "active_recipe": "recipe-slow@0.1.0", "retry_with_new_id": "COMPLETED"} |
| P8 kill -9 Triton under load: no wrong/duplicate result, service recovers | PASS | {"sent": 501, "completed": 501, "technical": {}, "not_accepted": 0, "wrong": 0, "duplicates": 0, "cutovers": "6/6", "ready_after_load_s": 0.0, "active_recipe": "recipe-a@0.1.0", "seconds_from_kill_to_end": 39.6} |
| P9 ledger backup -> simulated data loss -> restore | PASS | {"backup_integrity": "ok", "backup_rows": 1119, "backup_seconds": 0.01, "backup_sha256": "b88f3a44ba1aba88", "lookup_after_loss_http": 404, "result_identical_after_restore": true, "active_recipe_restored": true, "restore_rto_s_lab": 24.6} |
| P10 state saved for reboot; docker starts on boot | PASS | {"docker_service": "enabled", "active_recipe": "recipe-a@0.1.0"} |
| R1 after full machine reboot: stack back by itself, active recipe and old result intact | PASS | {"machine_uptime_s": 21.91, "waited_for_ready_s": 0.0, "active_recipe": "recipe-a@0.1.0", "result_identical": true} |
| R2 smoke flow after reboot | PASS | {} |

## Phiên kiểm trên Triton thật — vps-2026-10-11T0452Z-extra

Nguồn: `evidence/vps-2026-10-11T0452Z-extra/session-extra-report.json` (sha256 307d0337ec6d8ce5…) · repo công khai commit `9c8071a8fadf`

Môi trường: 

Kết luận: **PASS**, 4/4 bước.

| Bước | Kết quả | Số liệu ghi nhận |
|---|---|---|
| P9 make backup -> simulated data loss -> make restore (ledger + trace + images) | PASS | {"backup": {"backup": "/root/vin-vr-01-mvp/mvp/run/backup/backup-20261011T045148Z", "integrity_check": "ok", "inspections": 1124, "files": 258, "images": 256, "has_trace": true, "seconds": 0.05}, "lookup_after_loss_http": 404, "result_identical_after_restore": true, "active_recipe_restored": true, "trace_events_for_probe_before_ |
| P11 execution timeout on the real inference server; late result ignored | PASS | {"state": "TIMEOUT", "reason": "EXECUTION_TIMEOUT", "late_result_logged": true, "unchanged_after_late_result": true, "readyz": 200} |
| P11b normal limits restored: slow request completes again | PASS | {"state": "COMPLETED"} |
| P12 inference server down ~30 s under load: clean refusals, no wrong result, recovery | PASS | {"sent": 601, "completed": 597, "technical": {}, "not_accepted": 4, "wrong": 0, "duplicates": 0, "client_503": 217, "readyz_during_outage": [503, 503, 503, 503, 503, 503], "outage_s": 24.3, "ready_after_start_s": 0.0, "request_after_recovery": "COMPLETED", "active_recipe": "recipe-a@0.1.0"} |

## Phiên Tuần 4 trên Triton thật — vps-gpu-2026-10-11T0905Z / compose/session-gpu-report.json

Nguồn: `evidence/vps-gpu-2026-10-11T0905Z/compose/session-gpu-report.json` (sha256 4d4c7096a396ba99…)

Môi trường: Ubuntu 24.04.4 LTS · 6.17.0-14-generic x86_64 · 6 · Mem:           32139        1010       30317           5        1190       31128 · /dev/sda2       251G  9.9G  231G   5% / · NVIDIA RTX A6000, 49140 MiB, 580.126.16 · Docker version 29.2.1, build a5c7197 · NVIDIA Container Toolkit CLI version 1.18.

Kết luận: **PASS**, 16/16 bước.

| Bước | Kết quả | Số liệu ghi nhận |
|---|---|---|
| P1 smoke flow | PASS | {} |
| G1 the heavy model executes on the GPU (no silent CPU fallback) | PASS | {"gpu": {"name": "NVIDIA RTX A6000", "used_mib": 942.0, "total_mib": 49140.0, "driver": "580.126.16"}, "vram_before_mib": 400.0, "config_instance_kind": "KIND_GPU", "compute_apps": ["tritonserver, 932 MiB"], "triton_gpu_mem_used_bytes": [418381824.0], "triton_success_counter": ["nv_inference_request_success{gpu_uuid=\"GPU-74db33 |
| G2 calibrate heavy model on this GPU | PASS | {"preset_gpu_ms": [89.153, 88.194, 88.199, 88.493, 88.645], "preset_gpu_xl_ms": [664.425, 589.325, 589.444, 589.56, 590.864], "chosen": "gpu-xl", "median_inference_ms": 589.56, "vram": {"name": "NVIDIA RTX A6000", "used_mib": 4622.0, "total_mib": 49140.0, "driver": "580.126.16"}} |
| P18 real image model (triton-onnx-v1): golden on the inference server, score depends on the image | PASS | {"golden": {"expected": 0.479788, "actual": 0.47975558042526245, "passed": true}, "scores": {"dark": 0.435297, "mid": 0.47941, "bright": 0.525869}, "inference_ms": [592.937, 590.979, 592.118], "model": {"name": "model-heavy", "version": "0.1.0", "manifest_sha256": "a38da7342fd7c44e1317921f0d3204a9c0a2b64de16198c68639220bb49cb3b3 |
| G3 cutover between two heavy models on GPU under continuous load (5 min) | PASS | {"rate_per_s": 0.848, "sent": 256, "wrong": 0, "duplicates": 0, "cutovers": "9/9", "max_gap_s": 1.267, "latency_ms": {"p50": 608.573, "p95": 688.701, "max": 1165.582}, "vram_after": {"name": "NVIDIA RTX A6000", "used_mib": 4622.0, "total_mib": 49140.0, "driver": "580.126.16"}} |
| G4 GPU OOM at model load/warm-up: activation refused, old recipe keeps serving, no restart needed | PASS | {"hog": {"total_mib": 48539, "held_mib": 47673, "free_mib": 199}, "activation_http": 422, "code": "ACTIVATION_GOLDEN_FAILED", "active_after": "recipe-a@0.1.0", "readyz": 200, "request_on_old_recipe": "COMPLETED", "activation_after_vram_freed": 200} |
| G5 GPU OOM when a second model is loaded next to the active one: refused, active model unaffected | PASS | {"hog": {"total_mib": 48539, "held_mib": 45499, "free_mib": 199}, "activation_http": 422, "code": "ACTIVATION_GOLDEN_FAILED", "active_after": "recipe-heavy@0.1.0", "request_on_active_model": "COMPLETED", "activation_after_vram_freed": 200} |
| P13a Prometheus scrapes API and Triton | PASS | {"both_targets_up_after_s": 0.0} |
| P13b one request and one model switch are observable in Prometheus | PASS | {"visible_after_s": 4.0, "counters_before": {"terminal": 266.0, "act": 17.0, "triton_b": 0.0}, "counters_after": {"terminal": 268.0, "act": 18.0, "triton_b": 2.0}, "active_recipe_series": [{"__name__": "vr01_active_recipe_info", "instance": "api:9090", "job": "vr01-api", "model": "model-b", "model_sha256": "dcf1542894dc", "model |
| P13c full execution path of one request from its request_id (ledger + log) | PASS | {"events": ["request.admitted", "http.access", "inference.started", "inference.finished", "request.terminal"], "pinned_model": {"name": "model-a", "version": "0.1.0", "manifest_sha256": "a700dc698dfef898dda6ba046196ef339dd7614ea360d041321c8becb6aecce1"}} |
| P13d alert VR01ModelUnavailable fires when Triton is stopped and clears after it is back | PASS | {"fired_after_stop_s": 24.0, "cleared_after_start_s": 6.0} |
| P13e Grafana serves the provisioned dashboard | PASS | {"title": "VR-01 MVP — tổng quan vận hành", "panels": 18} |
| P13f /metrics is reachable inside the compose network but not published on the host | PASS | {"series_lines": 141, "host_port_9090_http": "000"} |
| P14 automatic rollback after 3 consecutive inference errors right after cutover | PASS | {"failed_requests": ["FAILED/BACKEND_ERROR", "FAILED/BACKEND_ERROR", "FAILED/BACKEND_ERROR"], "active_after": "recipe-a@0.1.0", "auto_rollback_logged": true, "failed_request_keeps_lineage": "model-bad", "request_after_rollback": "COMPLETED/NG"} |
| P7 kill -9 API with 1 running + 2 queued | PASS | {"before_kill": ["PROCESSING", "RECEIVED", "RECEIVED"], "after_restart": ["INDETERMINATE", "INDETERMINATE", "INDETERMINATE"], "ready_again_s": 1.0, "active_recipe": "recipe-heavy@0.1.0", "retry_with_new_id": "COMPLETED"} |
| P8 kill -9 Triton under load: no wrong/duplicate result, service recovers | PASS | {"sent": 501, "completed": 501, "technical": {}, "not_accepted": 0, "wrong": 0, "duplicates": 0, "cutovers": "6/6", "ready_after_load_s": 0.0, "active_recipe": "recipe-a@0.1.0", "seconds_from_kill_to_end": 40.6} |

## Kubernetes (kubeadm) — vps-gpu-2026-10-11T0905Z / k8s/k8s-report.txt

Nguồn: `evidence/vps-gpu-2026-10-11T0905Z/k8s/k8s-report.txt` (sha256 d7bf286b2c6d9b3e…)

Kết luận: **K8S CHECK PASS  10/10**

| Bước | Kết quả |
|---|---|
| K1 deploy from a clean namespace, rollout complete  13s | PASS |
| K2 both containers Ready (api readiness = active recipe verified + model loaded)  ready=[true true] | PASS |
| K3 vr01ctl status through NodePort  SAN SANG recipe active : recipe-a@0.1.0  (sha256 de9871c469e0)  | PASS |
| K4 smoke flow through NodePort  SMOKE PASS  18/18  -> /root/k8s-evidence | PASS |
| K5 from another pod: Triton 8000 closed, API 8443 open, metrics 9090 closed by NetworkPolicy  triton8000=closed api8443=open metrics9090=closed | PASS |
| K6 pod deleted -> recreated, same active recipe  11s; recipe active : recipe-b@0.1.0  (sha256 6ee3711f1bf3) | PASS |
| K7 update to a new release revision  rev 1 -> 2, 12s | PASS |
| K8 rollback to the previous release (rollout undo)  release=0.1.0, 14s | PASS |
| K9 model switch and model rollback  DA CHUYEN: recipe-b@0.1.0 -> recipe-a@0.1.0 | PASS |
| K10 smoke flow after update/rollback  SMOKE PASS  18/18  -> /root/k8s-evidence | PASS |

## Quét tải model nặng trên GPU — vps-gpu-2026-10-11T0905Z

Nguồn: `evidence/vps-gpu-2026-10-11T0905Z/compose/load-sweep-gpu-heavy-report.json` (sha256 7e9bc8bb2fc524e5…)

Throughput cao nhất chưa bão hòa: **1.66 req/s**; bước đầu tiên bão hòa: 2.0 req/s. Model là mạng tích chập tự sinh, không phải model QC; số chỉ có nghĩa trên máy thử.

## Phiên Tuần 4 trên Triton thật — vps-w4-2026-10-11T0754Z / compose/session-w4-report.json

Nguồn: `evidence/vps-w4-2026-10-11T0754Z/compose/session-w4-report.json` (sha256 48d517249a1507d1…)

Môi trường: Ubuntu 26.04 LTS · 7.0.0-29-generic x86_64 · 4 · Mem:            7746         716         579           4        6763        7029 · /dev/sda1        75G   22G   51G  30% /

Kết luận: **FAIL**, 10/12 bước.

| Bước | Kết quả | Số liệu ghi nhận |
|---|---|---|
| P1 smoke flow | PASS | {} |
| P13a Prometheus scrapes API and Triton | PASS | {"both_targets_up_after_s": 10.0} |
| P13b one request and one model switch are observable in Prometheus | FAIL | {"visible_after_s": null, "active_recipe_series": [{"__name__": "vr01_active_recipe_info", "instance": "api:9090", "job": "vr01-api", "model": "model-b", "model_sha256": "dcf1542894dc", "model_version": "0.1.0", "recipe": "recipe-b", "recipe_sha256": "6ee3711f1bf3", "recipe_version": "0.1.0"}], "p95_total_s": NaN} |
| P13c full execution path of one request from its request_id (ledger + log) | PASS | {"events": ["request.admitted", "http.access", "inference.started", "inference.finished", "request.terminal"], "pinned_model": {"name": "model-a", "version": "0.1.0", "manifest_sha256": "a700dc698dfef898dda6ba046196ef339dd7614ea360d041321c8becb6aecce1"}} |
| P13d alert VR01ModelUnavailable fires when Triton is stopped and clears after it is back | PASS | {"fired_after_stop_s": 20.0, "cleared_after_start_s": 6.0} |
| P13e Grafana serves the provisioned dashboard | PASS | {"title": "VR-01 MVP — tổng quan vận hành", "panels": 18} |
| P13f /metrics is reachable inside the compose network but not published on the host | PASS | {"series_lines": 93, "host_port_9090_http": "000"} |
| P14 automatic rollback after 3 consecutive inference errors right after cutover | PASS | {"failed_requests": ["FAILED/BACKEND_ERROR", "FAILED/BACKEND_ERROR", "FAILED/BACKEND_ERROR"], "active_after": "recipe-a@0.1.0", "auto_rollback_logged": true, "failed_request_keeps_lineage": "model-bad", "request_after_rollback": "COMPLETED/NG"} |
| p18_heavy_image_model | FAIL | {"error": "AssertionError: activate recipe-heavy: 422 {'type': 'urn:vr01:problem:RECIPE_NOT_FOUND', 'title': 'Unprocessable content', 'status': 422, 'code': 'RECIPE_NOT_FOUND', 'detail': 'recipe recipe-heavy@0.1.0 is not registered', 'trace_id': '4236316af097408fb9f5aa0ac57bab3f', 'request_id': None, 'retryable': False}"} |
| P16 app image upgrade and rollback under load (Compose): no wrong result, active recipe kept | PASS | {"upgrade_s": 8.7, "image_after_upgrade": "vr01-mvp-api:0.1.1-test", "active_after_upgrade": "recipe-a@0.1.0", "rollback_s": 8.6, "image_after_rollback": "vr01-mvp-api:0.1.0", "sent": 901, "completed": 901, "technical": {}, "not_accepted": 0, "client_retries": {"recipe_refresh_409": 0, "queue_full_429": 0, "not_ready_503": 0, "s |
| P17 network cut between client and API for 10 s under load: retries with same request_id, no loss/duplicate | PASS | {"iptables_chains": ["INPUT", "DOCKER-USER", "OUTPUT"], "sent": 401, "completed": 401, "not_accepted": 0, "client_send_errors": 5, "wrong": 0, "duplicates": 0} |
| P15 image store really full (64 KiB tmpfs): clean 503, no record for refused, recovery after space is back | PASS | {"accepted_before_full": 16, "refused": 5, "first_refusal": [503, "STORAGE_UNAVAILABLE"], "readyz": [503, {"ready": false, "reasons": ["STORAGE_UNAVAILABLE"]}], "refused_have_no_record": true, "accepted_all_completed": true, "ready_after_space_back_s": 0.0, "request_after_recovery": "COMPLETED"} |

## Kubernetes (kubeadm) — vps-w4-2026-10-11T0754Z / k8s/k8s-report.txt

Nguồn: `evidence/vps-w4-2026-10-11T0754Z/k8s/k8s-report.txt` (sha256 95487ee3e2812293…)

Kết luận: **K8S CHECK PASS  10/10**

| Bước | Kết quả |
|---|---|
| K1 deploy from a clean namespace, rollout complete  8s | PASS |
| K2 both containers Ready (api readiness = active recipe verified + model loaded)  ready=[true true] | PASS |
| K3 vr01ctl status through NodePort  SAN SANG recipe active : recipe-a@0.1.0  (sha256 de9871c469e0)  | PASS |
| K4 smoke flow through NodePort  SMOKE PASS  18/18  -> /root/k8s-evidence | PASS |
| K5 from another pod: Triton 8000 closed, API 8443 open, metrics 9090 closed by NetworkPolicy  triton8000=closed api8443=open metrics9090=closed | PASS |
| K6 pod deleted -> recreated, same active recipe  6s; recipe active : recipe-b@0.1.0  (sha256 6ee3711f1bf3) | PASS |
| K7 update to a new release revision  rev 1 -> 2, 11s | PASS |
| K8 rollback to the previous release (rollout undo)  release=0.1.0, 11s | PASS |
| K9 model switch and model rollback  DA CHUYEN: recipe-b@0.1.0 -> recipe-a@0.1.0 | PASS |
| K10 smoke flow after update/rollback  SMOKE PASS  18/18  -> /root/k8s-evidence | PASS |

## Gói offline lớp ứng dụng — vps-w4-2026-10-11T0754Z / k8s/offline-report.txt

Nguồn: `evidence/vps-w4-2026-10-11T0754Z/k8s/offline-report.txt` (sha256 56889d1e47a86c80…)

Kết luận: **OFFLINE CHECK FAIL  5/7  (egress stays cut; reboot or flush iptables to restore)**

| Bước | Kết quả |
|---|---|
| O1 build offline app bundle  size 7.0G, files 79 | PASS |
| O2 Internet egress cut on the node  probe=open | FAIL |
| O3 app images removed from the node before offline install  left=0 | PASS |
| O4 install from the bundle with egress cut  122s; kich hoat luc : 2026-10-11T08:09:20.316Z | PASS |
| O5 smoke flow on the offline-installed stack (tools from the bundle)  SMOKE PASS  18/18  -> /root/k8s-evidence | PASS |
| O6 no image pull was attempted  pull events=0 | PASS |
| O7 egress still cut at the end  probe=open | FAIL |

## Chưa có trong báo cáo này

- Máy AMD của nhà máy; air gap đầy đủ (lớp nền Kubernetes vẫn cài online); model QC thật.
- Người vận hành (không phải agent AI) tự chạy theo README/runbook trên máy sạch.
- Mất điện thật; soak dài hơn 8 giờ.
