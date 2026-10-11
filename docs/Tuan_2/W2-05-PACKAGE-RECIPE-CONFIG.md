# W2-05 — Model package, recipe và cấu hình trạm

29/09/2026 · DRAFT 0.1 · [Giả định](README.md) · [Kiến trúc](W2-02-KIEN-TRUC.md).

## 1. Ba hồ sơ có nhiệm vụ khác nhau

| Hồ sơ | Cách hiểu | Nội dung chính / quyền thay đổi |
|---|---|---|
| Model package | Hộp model đã niêm phong | Artifact, tên/version, I/O, runtime/backend, tiền–hậu xử lý, tài nguyên, golden/warm-up và danh sách package tiền nhiệm tương thích. Phát hành version mới khi nội dung thay đổi. |
| Recipe | Hướng dẫn kiểm tra cho một trạm | Tham chiếu chính xác package bằng digest; ngưỡng OK/NG; recipe có thể quay lại. Người có quyền sửa tạo revision/version mới. |
| Site config | Quy định vận hành tại nơi lắp | Runtime được phép, policy, limits, ngân sách tài nguyên, retention, hỗ trợ cảm ứng/CLI. Quản trị cấu hình riêng, không chỉnh model để đổi các giá trị này. |

Ví dụ: thay ngưỡng NG từ 0,5 sang 0,6 là phiên bản recipe mới; không phải sửa weights hoặc phát hành lại model. Kết quả phải lưu cả package digest, recipe version/digest và site config version/digest để tra đúng điều kiện lúc kiểm tra.

## 2. File bàn giao

```text
schemas/
  model-package.schema.json
  recipe.schema.json
  site-config.schema.json
examples/
  site-config.json
  packages/model-a/{manifest.json,model.json,golden-input.json}
  packages/model-b/{manifest.json,model.json,golden-input.json}
  recipes/{recipe-a.json,recipe-b.json}
validate_design.py
test_design.py
```

Schema dùng cú pháp JSON Schema draft 2020-12, version hợp đồng riêng là `w2-draft-v1`. Các object từ chối field ngoài danh sách. Chưa coi đây là schema API v1 đã mentor chấp nhận. Nếu dùng YAML về sau phải parse bằng chế độ an toàn, từ chối duplicate keys/custom tags và kiểm cùng schema; bản hiện tại chỉ cung cấp JSON.

## 3. Quy định model package

| Field | Ý nghĩa / quy tắc |
|---|---|
| `name`, `version`, `schema_version` | Danh tính model và phiên bản hợp đồng. Không ghi đè cùng name/version bằng nội dung khác. |
| `purpose` | `fixture` cho kiểm thử giả lập; `qc-model` dành model QC, cần validator/runtime thực. Không đưa fixture thành model QC đã đạt accuracy. |
| `artifact.path`, `artifact.sha256` | Một file model trong package và hash chính xác của byte file. Phiên bản đầu chỉ hỗ trợ một artifact độc lập; model cần nhiều external-data files phải mở rộng schema/validator trước. |
| `runtime.backend`, `profile`, `device` | Adapter/backend cần dùng, profile đã được site cho phép, CPU hoặc NVIDIA GPU. Package không được tự chọn container tùy ý hoặc tải runtime từ Internet. |
| `io.input`, `io.output` | Tên tensor, kiểu số và shape. Bản này giới hạn một tensor input, một output score. Batch 1; runtime validator phải đối chiếu metadata thực, không chỉ nhìn manifest. |
| `preprocess`, `postprocess` | ID của phép xử lý đã được platform hỗ trợ; không có script/code tùy ý trong package. |
| `resources` | CPU, RAM và peak VRAM dự kiến; `basis` ghi estimate hoặc measured. Giá trị khai báo chỉ dùng preflight; không chứng minh máy thực có đủ tài nguyên. |
| `compatibility` | Phiên bản hợp đồng platform, OS và kiến trúc CPU đích. Runtime profile được đối chiếu tiếp với ma trận OS/kernel/driver/CUDA/backend đã test của bộ cài. |
| `warmup` | Số lượt chạy thử và deadline trước khi cho phép activate. Không dùng warm-up làm benchmark SLA. |
| `golden` | File input có hash, score mong đợi và sai số tuyệt đối/tương đối. Đánh giá `abs(actual-expected) <= atol + rtol*abs(expected)`. |
| `rollback_candidates` | Tham chiếu name/version/hash của các package tiền nhiệm đã khai báo tương thích. Package A đầu tiên có thể rỗng; B chỉ định A. Đây chưa phải bằng chứng đã chạy rollback. |

**Digest của toàn manifest:** SHA-256 trên đúng byte `manifest.json` đã phát hành, bao gồm khoảng trắng/newline. Không đưa hash của chính manifest vào manifest; recipe chứa hash này. Sửa bất kỳ field nào cũng tạo digest mới; registry phải từ chối cùng name/version nhưng khác digest. File recipe/config cũng hash theo byte khi lưu revision. Prototype kiểm trùng identity trong tập hiện tại; registry production phải kiểm cả lịch sử đã phát hành.

Chữ ký detached phải bao phủ digest manifest và metadata phát hành theo policy của bộ cài. Khóa công khai tin cậy đến từ trust store của site, không tự tin khóa được gói model mang vào. Quy trình khóa offline/rotation/revocation chưa chốt; **prototype này không xác minh chữ ký** và từ chối khi policy yêu cầu chữ ký. Không phân phối private key trong package.

### Profiles trong bản nháp

| Profile | Quy tắc | Mức hỗ trợ |
|---|---|---|
| `reference-linear-score-v1` / `tensor-json-v1` | Input file JSON chứa bốn số [0,1], ánh xạ tensor `IMAGE FP32 [1,1,2,2]`. Artifact chỉ có gain/bias; score = clip(gain × mean(input) + bias, 0, 1), output `SCORE FP32 [1]`. | Được thực thi bởi checker local, dùng số Python; chưa đo sai số FP32 của backend thật. Không đọc ảnh camera. |
| `triton-onnx-v1` / `image-rgb-unit-v1` | Profile đề xuất: một ONNX file độc lập; ảnh RGB, resize bilinear tới H×W cố định trong input `[1,3,H,W]`, chia 255, FP32 NCHW; output `[1]` FP32 hữu hạn trong [0,1]. Không tự áp softmax hay normalize khác. | Chỉ là nhánh hợp đồng dự kiến trong schema. Chưa implement/kiểm thử trong bộ này; checker hiện từ chối backend này. |
| `normalized-score-v1` | Đọc một score đã chuẩn hóa; production phải từ chối NaN/Inf/ngoài [0,1], không tự sửa score. | Fixture tạo score theo công thức đã nêu; không có localization/overlay. |

Runtime profile production phải có image pin bằng `sha256:...` và tham chiếu ma trận tương thích được kiểm chứng của bộ cài. Ví dụ CPU dùng `image_digest: null` vì chạy local, không phải container image thật. OS/arch trong fixture là metadata đích Linux amd64; chạy checker trên laptop không chứng minh Linux/driver/CUDA compatibility. Registry runtime và ma trận chi tiết cần hoàn thiện khi có máy đích; chưa điền giá trị giả.

**Giới hạn “thêm model không sửa source”:** áp dụng cho model tuân thủ backend, transforms và I/O mà platform đã hỗ trợ. Nếu model cần backend mới, tensor mới hoặc xử lý ảnh mới thì phải phát triển adapter và kiểm thử thêm. Đổi dữ liệu trong một package hợp lệ thuộc profile hỗ trợ không cần sửa source.

## 4. Recipe và site config

- Recipe cố định site/station, package name/version/digest và `score-gte-threshold-is-ng`. Score bằng threshold là NG. Chỉ áp quy tắc sau inference thành công; lỗi kỹ thuật giữ trạng thái riêng, chưa có quyết định chất lượng.
- `rollback_recipe` trỏ recipe tiền nhiệm bằng name/version/hash; package của recipe đó phải nằm trong `rollback_candidates` của package hiện tại. Nếu không có phiên bản trước thì dùng null, không hứa có rollback.
- Rollback chỉ được phép khi còn đủ artifact, recipe, runtime tương thích và tài nguyên. Đổi site config có thể làm recipe cũ không còn dùng được; phải kiểm lại toàn bộ trước activation. Prototype chỉ kiểm tham chiếu và chạy các gói, không thực hiện chuyển active version dưới tải.
- Site config có policy cho phép purpose/backend/transforms, ngân sách tài nguyên, limits, retention và hai cách thao tác. Đây là dữ liệu cấu hình; quyền người dùng/thiết bị sẽ do W2-04/06 mô tả, không chứa password/token trong JSON.
- Mọi con số trong `examples/site-config.json` là giá trị lab: 1 MiB input, 4 giá trị ảnh giả, một request đang xử lý, queue 8, timeout 5 giây, retention ảnh 1 ngày/log 7 ngày/audit 30 ngày. **Chưa phải yêu cầu nhà máy**. Checker chỉ kiểm schema và phần liên quan tới fixture, không xây queue, dọn dữ liệu hay thực thi timeout request thật.
- Production admission phải yêu cầu ký số, cấm fixture, runtime đã pin, kiểm môi trường/tài nguyên thực. Checker hiện từ chối `mode: production` hoàn toàn, không tạo cảm giác đã có production gate.

## 5. Thứ tự kiểm tra và mã lỗi

Schema đúng mới là kiểm tra hình thức. Admission mục tiêu phải đi qua các bước sau và chỉ activate sau khi tất cả gate bắt buộc đạt.

| Gate | Hành động / lý do từ chối | Mức đã có |
|---|---|---|
| Đọc dữ liệu | Giới hạn byte; từ chối JSON sai/duplicate key/NaN; reject path tuyệt đối, `..`, symlink, file ngoài gói | Checker local; không phải sandbox xử lý file đối kháng production. |
| Schema | Field bắt buộc, kiểu, enum, range, field lạ → `E_SCHEMA` | Checker hỗ trợ đúng tập keyword đang dùng; không phải JSON Schema engine đầy đủ. |
| Integrity/identity | So SHA artifact/golden/manifest refs; kiểm trùng name/version → `E_CHECKSUM`, `E_REFERENCE`, `E_DUPLICATE` | Local trên tập gói được đưa vào. Chưa có registry phát hành bền vững. |
| Nguồn tin cậy | Chữ ký và trust store → `E_SIGNATURE` | Chưa implement crypto verification; nếu require_signature=true thì checker từ chối. |
| Runtime/compatibility | Backend/profile/device/target/transforms phải khớp allowlist → `E_BACKEND`, `E_RUNTIME`, `E_COMPATIBILITY`, `E_TRANSFORM` | Fixture thực thi; production metadata/runtime probe chưa có. |
| I/O | So tên/dtype/shape với runtime thực; kiểm input/output hữu hạn → `E_IO` | Fixture so với contract cố định của adapter; chưa query Triton. |
| Tài nguyên | So estimate với ngân sách; kiểm A+B cùng tồn tại và phần dự phòng → `E_RESOURCE` | Checker so CPU/RAM fixture và VRAM=0; GPU preflight/coexist chưa chạy. |
| Warm-up/golden | Chạy input chuẩn, kiểm deadline và sai số → `E_WARMUP`, `E_GOLDEN` | Có cho CPU fixture. Deadline đo sau các phép tính ngắn; chưa phải watchdog dừng GPU bị treo. |
| Recipe/rollback | Tham chiếu tồn tại, hash đúng, site/station đúng, predecessor được phép, không có vòng recipe rollback → `E_SITE`, `E_ROLLBACK` | Có kiểm local; chưa chạy thao tác phục hồi active version. |
| Activation | Commit revision, pin request, drain cũ, audit, xử lý lỗi activation | Mô tả trong W2-02; chưa implement ở bộ nháp này. |

Nếu gate thất bại, hệ thống mục tiêu phải trả code, field/gate gây lỗi và hướng xử lý; giữ nguyên bản đang active. Không ghi nội dung secret vào lỗi. Với file nén đưa qua air gap còn cần giới hạn dung lượng giải nén, chống zip bomb và symlink/hardlink trong archive; checker hiện chỉ nhận thư mục fixture đã có sẵn.

## 6. Hai mẫu và cách kiểm tra

| Mẫu | Artifact | Golden score | Recipe threshold | Kết quả minh họa |
|---|---|---|---|---|
| A | gain=1, bias=0 | 0,375 | 0,5 | OK |
| B | gain=0,5, bias=0,125 | 0,3125 | 0,3 | NG; có tham chiếu rollback về A |

Input của cả hai là `[0, 0.25, 0.5, 0.75]`, được tự tạo. Đây là fixture toán học, không phải weights học máy, ảnh sản phẩm hay chứng minh accuracy QC. Hai mẫu giúp kiểm hợp đồng và tách recipe khỏi artifact.

Từ thư mục chính project, chạy Python 3.10 trở lên; chỉ cần thư viện chuẩn, không tải package từ Internet:

```bash
python3 docs/Tuan_2/validate_design.py
python3 docs/Tuan_2/test_design.py
```

Test thêm model C tạo một gói mới trong thư mục tạm, đổi artifact/hash/expected score/recipe; checker vẫn chạy bằng source cũ. Test không thêm C vào bộ bàn giao hoặc sửa hai mẫu A/B. Các ca còn lại kiểm từ chối lỗi có chủ đích; kết quả thực tế ở [VALIDATION.md](VALIDATION.md).

## 7. Điều kiện để chuyển từ nháp sang được chấp nhận

Mentor xác nhận phạm vi score profile và fixture; thống nhất schema/recipe/config; review rules; bổ sung runtime thật, ký số và metadata I/O checks; kiểm package mới trên NVIDIA/Kubernetes với cùng adapter mà không sửa source; kiểm warm-up/rollback/resources thực và lưu evidence. Những gate cuối chưa đạt chỉ vì fixture local PASS.
