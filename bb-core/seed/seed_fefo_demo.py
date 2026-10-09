"""Safely add a small, clearly labeled FEFO demo set to an existing database.

Run from ``bb-core`` with ``python -m seed.seed_fefo_demo``. This script only
inserts missing demo rows; it does not clear or replace inventory.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.database import (
    ABO,
    BloodUnit,
    ComponentCode,
    Facility,
    InventoryEvent,
    RhD,
    UnitStatus,
)


DEMO_UNITS = (
    # DIN, facility, component, ABO, RhD, hours to expiry, shelf life days
    ("MOCK-FEFO-PLT-08H", "fac-bv-cho-ray", ComponentCode.PLT, ABO.O, RhD.POS, 8, 5),
    ("MOCK-FEFO-RBC-18H", "fac-bv-tmhh", ComponentCode.RBC, ABO.A, RhD.POS, 18, 42),
    ("MOCK-FEFO-PLT-36H", "fac-bv-ung-buou", ComponentCode.PLT, ABO.B, RhD.POS, 36, 5),
    ("MOCK-FEFO-RBC-60H", "fac-bv-nhi-dong", ComponentCode.RBC, ABO.O, RhD.NEG, 60, 42),
    ("MOCK-FEFO-RBC-68H", "fac-bv-pham-ngoc-thach", ComponentCode.RBC, ABO.AB, RhD.POS, 68, 42),
    ("MOCK-FEFO-FFP-144H", "fac-bv-cho-ray", ComponentCode.FFP, ABO.O, RhD.POS, 144, 365),
)


async def seed_fefo_demo() -> int:
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    added = 0
    now = datetime.now(timezone.utc)

    try:
        async with session_factory() as session:
            facility_ids = set((await session.scalars(select(Facility.id))).all())
            for din, facility_id, component, abo, rh, hours, shelf_days in DEMO_UNITS:
                if facility_id not in facility_ids:
                    raise RuntimeError(
                        f"Facility {facility_id} is missing. Seed the base facilities first."
                    )

                exists = await session.scalar(
                    select(BloodUnit.id).where(BloodUnit.isbt_din == din)
                )
                if exists:
                    continue

                expires_at = now + timedelta(hours=hours)
                unit_id = f"demo-{din.lower()}"
                session.add(BloodUnit(
                    id=unit_id,
                    isbt_din=din,
                    component_code=component,
                    abo=abo,
                    rh=rh,
                    volume_ml=300,
                    collected_at=expires_at - timedelta(days=shelf_days),
                    expires_at=expires_at,
                    status=UnitStatus.AVAILABLE,
                    held_by_facility_id=facility_id,
                    irradiated=False,
                    leukoreduced=component == ComponentCode.RBC,
                ))
                session.add(InventoryEvent(
                    id=f"event-{unit_id}",
                    unit_id=unit_id,
                    event_type="received",
                    at=now,
                    actor_id="fefo-demo-seed",
                    note="Dữ liệu tồn kho mô phỏng FEFO; không dùng cho điều phối thực tế.",
                ))
                added += 1

            await session.commit()
    finally:
        await engine.dispose()

    return added


if __name__ == "__main__":
    count = asyncio.run(seed_fefo_demo())
    print(f"Added {count} FEFO demo units; existing inventory was preserved.")
