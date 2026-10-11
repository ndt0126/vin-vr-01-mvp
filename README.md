# VIN – VR – 01: MVP kiểm tra chất lượng bằng AI (bản lab)

Repo công khai để mentor và công cụ review đọc/chạy lại. Đây là **bản lab, chưa được nghiệm thu**; mọi "PASS" trong repo là kết quả tự kiểm, không phải chấp nhận của mentor/QC.

| Thư mục | Task | Nội dung | Tự kiểm |
|---|---|---|---|
| [`mvp/`](mvp/) | W3-01 → W3-05 | Inspection API + lifecycle controller + Triton, Docker Compose, test, smoke, bài tải có chuyển model | `cd mvp && make test`; với Triton thật: `make start && make smoke` |
| [`docs/Tuan_2/W2-01/`](docs/Tuan_2/W2-01/) | W2-01 | Use-case PCB1 visual anomaly | `python3 -I check_w2_01.py` |
| `docs/Tuan_2/W2-02-*.md`, `ADR-D09-*.md`, `DECISIONS …md` | W2-02 | Kiến trúc MVP/target, ADR SQLite, network matrix, failure/sizing/backup | Chỉ là tài liệu (bộ kiểm cần bundle lab, không nằm trong repo này) |
| [`docs/Tuan_2/W2-03/`](docs/Tuan_2/W2-03/) | W2-03 | Data flow + state machine | `python3 -I check_w2_03.py` |
| [`docs/Tuan_2/W2-04/`](docs/Tuan_2/W2-04/) | W2-04 | OpenAPI v1 + server tham chiếu + contract test | `python3 -I verify_w2_04.py` |
| `docs/Tuan_2/W2-05-*.md`, `schemas/`, `examples/`, `validate_design.py` | W2-05 | Chuẩn ModelPackage/Recipe, 2 package mẫu, validator | `python3 -m unittest test_design` |
| [`docs/Tuan_2/W2-06/`](docs/Tuan_2/W2-06/) | W2-06 | Prototype UI bấm được + screen-state matrix + phiếu review (chưa review) | `python3 -I check_w2_06.py`; mở `prototype.html` |

Bắt đầu từ [`mvp/README.md`](mvp/README.md): quick start, những gì đã kiểm chứng, những gì **chưa** kiểm chứng và giới hạn.

Yêu cầu để chạy các lệnh tự kiểm: Python 3.10+ với `jsonschema`, `PyYAML`, `Pillow` (`pip install -r mvp/backend/requirements.txt`). Riêng `mvp/` chỉ cần Docker + `make`.

Lưu ý:

- Hai model mẫu là hàm tuyến tính (deterministic stub), không phải model QC. OK/NG/REVIEW ở đây không nói gì về chất lượng sản phẩm.
- Token, chứng chỉ trong luồng chạy là đồ lab, sinh lúc `make init`; repo không chứa secret nào.
- `mvp/evidence/` là log/báo cáo thô của các lượt chạy (không gồm token và private key).
