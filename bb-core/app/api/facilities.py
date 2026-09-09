"""
BB-Core — Danh sách cơ sở y tế.

BB-Console trước đây phải cắm cứng 5 bệnh viện trong `pages/Routing.tsx`; trang
"Tìm người hiến" cần biết ô lưới H3 của cơ sở nên đọc thẳng từ đây.
"""

import h3
from fastapi import APIRouter, Depends
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models.database import Facility
from app.api.deps import Principal, get_principal
from app.api.schemas import FacilityOut

router = APIRouter()


@router.get("", response_model=list[FacilityOut])
async def list_facilities(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Toạ độ cơ sở là dữ liệu công khai — kèm luôn ô lưới H3 để đỡ tính lại."""
    facilities = (await db.execute(select(Facility).order_by(Facility.name))).scalars().all()

    out = []
    for f in facilities:
        point = to_shape(f.geom) if f.geom is not None else None
        lat = point.y if point else 0.0
        lon = point.x if point else 0.0
        out.append(FacilityOut(
            id=f.id,
            name=f.name,
            tier=f.tier.value,
            lat=lat,
            lon=lon,
            opt_in=f.opt_in,
            safety_threshold=f.safety_threshold_json or {},
            h3_cell=h3.latlng_to_cell(lat, lon, settings.h3_resolution) if point else None,
        ))
    return out
