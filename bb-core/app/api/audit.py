"""
BB-Core — Đọc và kiểm tra nhật ký ghi vết.

Chỉ quản trị đọc được: nhật ký cho biết cơ sở nào tra ai lúc nào, tự nó đã là
dữ liệu nhạy cảm.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.database import AuditLog
from app.services import audit as audit_service
from app.services.auth import ROLE_ADMIN
from app.api.deps import Principal, require_roles
from app.api.schemas import AuditEntryOut, AuditVerifyOut

router = APIRouter()

require_admin = require_roles(ROLE_ADMIN)


@router.get("", response_model=list[AuditEntryOut])
async def list_audit(
    action: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
):
    """Nhật ký mới nhất trước. Lọc theo hành động hoặc chủ thể."""
    stmt = select(AuditLog).order_by(desc(AuditLog.at), desc(AuditLog.id)).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)

    rows = (await db.execute(stmt)).scalars().all()
    return [
        AuditEntryOut(
            id=r.id, at=r.at, actor=r.actor, action=r.action,
            payload=r.payload_json or {}, hash=r.hash, prev_hash=r.prev_hash,
        )
        for r in rows
    ]


@router.get("/verify", response_model=AuditVerifyOut)
async def verify_audit(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
):
    """
    Kiểm tra chuỗi băm còn liền mạch không.

    Trả `ok=false` kèm mã dòng hỏng đầu tiên nếu có ai sửa hoặc xoá giữa chừng.
    """
    return AuditVerifyOut(**await audit_service.verify_chain(db))
