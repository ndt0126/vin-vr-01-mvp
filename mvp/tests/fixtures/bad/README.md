# Fixture test: model hỏng sau khi được chọn

`model-bad` qua được golden check (ảnh mẫu tối) nhưng báo lỗi khi suy luận trên ảnh sáng (mean >= 0,5).
Chỉ dùng để thử cơ chế tự rollback sau cutover trên inference server thật. Bật bằng `make start SLOW=1` (cùng cờ với fixture chậm). Không thuộc bộ package mẫu.
