"""
BB-Core — Phụ thuộc dùng chung cho phân quyền.

Nguyên tắc: mọi endpoint dưới /api đều cần token, TRỪ bốn cái sau (khai báo ở
`app/main.py`): /api/health, /api/spec-summary, /api/auth/login,
/api/donors/register — cái cuối là đăng ký mới, chưa thể có token.
"""

from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth import decode_access_token, ROLE_DONOR, STAFF_ROLES

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    """Chủ thể đang gọi API — nhân viên cơ sở, quản trị, hoặc người hiến."""
    subject: str
    role: str
    facility_id: Optional[str] = None

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF_ROLES

    @property
    def is_donor(self) -> bool:
        return self.role == ROLE_DONOR


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_principal(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Principal:
    if creds is None:
        raise _unauthorized("Thiếu token — gửi header Authorization: Bearer <token>")

    try:
        claims = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token đã hết hạn, hãy đăng nhập lại")
    except jwt.PyJWTError:
        raise _unauthorized("Token không hợp lệ")

    return Principal(
        subject=claims.get("sub", ""),
        role=claims.get("role", ""),
        facility_id=claims.get("facility_id"),
    )


async def get_principal_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[Principal]:
    """
    Như `get_principal` nhưng KHÔNG chặn khi thiếu/hỏng token.

    Dùng cho `/donors/register`: endpoint đó phải mở cho người đăng ký lần đầu
    (chưa thể có token), nhưng khi app gọi lại để lấy token mới thì token cũ —
    nếu còn hạn — chính là bằng chứng "tôi là chủ hồ sơ này".
    """
    if creds is None:
        return None
    try:
        claims = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        return None
    return Principal(
        subject=claims.get("sub", ""),
        role=claims.get("role", ""),
        facility_id=claims.get("facility_id"),
    )


def require_roles(*roles: str):
    """Khoá endpoint theo vai trò: `Depends(require_roles(ROLE_ADMIN))`."""
    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Vai trò '{principal.role}' không được phép; cần {' hoặc '.join(roles)}",
            )
        return principal
    return dependency


require_staff = require_roles(*STAFF_ROLES)


def require_self_or_staff(principal: Principal, donor_id: str) -> None:
    """
    Người hiến chỉ thao tác được trên hồ sơ của chính mình; nhân viên cơ sở thì
    được trên mọi hồ sơ. Gọi trong thân hàm vì cần biết `donor_id` từ đường dẫn.
    """
    if principal.is_staff:
        return
    if principal.is_donor and principal.subject == donor_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Chỉ được thao tác trên hồ sơ của chính mình",
    )
