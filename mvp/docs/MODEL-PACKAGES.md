# VR-01 MVP — Các loại ModelPackage được hỗ trợ

Chuẩn ModelPackage/Recipe là của W2-05 (`packages/schemas/`). MVP hỗ trợ hai backend mà schema đó đã khai báo. Thêm model thuộc một trong hai loại này **không cần sửa mã nguồn**; loại khác thì phải thêm code và bị validator từ chối cho tới lúc đó.

| | `reference-linear-score-v1` | `triton-onnx-v1` (thêm 11/10/2026) |
|---|---|---|
| Artifact | `model.json` (`gain`, `bias`) | `model.onnx` bất kỳ thỏa I/O bên dưới |
| Input | `IMAGE` FP32 `[1,1,2,2]` | `IMAGE` UINT8 `[1,3,S,S]`, 8 ≤ S ≤ 4096 |
| Output | `SCORE` FP32 `[1]` trong [0,1] | `SCORE` FP32 `[1]` trong [0,1] |
| Preprocess (API làm) | `tensor-json-v1`: ảnh → xám → 2×2 | `image-rgb-unit-v1`: RGB, resize bilinear về S×S, xếp CHW, uint8. Việc chia 255 nằm trong model |
| Postprocess | `normalized-score-v1`: so score với threshold của recipe → OK/NG/REVIEW | như bên trái |
| Gửi sang Triton | JSON (4 số) | KServe v2 binary tensor (bytes thô) |
| Golden | `golden-input.json` + `expected_score` | `golden-input.png` + `expected_score`, `atol` ≤ 0,01 |
| Thiết bị | cpu | cpu hoặc nvidia-gpu (`config.pbtxt` ghi `KIND_CPU`/`KIND_GPU` theo package) |

## Validator kiểm gì với `triton-onnx-v1`

Schema; profile runtime có trong `site-config.json` của máy; preprocess/postprocess được máy cho phép; đúng dạng I/O; kích thước ảnh không vượt `max_decoded_pixels`; CPU/RAM không vượt `capacity`; package GPU phải khai VRAM > 0 và vừa `available_vram_mib − gpu_reserve_mib`, package CPU phải khai VRAM = 0; SHA-256 của `model.onnx` và ảnh golden; ảnh golden là PNG.

Validator **không chạy model**. Golden output được kiểm lúc kích hoạt recipe, bằng chính inference server: nạp model → chạy ảnh golden → so với `expected_score` → đạt mới chuyển. Sai thì giữ recipe cũ.

Máy chỉ nhận loại package mà `site-config.json` của nó cho phép. Bản `site-config.json` gốc không cho phép model ảnh; fixture bên dưới tự bổ sung profile vào bản sao trong thư mục chạy.

## Fixture model nặng (`make start HEAVY=<mức>`)

`tools/make_heavy_fixture.py` sinh `model-heavy` / `recipe-heavy`: mạng tích chập sâu (Conv 3×3 + ReLU, global average pool, sigmoid) với trọng số giả ngẫu nhiên **tất định từ seed**, nên cùng mức thì `model.onnx` có cùng SHA-256 trên mọi máy (hash được ghim trong code và kiểm lúc sinh).

| Mức | Lớp × kênh × ảnh | File | Suy luận trên CPU laptop (tham khảo) | Dùng cho |
|---|---|---|---|---|
| `tiny` | 2 × 4 × 32² | 1 KiB | < 1 ms | unit test |
| `cpu` | 16 × 48 × 192² | 1,2 MiB | khoảng 0,1 giây | phiên VPS CPU |
| `gpu` | 48 × 96 × 512² | 15 MiB | khoảng 7 giây | phiên GPU |
| `gpu-xl` | 64 × 128 × 1024² | 35 MiB | khoảng 78 giây | phiên GPU, tải nặng |

Đây là **tải tính toán thật** (tích chập, VRAM) để đo hiệu năng và ổn định. Nó **không phải model QC**, không được huấn luyện, và điểm số của nó không nói gì về chất lượng sản phẩm. Thời gian trên GPU chưa đo.

## Đã kiểm và chưa kiểm (11/10/2026)

- Đã kiểm trên laptop: 10 test (`tests/test_heavy.py`): validator nhận/từ chối kèm lý do, model repository, kích hoạt + golden, điểm phụ thuộc ảnh và khớp onnxruntime, chuyển qua lại giữa model tuyến tính và model ảnh vẫn giữ pin, tensor đi dạng binary uint8. Chạy trọn luồng với mức `cpu` qua inference server giả có onnxruntime, kèm quét tải.
- Chưa kiểm: Triton thật nạp model này (CPU và GPU), `KIND_GPU`, số đo trên GPU, model do người khác cung cấp.
