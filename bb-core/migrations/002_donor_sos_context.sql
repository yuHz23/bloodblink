-- BB-Core migration 002 — bối cảnh lâm sàng cho sự kiện SOS
--
-- Áp dụng cho CSDL đã tạo trước khi có P0. Với CSDL mới, `Base.metadata.create_all`
-- trong seed/seed_db.py đã sinh sẵn các cột này.

ALTER TABLE sos_event ADD COLUMN IF NOT EXISTS facility_id    VARCHAR REFERENCES facility(id);
ALTER TABLE sos_event ADD COLUMN IF NOT EXISTS component_code VARCHAR;
ALTER TABLE sos_event ADD COLUMN IF NOT EXISTS abo            VARCHAR;
ALTER TABLE sos_event ADD COLUMN IF NOT EXISTS rh             VARCHAR;
ALTER TABLE sos_event ADD COLUMN IF NOT EXISTS urgency        VARCHAR;
ALTER TABLE sos_event ADD COLUMN IF NOT EXISTS h3_cell        VARCHAR;
ALTER TABLE sos_event ADD COLUMN IF NOT EXISTS status         VARCHAR NOT NULL DEFAULT 'open';

CREATE INDEX IF NOT EXISTS ix_sos_event_status ON sos_event (status);

-- Độ phân giải H3 đổi từ 9 sang 7: ô lưới cũ của người hiến không còn khớp,
-- xoá đi để app đăng ký lại ở res 7 (dữ liệu vị trí vốn chỉ sống 4 giờ).
UPDATE donor SET geocell_h3 = NULL, geocell_ttl = NULL WHERE geocell_h3 IS NOT NULL;
