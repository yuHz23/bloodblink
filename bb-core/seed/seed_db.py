#!/usr/bin/env python3
"""
BB-Core database seed script.

Usage:
    cd bb-core
    python -m seed.seed_db

Requires PostgreSQL with PostGIS and TimescaleDB extensions.
Creates tables, seeds facilities and generates simulation data.
"""

import asyncio
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.database import Base
from app.models.seed import generate_all


async def create_tables(engine):
    """
    Create all tables and (nếu có) TimescaleDB hypertable.

    PostGIS là bắt buộc — `facility.geom` là cột Geometry. TimescaleDB thì không:
    nó chỉ tăng tốc bảng `shipment_reading`, nên trên máy chủ tạm chỉ có Postgres
    thuần ta bỏ qua và ghi rõ ra màn hình thay vì để seed chết giữa chừng.
    """
    async with engine.begin() as conn:
        await conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS postgis"))

    has_timescale = True
    try:
        async with engine.begin() as conn:
            await conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
    except Exception as exc:  # extension chưa cài trên máy chủ này
        has_timescale = False
        print(f"   ⚠️  Bỏ qua TimescaleDB ({type(exc).__name__}) — shipment_reading là bảng thường")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if has_timescale:
        async with engine.begin() as conn:
            await conn.execute(sa_text(
                "SELECT create_hypertable('shipment_reading', 'time', "
                "if_not_exists => TRUE)"
            ))


async def seed_database():
    """Main seed function."""
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print("🏗️  Creating tables...")
    await create_tables(engine)
    print("   ✓ Tables created")

    print("🌱 Seeding data...")
    data = generate_all()

    async with async_session() as session:
        # Insert facilities first (foreign key dependency)
        for fac in data["facilities"]:
            session.add(fac)
        await session.commit()
        print(f"   ✓ {len(data['facilities'])} facilities")

        # Insert blood units in batches (large dataset)
        batch_size = 500
        for i in range(0, len(data["blood_units"]), batch_size):
            batch = data["blood_units"][i:i + batch_size]
            session.add_all(batch)
            await session.commit()
        print(f"   ✓ {len(data['blood_units'])} blood units")

        # Insert donors
        session.add_all(data["donors"])
        await session.commit()
        print(f"   ✓ {len(data['donors'])} donors")

        # Insert inventory events in batches
        for i in range(0, len(data["inventory_events"]), batch_size):
            batch = data["inventory_events"][i:i + batch_size]
            session.add_all(batch)
            await session.commit()
        print(f"   ✓ {len(data['inventory_events'])} inventory events")

        # Tài khoản đăng nhập BB-Console
        session.add_all(data["users"])
        await session.commit()
        print(f"   ✓ {len(data['users'])} tài khoản BB-Console")

    await engine.dispose()
    print("\n✅ Seed complete!")


if __name__ == "__main__":
    asyncio.run(seed_database())