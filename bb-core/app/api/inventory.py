"""BB-Core — Inventory API: list blood units with expiry tracking."""

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.database import BloodUnit, Facility, ComponentCode, UnitStatus
from app.api.schemas import BloodUnitOut, HoursRemainingOut, InventoryQuery

router = APIRouter()


@router.get("/", response_model=list[BloodUnitOut])
async def list_inventory(
    component: Optional[str] = None,
    abo: Optional[str] = None,
    rh: Optional[str] = None,
    facility_id: Optional[str] = None,
    status: str = "available",
    expires_within_hours: Optional[float] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List blood units in inventory with optional filters."""
    stmt = select(BloodUnit)

    if component:
        stmt = stmt.where(BloodUnit.component_code == component)
    if abo:
        stmt = stmt.where(BloodUnit.abo == abo)
    if rh:
        stmt = stmt.where(BloodUnit.rh == rh)
    if facility_id:
        stmt = stmt.where(BloodUnit.held_by_facility_id == facility_id)
    if status:
        stmt = stmt.where(BloodUnit.status == status)
    if expires_within_hours is not None:
        cutoff = datetime.now(timezone.utc) + timedelta(hours=expires_within_hours)
        stmt = stmt.where(BloodUnit.expires_at <= cutoff)

    stmt = stmt.order_by(BloodUnit.expires_at.asc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    units = result.scalars().all()
    return units


@router.get("/expiring", response_model=list[HoursRemainingOut])
async def list_expiring(
    component: Optional[str] = None,
    within_hours: float = Query(default=48.0, ge=1),
    facility_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    List blood units expiring within N hours, with FEFO priority.
    This is the core inventory view for BB-Console.
    """
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=within_hours)

    stmt = select(BloodUnit).where(
        and_(
            BloodUnit.status == UnitStatus.AVAILABLE,
            BloodUnit.expires_at <= cutoff,
            BloodUnit.expires_at > now,
        )
    )
    if component:
        stmt = stmt.where(BloodUnit.component_code == component)
    if facility_id:
        stmt = stmt.where(BloodUnit.held_by_facility_id == facility_id)

    stmt = stmt.order_by(BloodUnit.expires_at.asc()).limit(limit)
    result = await db.execute(stmt)
    units = result.scalars().all()

    out = []
    for u in units:
        hours_left = (u.expires_at - now).total_seconds() / 3600
        days_left = hours_left / 24

        if hours_left <= 0:
            urgency = "expired"
        elif u.component_code == ComponentCode.PLT and hours_left < 24:
            urgency = "critical"  # PLT: <24h is critical (5-day window)
        elif u.component_code == ComponentCode.RBC and hours_left < 72:
            urgency = "warning"   # RBC: <3 days is warning
        elif hours_left < 48:
            urgency = "warning"
        else:
            urgency = "normal"

        out.append(HoursRemainingOut(
            unit=BloodUnitOut.model_validate(u),
            hours_remaining=round(hours_left, 1),
            days_remaining=round(days_left, 1),
            urgency=urgency,
        ))

    return out


@router.get("/by-facility")
async def inventory_by_facility(
    component_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Tồn kho theo CƠ SỞ × NHÓM MÁU — dữ liệu để tô bản đồ.

    `/summary` đã có `by_facility_component` nhưng gộp hết nhóm máu lại, nên
    không trả lời được câu duy nhất mà người điều phối cần khi nhìn bản đồ:
    "chỗ nào đang có O− ngay lúc này".

    Chỉ đếm đơn vị CÒN HẠN. Đơn vị quá hạn tuy vẫn nằm trong kho nhưng không
    dùng được, tô lên bản đồ là chỉ sai chỗ cho người đi lấy.
    """
    now = datetime.now(timezone.utc)

    stmt = (
        select(
            BloodUnit.held_by_facility_id,
            BloodUnit.abo,
            BloodUnit.rh,
            BloodUnit.component_code,
            func.count(BloodUnit.id).label("count"),
        )
        .where(
            BloodUnit.status == UnitStatus.AVAILABLE,
            BloodUnit.expires_at > now,
        )
        .group_by(
            BloodUnit.held_by_facility_id,
            BloodUnit.abo,
            BloodUnit.rh,
            BloodUnit.component_code,
        )
    )
    if component_code:
        try:
            stmt = stmt.where(BloodUnit.component_code == ComponentCode(component_code.upper()))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Chế phẩm không hợp lệ: {component_code}")

    rows = (await db.execute(stmt)).all()
    return [
        {
            "facility_id": r.held_by_facility_id,
            "abo": r.abo.value,
            "rh": r.rh.value,
            "blood_type": f"{r.abo.value}{r.rh.value}",
            "component": r.component_code.value,
            "count": r.count,
        }
        for r in rows
    ]


@router.get("/summary")
async def inventory_summary(db: AsyncSession = Depends(get_db)):
    """
    Cluster-wide inventory summary — the main BB-Console dashboard view.
    Returns counts by component, ABO, RhD, and facility.
    """
    now = datetime.now(timezone.utc)

    # Count by component and status
    stmt = (
        select(
            BloodUnit.component_code,
            BloodUnit.status,
            func.count(BloodUnit.id).label("count"),
        )
        .group_by(BloodUnit.component_code, BloodUnit.status)
        .order_by(BloodUnit.component_code, BloodUnit.status)
    )
    result = await db.execute(stmt)
    by_component_status = [
        {"component": row.component_code.value, "status": row.status.value, "count": row.count}
        for row in result
    ]

    # Count by ABO/Rh
    stmt = (
        select(
            BloodUnit.abo,
            BloodUnit.rh,
            func.count(BloodUnit.id).label("count"),
        )
        .where(BloodUnit.status == UnitStatus.AVAILABLE)
        .group_by(BloodUnit.abo, BloodUnit.rh)
        .order_by(BloodUnit.abo, BloodUnit.rh)
    )
    result = await db.execute(stmt)
    by_blood_type = [
        {"abo": row.abo.value, "rh": row.rh.value, "count": row.count}
        for row in result
    ]

    # Expiring within 24h
    stmt = select(func.count(BloodUnit.id)).where(
        and_(
            BloodUnit.status == UnitStatus.AVAILABLE,
            BloodUnit.expires_at <= now + timedelta(hours=24),
            BloodUnit.expires_at > now,
        )
    )
    result = await db.execute(stmt)
    expiring_24h = result.scalar() or 0

    # Expiring within 72h
    stmt = select(func.count(BloodUnit.id)).where(
        and_(
            BloodUnit.status == UnitStatus.AVAILABLE,
            BloodUnit.expires_at <= now + timedelta(hours=72),
            BloodUnit.expires_at > now,
        )
    )
    result = await db.execute(stmt)
    expiring_72h = result.scalar() or 0

    # By facility
    stmt = (
        select(
            BloodUnit.held_by_facility_id,
            BloodUnit.component_code,
            func.count(BloodUnit.id).label("count"),
        )
        .where(BloodUnit.status == UnitStatus.AVAILABLE)
        .group_by(BloodUnit.held_by_facility_id, BloodUnit.component_code)
        .order_by(BloodUnit.held_by_facility_id)
    )
    result = await db.execute(stmt)
    by_facility = [
        {"facility_id": row.held_by_facility_id, "component": row.component_code.value, "count": row.count}
        for row in result
    ]

    return {
        "by_component_status": by_component_status,
        "by_blood_type": by_blood_type,
        "by_facility_component": by_facility,
        "expiring_within_24h": expiring_24h,
        "expiring_within_72h": expiring_72h,
        "total_available": sum(r["count"] for r in by_component_status if r["status"] == "available"),
    }