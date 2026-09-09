-- BB-Core migration 004 — đẩy thông báo và nhật ký lời kêu gọi (P2)

ALTER TABLE donor ADD COLUMN IF NOT EXISTS push_token      VARCHAR;
ALTER TABLE donor ADD COLUMN IF NOT EXISTS push_platform   VARCHAR;   -- android | ios
ALTER TABLE donor ADD COLUMN IF NOT EXISTS push_updated_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS sos_notification (
    id            VARCHAR PRIMARY KEY,
    sos_event_id  VARCHAR NOT NULL REFERENCES sos_event(id),
    donor_id      VARCHAR NOT NULL REFERENCES donor(id),
    ring          INTEGER NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel       VARCHAR NOT NULL,                      -- fcm | store
    status        VARCHAR NOT NULL DEFAULT 'pending',    -- pending|sent|failed|read
    error         VARCHAR,
    delivered_at  TIMESTAMPTZ,
    read_at       TIMESTAMPTZ
);

-- Mỗi người hiến chỉ nhận MỘT lần cho mỗi sự kiện, dù sự kiện leo qua nhiều vòng.
CREATE UNIQUE INDEX IF NOT EXISTS ix_sos_notif_event_donor
    ON sos_notification (sos_event_id, donor_id);
CREATE INDEX IF NOT EXISTS ix_sos_notif_donor_status
    ON sos_notification (donor_id, status);

-- Sự kiện quá hạn được đóng bằng trạng thái mới
COMMENT ON COLUMN sos_event.status IS 'open | fulfilled | expired | cancelled';
