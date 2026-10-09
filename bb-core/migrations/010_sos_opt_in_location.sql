ALTER TABLE sos_response
    ADD COLUMN IF NOT EXISTS location_latitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS location_longitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS location_sharing_consented BOOLEAN,
    ADD COLUMN IF NOT EXISTS location_shared_at TIMESTAMP WITH TIME ZONE;

-- A stored approximate profile cell is not consent for an event-specific share.
UPDATE sos_response
SET location_cell = NULL
WHERE location_sharing_consented IS DISTINCT FROM TRUE;

-- Manual SOS forms do not carry a transfer request ID. Keep one open call for
-- an identical facility/blood/component request and preserve duplicates in history.
WITH ranked AS (
    SELECT id, row_number() OVER (
        PARTITION BY facility_id, component_code, abo, rh, urgency, target_count
        ORDER BY accept_count DESC, opened_at, id
    ) AS position
    FROM sos_event
    WHERE request_id IS NULL AND facility_id IS NOT NULL AND status = 'open'
)
UPDATE sos_event AS event
SET status = 'expired'
FROM ranked
WHERE event.id = ranked.id AND ranked.position > 1;

CREATE UNIQUE INDEX IF NOT EXISTS ix_sos_event_open_standalone_unique
    ON sos_event (facility_id, component_code, abo, rh, urgency, target_count)
    WHERE request_id IS NULL AND facility_id IS NOT NULL AND status = 'open';
