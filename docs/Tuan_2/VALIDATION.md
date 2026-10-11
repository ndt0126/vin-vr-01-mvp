# Kiểm chứng bộ nháp local — 29/09/2026

**Kết quả:** hai package và hai recipe mẫu PASS; **16/16 ca kiểm tra PASS**. Đây là kiểm chứng prototype CPU local của W2-05, không phải test GPU, triển khai Kubernetes hay chấp nhận từ mentor.

Lệnh chạy từ root project:

```bash
python3 docs/Tuan_2/validate_design.py
python3 docs/Tuan_2/test_design.py
```

Kết quả golden/recipe: A score 0.375 → OK; B score 0.3125 → NG. Source tự chạy bằng thư viện chuẩn; không tải model/dataset/phụ thuộc và không truy cập server.

| Nhóm | Ca đã chạy |
|---|---|
| Hợp lệ | Hai gói/recipe; thêm gói C khác artifact trong thư mục tạm mà không sửa source validator. |
| Từ chối dữ liệu/gói sai | Sai checksum, I/O, backend, golden; thiếu field bắt buộc; path traversal; symlink; trùng name/version. |
| Từ chối cấu hình/tham chiếu sai | Sai digest package; thiếu rollback package; thiếu rollback recipe; vượt ngân sách RAM. |
| Không bỏ qua gate chưa implement | Từ chối production mode; từ chối yêu cầu signature khi checker chưa có verification. |

Output của unittest: `Ran 16 tests ... OK`. Các mẫu bị sửa trong test chỉ nằm trong temporary directory, tự dọn sau test. Mã test và validator nằm cùng thư mục để tái tạo.

Bằng chứng đã lưu: [kết quả fixture](evidence/fixture-result.json), [output 16 ca test](evidence/tests.txt), [kích thước và SHA-256 các file bàn giao](evidence/files.sha256.json). Đã kiểm JSON đọc được và các liên kết Markdown nội bộ tồn tại. File kê hash không tự chứa hash của chính nó.

**Giới hạn:** schema checker chỉ hỗ trợ tập keyword dùng trong ba file schema và từ chối keyword lạ; chưa kiểm bằng engine JSON Schema 2020-12 đầy đủ. Không có signature verification, image decoder, Triton/ONNX execution, GPU preflight, stress/OOM, registry bất biến qua nhiều lần chạy, durable activation/rollback, retention job hoặc UI thật. Resource numbers là estimate; metadata OS/arch không phải inventory của máy chạy checker. Mermaid diagrams là bản thiết kế review, không phải topology đã triển khai.
