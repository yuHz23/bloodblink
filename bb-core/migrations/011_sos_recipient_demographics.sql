-- Retain only the recipient attributes needed to apply the same RhD rules
-- when a transfer shortfall falls back to donor SOS.
ALTER TABLE sos_event
    ADD COLUMN IF NOT EXISTS recipient_sex VARCHAR(1),
    ADD COLUMN IF NOT EXISTS recipient_age INTEGER;
