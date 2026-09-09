-- BB-Core migration 005 — ghi vết và danh tính người nhận lời (P4)

-- Liên hệ chỉ xuất hiện khi người hiến NHẬN LỜI, do chính họ nhập ở bước đó.
ALTER TABLE sos_response ADD COLUMN IF NOT EXISTS contact_phone VARCHAR;
ALTER TABLE sos_response ADD COLUMN IF NOT EXISTS contact_note  VARCHAR;

CREATE TABLE IF NOT EXISTS audit_log (
    id           VARCHAR PRIMARY KEY,
    prev_hash    VARCHAR,                     -- băm của dòng liền trước
    hash         VARCHAR NOT NULL,            -- SHA-256 của chính dòng này
    actor        VARCHAR NOT NULL,            -- mã tài khoản hoặc mã người hiến
    action       VARCHAR NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}',
    at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_audit_at     ON audit_log (at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_action ON audit_log (action, at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_actor  ON audit_log (actor, at DESC);

-- Nhật ký là append-only: không có UPDATE/DELETE hợp lệ. Ở môi trường thật nên
-- thu hồi quyền trên hai lệnh đó thay vì chỉ trông vào chuỗi băm.
-- REVOKE UPDATE, DELETE ON audit_log FROM bloodblink;
