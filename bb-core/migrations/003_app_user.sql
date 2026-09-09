-- BB-Core migration 003 — tài khoản đăng nhập BB-Console (P1)

CREATE TABLE IF NOT EXISTS app_user (
    id            VARCHAR PRIMARY KEY,
    username      VARCHAR NOT NULL UNIQUE,
    password_hash VARCHAR NOT NULL,          -- pbkdf2_sha256$<vòng>$<muối>$<băm>
    role          VARCHAR NOT NULL,          -- facility_staff | admin
    facility_id   VARCHAR REFERENCES facility(id),
    full_name     VARCHAR,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_app_user_username ON app_user (username);
