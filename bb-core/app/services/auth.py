"""
BB-Core — Băm mật khẩu và cấp token JWT.

Hai loại chủ thể trong hệ thống:
  - `facility_staff` / `admin`: đăng nhập bằng tài khoản trong bảng `app_user`.
  - `donor`: không có tài khoản, nhận token ngay khi đăng ký hồ sơ trong app;
    `sub` của token chính là mã người hiến.

Băm mật khẩu dùng PBKDF2-HMAC-SHA256 của thư viện chuẩn — không thêm phụ thuộc
biên dịch (bcrypt/argon2) chỉ để phục vụ vài tài khoản của đồ án.
"""

import hmac
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from app.config import settings

PBKDF2_ITERATIONS = 200_000
ALGORITHM = "HS256"

ROLE_DONOR = "donor"
ROLE_FACILITY_STAFF = "facility_staff"
ROLE_ADMIN = "admin"
STAFF_ROLES = (ROLE_FACILITY_STAFF, ROLE_ADMIN)


# ── Mật khẩu ──────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Trả về chuỗi `pbkdf2_sha256$<vòng lặp>$<muối hex>$<băm hex>`."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """So sánh theo thời gian hằng định để không rò rỉ thông tin qua thời gian đáp."""
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# ── Token ─────────────────────────────────────────────────────────

def create_access_token(
    subject: str,
    role: str,
    facility_id: Optional[str] = None,
    expires_minutes: Optional[int] = None,
) -> str:
    now = datetime.now(timezone.utc)
    minutes = expires_minutes or settings.jwt_expire_minutes
    payload = {
        "sub": subject,
        "role": role,
        "facility_id": facility_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        "iss": "bb-core",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Ném `jwt.PyJWTError` nếu token hỏng, sai chữ ký hoặc hết hạn."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM], issuer="bb-core")
