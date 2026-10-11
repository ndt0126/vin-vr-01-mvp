# Fixture test: model chạy chậm

`model-slow` cho đúng kết quả như `model-a` nhưng mỗi lần suy luận tốn thêm thời gian (vòng lặp MatMul, cấu hình ở `triton-build.json`).
Chỉ dùng để thử timeout, hủy khi đang chạy và drain trên Triton thật. Bật bằng `make start SLOW=1`. Không thuộc bộ package mẫu.
