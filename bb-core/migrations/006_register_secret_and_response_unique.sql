-- BB-Core migration 006 — vá hai lỗ tìm ra ở đợt soát 09/09/2026

-- Lỗi #1: `/donors/register` từng cấp token cho bất kỳ `id` nào gửi lên, mà mã
-- người hiến không phải bí mật (mã seed là donor-0001…, mã thật thì mọi tài
-- khoản nhân viên đều đọc được qua /sos/donors/nearby). Cột này giữ bản băm
-- PBKDF2 của bí mật thiết bị cấp ở lần đăng ký đầu.
--
-- NULL nghĩa là hồ sơ cũ chưa có bí mật: chỉ chủ hồ sơ (token còn hạn) hoặc
-- nhân viên mới cập nhật được, và lần đó máy chủ sẽ cấp bí mật cho họ.
ALTER TABLE donor ADD COLUMN IF NOT EXISTS device_secret_hash VARCHAR;

-- Lỗi #2: gửi lại "Nhận lời" (app timeout SAU khi máy chủ đã commit) từng tạo
-- thêm một dòng phản hồi và cộng dồn accept_count, khiến một người được đếm
-- thành hai và bộ lập lịch ngừng leo thang khi chưa đủ người thật.
--
-- Dọn trùng trước khi tạo chỉ mục — giữ dòng mới nhất của mỗi người.
DELETE FROM sos_response a
 USING sos_response b
 WHERE a.sos_event_id = b.sos_event_id
   AND a.donor_id     = b.donor_id
   AND (a.responded_at, a.id) < (b.responded_at, b.id);

CREATE UNIQUE INDEX IF NOT EXISTS ix_sos_response_event_donor
    ON sos_response (sos_event_id, donor_id);

-- Đếm lại accept_count cho các sự kiện đang mở, phòng khi đã bị cộng dồn sai.
UPDATE sos_event e
   SET accept_count = COALESCE((
       SELECT COUNT(DISTINCT r.donor_id)
         FROM sos_response r
        WHERE r.sos_event_id = e.id
          AND r.outcome = 'accepted'
   ), 0);
