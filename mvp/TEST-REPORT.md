# VR-01 MVP — Test report

File này được **sinh tự động** bằng `tools/make_test_report.py` từ các file trong `evidence/`. Mỗi bảng ghi file nguồn và 16 ký tự đầu SHA-256 của file đó. Chạy lại lệnh sẽ ra cùng nội dung.

## Unit / contract / integration — local-2026-10-10

Nguồn: `evidence/local-2026-10-10/test-report.json` (sha256 0c0bda2a6fa2a64f…)

Kết luận: **PASS** · Python 3.12.7 · macOS-26.6-arm64-arm-64bit · 23.2 s · kiểm tĩnh OpenAPI 11/11 · API.md khớp spec: True

| Bộ test | Chạy | Đạt | Lỗi | Bỏ qua |
|---|---|---|---|---|
| `test_contract` | 45 | 45 | 0 | 0 |
| `test_mvp` | 22 | 22 | 0 | 0 |
| `test_models` | 6 | 6 | 0 | 0 |

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

## Chưa có trong báo cáo này

- Chuyển recipe dưới tải liên tục trên **Triton thật** (mới chạy với inference server giả).
- Reboot cả máy; GPU (`KIND_GPU`); người khác tự chạy theo README trên máy sạch.
- Stress tới bão hòa, soak dài, fault injection có hệ thống (W4-04).
