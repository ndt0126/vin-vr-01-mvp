# VR-01 MVP — Test report

File này được **sinh tự động** bằng `tools/make_test_report.py` từ các file trong `evidence/`. Mỗi bảng ghi file nguồn và 16 ký tự đầu SHA-256 của file đó. Chạy lại lệnh sẽ ra cùng nội dung.

## Unit / contract / integration — local-2026-10-10

Nguồn: `evidence/local-2026-10-10/test-report.json` (sha256 583354cd4480fd0f…)

Kết luận: **PASS** · Python 3.12.7 · macOS-26.6-arm64-arm-64bit · 28.1 s · kiểm tĩnh OpenAPI 11/11 · API.md khớp spec: True

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

## Chưa có trong báo cáo này

- Chuyển recipe dưới tải liên tục trên **Triton thật** (mới chạy với inference server giả).
- Reboot cả máy; GPU (`KIND_GPU`); người khác tự chạy theo README trên máy sạch.
- Stress tới bão hòa, soak dài, fault injection có hệ thống (W4-04).
