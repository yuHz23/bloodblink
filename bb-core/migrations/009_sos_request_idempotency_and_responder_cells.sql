-- Keep linked hospital-to-SOS transitions idempotent under browser/scheduler races.
-- Historical duplicate rows remain available; only extra open duplicates are expired.
WITH ranked AS (
    SELECT id, row_number() OVER (
        PARTITION BY request_id ORDER BY accept_count DESC, opened_at, id
    ) AS position
    FROM sos_event
    WHERE request_id IS NOT NULL AND status = 'open'
)
UPDATE sos_event AS event
SET status = CASE
    WHEN event.accept_count >= event.target_count THEN 'fulfilled'
    ELSE 'expired'
END
FROM ranked
WHERE event.id = ranked.id AND ranked.position > 1;

CREATE UNIQUE INDEX IF NOT EXISTS ix_sos_event_open_request_unique
    ON sos_event (request_id)
    WHERE request_id IS NOT NULL AND status = 'open';

ALTER TABLE sos_response
    ADD COLUMN IF NOT EXISTS location_cell VARCHAR;

UPDATE sos_response AS response
SET location_cell = donor.geocell_h3
FROM donor
WHERE response.donor_id = donor.id
  AND response.outcome = 'accepted'
  AND response.location_cell IS NULL
  AND donor.geocell_h3 IS NOT NULL
  AND (
      donor.geocell_ttl > now()
      OR donor.id LIKE 'donor-%'
      OR donor.id LIKE 'mock-map-%'
  );
