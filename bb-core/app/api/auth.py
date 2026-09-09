"""BB-Core — Đăng nhập BB-Console."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models.database import AppUser, Facility
from app.services import audit
from app.services.auth import verify_password, create_access_token
from app.api.deps import Principal, get_principal
from app.api.schemas import LoginIn, TokenOut, MeOut

router = APIRouter()


@router.post("/login", response_model=TokenOut)
async def login(req: LoginIn, db: AsyncSession = Depends(get_db)):
    """
    Đăng nhập bằng tài khoản nhân viên cơ sở y tế.

    Trả cùng một thông điệp cho "sai tên" và "sai mật khẩu" để không tiết lộ
    tài khoản nào có thật.
    """
    stmt = select(AppUser).where(AppUser.username == req.username.strip().lower())
    user = (await db.execute(stmt)).scalar_one_or_none()

    if user is None or not verify_password(req.password, user.password_hash):
        # Ghi cả lần đăng nhập hỏng: dò mật khẩu phải để lại dấu vết.
        await audit.record(db, req.username.strip().lower()[:64], audit.LOGIN_FAILED,
                           {"reason": "sai tài khoản hoặc mật khẩu"})
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai tên đăng nhập hoặc mật khẩu",
        )
    if not user.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tài khoản đã bị khoá")

    token = create_access_token(user.id, user.role, user.facility_id)
    await audit.record(db, user.id, audit.LOGIN,
                       {"role": user.role, "facility_id": user.facility_id})
    await db.commit()

    facility_name = None
    if user.facility_id:
        facility = await db.get(Facility, user.facility_id)
        facility_name = facility.name if facility else None

    return TokenOut(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
        role=user.role,
        subject=user.id,
        username=user.username,
        full_name=user.full_name,
        facility_id=user.facility_id,
        facility_name=facility_name,
    )


@router.get("/me", response_model=MeOut)
async def me(principal: Principal = Depends(get_principal)):
    """Xác nhận token còn hiệu lực — BB-Console gọi lúc khởi động."""
    return MeOut(
        subject=principal.subject,
        role=principal.role,
        facility_id=principal.facility_id,
    )
