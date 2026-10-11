# Lượt "người B" diễn tập theo runbook — 11/10/2026

**Ai:** một agent AI mới (không phải người), không biết dự án, chỉ đọc `mvp/README.md` và `mvp/docs/RUNBOOK.md` (draft-1) của repo công khai ở commit `07b87ce`, dùng terminal có ghi biên bản (`terminal.jsonl`, 18 lệnh).

**Máy:** VPS Hetzner mới, Ubuntu 26.04, 4 vCPU, 7,7 GB RAM; chưa có Docker.

**Kết luận của người B: DONE_NO_INTERVENTION** — 8/8 việc, mọi lệnh lấy từ tài liệu, mọi kết quả khớp điều tài liệu ghi; khoảng 6 phút.

| Việc | Kết quả |
|---|---|
| 1. Cài theo README | `make start` exit 0 sau khoảng 104 giây; smoke 18/18 |
| 2. Kiểm sức khỏe | `SAN SANG` |
| 3. Chọn `recipe-a` | `DA CHUYEN: recipe-b → recipe-a`, golden đạt |
| 4. Đổi sang `recipe-b` rồi rollback | cả hai `DA CHUYEN`; sau rollback active là `recipe-a`; lịch sử có đủ 5 lần chuyển kèm lý do |
| 5. Sao lưu | `integrity_check: ok`, `has_trace: true` |
| 6. Khôi phục | 13,9 giây; dữ liệu cũ được đổi tên, không bị xóa; recipe active đúng |
| 7. Dừng rồi bật | 1,7 giây + 13,1 giây; recipe active giữ nguyên |
| 8. Gói chẩn đoán | 10.354 byte, 7 file; người B tự kiểm: không có token hay private key |

**Góp ý của người B, đã sửa trong RUNBOOK draft-2:** không nói cách đặt lại recipe sau smoke và recipe nào là mặc định; ví dụ lệnh restore dùng tên bản sao lưu cố định; không nói giờ trong tên file là UTC; không nhắc `activation_id`; không nêu tên file trong gói chẩn đoán; bài khôi phục không cho thấy dữ liệu "quay về" vì không có request nào giữa lúc sao lưu và lúc khôi phục.

**Phạm vi:** cần Internet; người làm là AI; RUNBOOK draft-2 chưa được một lượt độc lập khác chạy lại.
