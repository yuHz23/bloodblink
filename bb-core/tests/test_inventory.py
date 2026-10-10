"""
Hồi quy cho lỗi 500 của `GET /api/inventory/` trên Postgres: cột `status` là
enum với label là TÊN VIẾT HOA (AVAILABLE…), còn endpoint từng so sánh trực
tiếp với chuỗi "available" khiến asyncpg từ chối cả truy vấn.

Trên SQLite (CSDL test) chuỗi sai không gây lỗi mà chỉ im lặng trả rỗng, nên
các test ở đây phải kiểm filter THẬT SỰ khớp đơn vị, chứ không chỉ HTTP 200.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.database import ABO, RhD, BloodUnit, ComponentCode, UnitStatus

pytestmark = pytest.mark.asyncio

_NOW = datetime.now(timezone.utc)


async def _add_unit(db_session, *, din: str, status: UnitStatus = UnitStatus.AVAILABLE):
    db_session.add(BloodUnit(
        id=str(uuid.uuid4()),
        isbt_din=din,
        component_code=ComponentCode.RBC,
        abo=ABO.O,
        rh=RhD.POS,
        volume_ml=300,
        collected_at=_NOW - timedelta(days=5),
        expires_at=_NOW + timedelta(days=30),
        status=status,
        held_by_facility_id="fac-test",
    ))
    await db_session.commit()


class TestInventoryStatusFilter:
    async def test_loc_mac_dien_tra_dung_don_vi(self, staff, db_session):
        await _add_unit(db_session, din="VNBV2026284000001")

        r = await staff.get("/api/inventory/")
        assert r.status_code == 200, r.text
        assert any(u["isbt_din"] == "VNBV2026284000001" for u in r.json()), \
            "filter trạng thái mặc định phải khớp được đơn vị AVAILABLE"

    async def test_status_khong_hop_le_tra_422(self, staff, db_session):
        await _add_unit(db_session, din="VNBV2026284000002")

        r = await staff.get("/api/inventory/", params={"status": "khong_hop_le"})
        assert r.status_code == 422, "giá trị trạng thái lạ phải bị từ chối rõ ràng"

    async def test_don_vi_da_loai_khong_xuat_hien(self, staff, db_session):
        await _add_unit(db_session, din="VNBV2026284000003", status=UnitStatus.DISCARDED)

        r = await staff.get("/api/inventory/")
        assert r.status_code == 200
        assert r.json() == [], "đơn vị DISCARDED không được lọt qua filter available"