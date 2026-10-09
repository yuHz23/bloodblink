"""Add or refresh anonymous mock donor profiles for the map demo.

Run from ``bb-core`` with ``python -m seed.seed_map_donors``. This only writes
the clearly prefixed ``mock-map-*`` donors and never clears real donor rows.
No names, phone numbers, or GPS coordinates are created.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import h3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.database import ABO, Donor, Facility, RhD


# ID, facility, ABO, RhD, sex, birth year, weight kg, days since last donation.
# Balanced groups are intentional so each map filter has a visible demo cluster.
MOCK_PROFILES = (
    ("mock-map-cho-o-01", "fac-bv-cho-ray", ABO.O, RhD.POS, "F", 1994, 55, 140),
    ("mock-map-cho-o-02", "fac-bv-cho-ray", ABO.O, RhD.POS, "M", 1988, 68, 210),
    ("mock-map-cho-o-03", "fac-bv-cho-ray", ABO.O, RhD.POS, "F", 1999, 52, 95),
    ("mock-map-cho-o-04", "fac-bv-cho-ray", ABO.O, RhD.POS, "M", 1992, 75, 180),
    ("mock-map-tmhh-a-01", "fac-bv-tmhh", ABO.A, RhD.POS, "M", 1985, 70, 160),
    ("mock-map-tmhh-a-02", "fac-bv-tmhh", ABO.A, RhD.POS, "F", 1996, 58, 120),
    ("mock-map-tmhh-a-03", "fac-bv-tmhh", ABO.A, RhD.POS, "M", 2000, 62, 240),
    ("mock-map-tmhh-a-04", "fac-bv-tmhh", ABO.A, RhD.POS, "F", 1990, 54, 200),
    ("mock-map-ung-b-01", "fac-bv-ung-buou", ABO.B, RhD.POS, "F", 1993, 60, 150),
    ("mock-map-ung-b-02", "fac-bv-ung-buou", ABO.B, RhD.POS, "M", 1987, 72, 190),
    ("mock-map-ung-b-03", "fac-bv-ung-buou", ABO.B, RhD.POS, "F", 2001, 50, 110),
    ("mock-map-ung-b-04", "fac-bv-ung-buou", ABO.B, RhD.POS, "M", 1995, 65, 230),
    ("mock-map-pnt-ab-01", "fac-bv-pham-ngoc-thach", ABO.AB, RhD.POS, "M", 1989, 74, 170),
    ("mock-map-pnt-ab-02", "fac-bv-pham-ngoc-thach", ABO.AB, RhD.POS, "F", 1997, 56, 130),
    ("mock-map-pnt-ab-03", "fac-bv-pham-ngoc-thach", ABO.AB, RhD.POS, "M", 1991, 67, 220),
    ("mock-map-pnt-ab-04", "fac-bv-pham-ngoc-thach", ABO.AB, RhD.POS, "F", 1986, 61, 100),
    ("mock-map-nhi-o-neg-01", "fac-bv-nhi-dong", ABO.O, RhD.NEG, "F", 1992, 55, 180),
    ("mock-map-nhi-o-neg-02", "fac-bv-nhi-dong", ABO.O, RhD.NEG, "M", 1984, 78, 250),
    ("mock-map-nhi-o-neg-03", "fac-bv-nhi-dong", ABO.O, RhD.NEG, "F", 2000, 52, 125),
    ("mock-map-nhi-o-neg-04", "fac-bv-nhi-dong", ABO.O, RhD.NEG, "M", 1996, 69, 200),
)

# Public facility coordinates are used only to choose the containing H3 cell.
# Mock donor points are jittered within that coarse cell on the console.
FACILITY_COORDS = {
    "fac-bv-cho-ray": (10.7635, 106.6690),
    "fac-bv-tmhh": (10.7869, 106.6854),
    "fac-bv-ung-buou": (10.7736, 106.6973),
    "fac-bv-nhi-dong": (10.7905, 106.6940),
    "fac-bv-pham-ngoc-thach": (10.7811, 106.6728),
}


async def seed_map_donors() -> tuple[int, int]:
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    added = refreshed = 0
    now = datetime.now(timezone.utc)
    try:
        async with session_factory() as session:
            facility_ids = set((await session.scalars(select(Facility.id))).all())
            missing = sorted({row[1] for row in MOCK_PROFILES} - facility_ids)
            if missing:
                raise RuntimeError(f"Seed base facilities first; missing: {', '.join(missing)}")

            for donor_id, facility_id, abo, rh, sex, birth_year, weight, days_ago in MOCK_PROFILES:
                lat, lon = FACILITY_COORDS[facility_id]
                donor = await session.get(Donor, donor_id)
                if donor is None:
                    donor = Donor(id=donor_id)
                    session.add(donor)
                    added += 1
                else:
                    refreshed += 1

                donor.abo = abo
                donor.rh = rh
                donor.sex = sex
                donor.birth_year = birth_year
                donor.weight_kg = weight
                donor.last_donation_at = now - timedelta(days=days_ago)
                donor.verified = True
                donor.geocell_h3 = h3.latlng_to_cell(lat, lon, settings.h3_resolution)
                donor.geocell_ttl = now + timedelta(days=7)

            await session.commit()
    finally:
        await engine.dispose()

    return added, refreshed


if __name__ == "__main__":
    new_count, refreshed_count = asyncio.run(seed_map_donors())
    print(
        f"Mock map donors ready: {new_count} added, {refreshed_count} refreshed. "
        "These profiles contain no real names, phone numbers, or GPS coordinates."
    )
