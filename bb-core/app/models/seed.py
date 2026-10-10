"""
BB-Core — Simulation data generator

Calibrated against verified public data:
- 146,329 whole blood units in 6 months at BV TMHH TP.HCM → daily collection rate
- ~220,000 components produced in 6 months → component ratio
- Seasonal scarcity: summer (Jun-Aug) and around Tet (Jan-Feb)
- Shelf life per TT 26/2013/TT-BYT
- Blood group distribution: O~45%, B~30%, A~20%, AB~5%; Rh(D)+ ~99.9%

All random seeds are deterministic for reproducibility.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, date, timezone
from typing import Optional

import numpy as np
from faker import Faker

from app.config import settings
from app.models.database import (
    Facility, BloodUnit, InventoryEvent, Donor, AppUser,
    ComponentCode, ABO, RhD, UnitStatus, FacilityTier,
)


fake = Faker("vi_VN")
Faker.seed(settings.sim_seed)
random.seed(settings.sim_seed)
np.random.seed(settings.sim_seed)

# ── Calibrated parameters (from verified data) ──────────────────

# BV TMHH TP.HCM: 146,329 whole blood units / 6 months → ~800/day avg
# 5 facilities seeded: share proportional to tier
_FACILITIES = [
    {"id": "fac-bv-tmhh",  "name": "Bệnh viện A", "tier": FacilityTier.REGIONAL,
     "lat": 10.7869, "lon": 106.6854, "daily_units": 520, "safety": {"RBC": 50, "PLT": 30, "FFP": 40}},
    {"id": "fac-bv-cho-ray", "name": "Bệnh viện B", "tier": FacilityTier.HOSPITAL,
     "lat": 10.7635, "lon": 106.6690, "daily_units": 140, "safety": {"RBC": 30, "PLT": 15, "FFP": 20}},
    {"id": "fac-bv-ung-buou", "name": "Bệnh viện C", "tier": FacilityTier.HOSPITAL,
     "lat": 10.7736, "lon": 106.6973, "daily_units": 70, "safety": {"RBC": 15, "PLT": 8, "FFP": 10}},
    {"id": "fac-bv-nhi-dong", "name": "Bệnh viện D", "tier": FacilityTier.HOSPITAL,
     "lat": 10.7905, "lon": 106.6940, "daily_units": 40, "safety": {"RBC": 10, "PLT": 10, "FFP": 5}},
    {"id": "fac-bv-pham-ngoc-thach", "name": "Bệnh viện E", "tier": FacilityTier.HOSPITAL,
     "lat": 10.7811, "lon": 106.6728, "daily_units": 30, "safety": {"RBC": 8, "PLT": 5, "FFP": 5}},
]

# Blood group distribution — Vietnamese population (Viện HH-TMTW)
_ABO_WEIGHTS = {"O": 0.45, "B": 0.30, "A": 0.20, "AB": 0.05}
_RH_POS_RATE = 0.999  # ~0.1% Rh(D) negative

# Component production ratio (from ~220k components / 146k whole blood)
# WB collected → split into RBC (~55%), PLT (~20%), FFP (~25%)
_COMPONENT_RATIOS = {
    ComponentCode.RBC:  0.55,
    ComponentCode.PLT:  0.20,
    ComponentCode.FFP:  0.25,
}

# Shelf life (days) — TT 26/2013/TT-BYT
_SHELF_LIFE = {
    ComponentCode.RBC:  42,
    ComponentCode.PLT:  5,   # Art 30
    ComponentCode.FFP: None,  # stored as months, handled separately
}

# Seasonal factors: summer scarcity (Jun-Aug) and Tet (Jan-Feb)
_SEASON_FACTOR = {
    1: 0.82,   # Tet
    2: 0.78,   # Tet aftermath
    3: 0.92,
    4: 0.96,
    5: 0.98,
    6: 0.88,   # Summer scarcity begins
    7: 0.82,   # Peak summer scarcity
    8: 0.85,   # Still scarce
    9: 0.95,
    10: 1.02,
    11: 1.05,
    12: 0.93,  # Holiday season
}


def _pick_abo_rh() -> tuple[ABO, RhD]:
    """Pick ABO/RhD based on Vietnamese population distribution."""
    abo = random.choices(list(_ABO_WEIGHTS.keys()), weights=list(_ABO_WEIGHTS.values()))[0]
    rh = RhD.POS if random.random() < _RH_POS_RATE else RhD.NEG
    return ABO(abo), rh


def _generate_isbt_din(collection_date: date, seq: int) -> str:
    """
    Generate ISBT 128-style Donation Identification Number.
    Format: VN[facility_code]YYYYDDDSEQ (not fully spec-compliant, but structured)
    """
    day_of_year = collection_date.timetuple().tm_yday
    return f"VNBV{collection_date.year}{day_of_year:03d}{seq:06d}"


def seed_facilities() -> list[Facility]:
    """Create 5 mock facilities in HCMC."""
    from geoalchemy2 import WKTElement

    facilities = []
    for f in _FACILITIES:
        geom = WKTElement(f"POINT({f['lon']} {f['lat']})", srid=4326)
        facilities.append(Facility(
            id=f["id"],
            name=f["name"],
            tier=f["tier"],
            geom=geom,
            opt_in=True,
            safety_threshold_json=f["safety"],
        ))
    return facilities


def generate_blood_units(
    facilities: list[Facility],
    start_date: date,
    days: int = 90,
) -> list[BloodUnit]:
    """
    Generate blood units with calibrated daily collection rates and seasonal variation.
    Simulates the full pipeline: collection → component preparation → inventory.
    """
    units = []
    seq = 1

    for day_offset in range(days):
        current_date = start_date + timedelta(days=day_offset)
        month = current_date.month
        season_factor = _SEASON_FACTOR.get(month, 1.0)

        # Add daily noise (Poisson-like)
        for fac_data in _FACILITIES:
            fac_id = fac_data["id"]
            base_daily = fac_data["daily_units"]
            # Poisson with seasonal factor
            daily_count = max(1, int(np.random.poisson(base_daily * season_factor / 10) * 10))
            daily_count = int(daily_count * 0.1)  # scale down for sim: ~10% of real volume

            for i in range(daily_count):
                # Cột thời gian trong models là timestamptz — sinh giá trị CÓ múi
                # giờ, nếu không asyncpg từ chối cả mẻ chèn đơn vị máu.
                collection_dt = datetime.combine(
                    current_date,
                    fake.time_object(end_datetime=None).replace(tzinfo=None),
                    tzinfo=timezone.utc,
                )

                # Each whole blood → produce components
                abo, rh = _pick_abo_rh()

                for comp_code, ratio in _COMPONENT_RATIOS.items():
                    if random.random() > ratio:
                        continue

                    shelf_days = _SHELF_LIFE[comp_code]
                    if shelf_days is None:
                        # FFP: 12 months at -18..-25°C (Art 33)
                        expires_at = collection_dt + timedelta(days=365)
                    else:
                        expires_at = collection_dt + timedelta(days=shelf_days)

                    # For PLT: effective usable window is ~3 days (collection + screening)
                    # but we store the regulatory 5-day expiry

                    unit = BloodUnit(
                        id=str(uuid.uuid4()),
                        isbt_din=_generate_isbt_din(current_date, seq),
                        component_code=comp_code,
                        abo=abo,
                        rh=rh,
                        volume_ml=_pick_volume(comp_code),
                        collected_at=collection_dt,
                        expires_at=expires_at,
                        # Quá hạn thì KHÔNG còn là AVAILABLE.
                        #
                        # Cửa sổ thu gom dài 90 ngày trong khi RBC chỉ sống 42
                        # ngày và PLT 5 ngày, nên phần đầu cửa sổ đương nhiên đã
                        # hết hạn. Để nguyên trạng thái AVAILABLE thì bảng Tổng
                        # quan đếm cả chúng vào "đơn vị khả dụng" — một con số
                        # không có thật — còn Ghép nguồn thì loại hết và trả về
                        # 0 nguồn tương hợp.
                        status=(UnitStatus.AVAILABLE
                                if expires_at > datetime.now(timezone.utc)
                                else UnitStatus.EXPIRED),
                        held_by_facility_id=fac_id,
                        irradiated=random.random() < 0.1 if comp_code == ComponentCode.RBC else False,
                        leukoreduced=random.random() < 0.7 if comp_code == ComponentCode.RBC else False,
                    )
                    units.append(unit)
                    seq += 1

    # Small deterministic demo set keeps both FEFO urgency windows populated
    # after a fresh seed, even when the random collection sample is sparse.
    now = datetime.now(timezone.utc)
    fefo_examples = [
        (ComponentCode.PLT, "fac-bv-cho-ray", ABO.O, RhD.POS, 8),
        (ComponentCode.RBC, "fac-bv-tmhh", ABO.A, RhD.POS, 18),
        (ComponentCode.PLT, "fac-bv-ung-buou", ABO.B, RhD.POS, 36),
        (ComponentCode.RBC, "fac-bv-nhi-dong", ABO.O, RhD.NEG, 60),
        (ComponentCode.RBC, "fac-bv-pham-ngoc-thach", ABO.AB, RhD.POS, 68),
        (ComponentCode.FFP, "fac-bv-cho-ray", ABO.O, RhD.POS, 144),
    ]
    for comp_code, facility_id, abo, rh, hours_remaining in fefo_examples:
        expires_at = now + timedelta(hours=hours_remaining)
        shelf_days = _SHELF_LIFE[comp_code] or 365
        collected_at = expires_at - timedelta(days=shelf_days)
        units.append(BloodUnit(
            id=str(uuid.uuid4()),
            isbt_din=_generate_isbt_din(collected_at.date(), seq),
            component_code=comp_code,
            abo=abo,
            rh=rh,
            volume_ml=_pick_volume(comp_code),
            collected_at=collected_at,
            expires_at=expires_at,
            status=UnitStatus.AVAILABLE,
            held_by_facility_id=facility_id,
            irradiated=False,
            leukoreduced=comp_code == ComponentCode.RBC,
        ))
        seq += 1

    return units


def _pick_volume(comp: ComponentCode) -> int:
    """Pick realistic volume in ml per component type."""
    volumes = {
        ComponentCode.RBC:  [250, 300, 350],      # per TT 26 Art 4: 250-450ml based on weight
        ComponentCode.PLT:  [250, 300, 350],        # apheresis unit
        ComponentCode.FFP:  [200, 250, 300],        # FFP volume
    }
    return random.choice(volumes.get(comp, [300]))


def generate_donors(count: int = 500) -> list[Donor]:
    """
    Generate mock donors in HCMC area.
    Uses H3 geocells (~1 km) with TTL, NOT raw coordinates.
    """
    import h3

    donors = []
    # HCMC center area lat/lon range
    h3_res = settings.h3_resolution  # ~1 km

    for i in range(count):
        abo, rh = _pick_abo_rh()
        # Random point in HCMC area
        lat = 10.76 + random.uniform(-0.05, 0.05)
        lon = 106.66 + random.uniform(-0.04, 0.04)
        geocell = h3.latlng_to_cell(lat, lon, h3_res)

        # Last donation: random within last 12 months
        days_ago = random.randint(14, 365)  # min 2 weeks (Art 6 for PLT)

        donor = Donor(
            id=f"donor-{i+1:04d}",
            abo=abo,
            rh=rh,
            last_donation_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            verified=random.random() < 0.8,
            geocell_h3=geocell,
            geocell_ttl=datetime.now(timezone.utc) + timedelta(hours=random.randint(1, 72)),
            birth_year=random.randint(1970, 2006),  # 18-55 years old
            weight_kg=random.choice([45, 48, 50, 52, 55, 58, 60, 62, 65, 68, 70, 75]),
            sex=random.choice(["M", "F"]),
        )
        donors.append(donor)

    return donors


def generate_inventory_events(units: list[BloodUnit]) -> list[InventoryEvent]:
    """Generate received events for all blood units."""
    events = []
    for unit in units:
        event = InventoryEvent(
            id=str(uuid.uuid4()),
            unit_id=unit.id,
            event_type="received",
            at=unit.collected_at,
            actor_id="system-seed",
            note=f"Unit {unit.isbt_din} received at {unit.held_by_facility_id}",
        )
        events.append(event)
    return events


# Tài khoản BB-Console cho dữ liệu mẫu. Mật khẩu để trong mã nguồn là CHẤP NHẬN
# ĐƯỢC vì đây là dữ liệu mô phỏng của đồ án; khi chạy thật phải đổi ngay.
_USERS = [
    {"username": "admin", "password": "bloodblink@2026", "role": "admin",
     "full_name": "Quản trị hệ thống", "facility_id": None},
    {"username": "choray", "password": "choray@2026", "role": "facility_staff",
     "full_name": "Khoa Huyết học — Bệnh viện B", "facility_id": "fac-bv-cho-ray"},
    {"username": "tmhh", "password": "tmhh@2026", "role": "facility_staff",
     "full_name": "Bệnh viện A", "facility_id": "fac-bv-tmhh"},
    {"username": "ungbuou", "password": "ungbuou@2026", "role": "facility_staff",
     "full_name": "Bệnh viện C", "facility_id": "fac-bv-ung-buou"},
    {"username": "nhidong", "password": "nhidong@2026", "role": "facility_staff",
     "full_name": "Bệnh viện D", "facility_id": "fac-bv-nhi-dong"},
    {"username": "phamngocthach", "password": "pnt@2026", "role": "facility_staff",
     "full_name": "Bệnh viện E", "facility_id": "fac-bv-pham-ngoc-thach"},
]


def seed_users() -> list[AppUser]:
    """Tài khoản đăng nhập BB-Console — một quản trị + mỗi cơ sở một tài khoản."""
    from app.services.auth import hash_password

    return [
        AppUser(
            id=f"user-{u['username']}",
            username=u["username"],
            password_hash=hash_password(u["password"]),
            role=u["role"],
            facility_id=u["facility_id"],
            full_name=u["full_name"],
            active=True,
        )
        for u in _USERS
    ]


def generate_all():
    """Main entry point — generate all seed data."""
    # Neo cửa sổ thu gom vào HÔM NAY, không dùng `sim_start_date`.
    #
    # `sim_start_date` là mốc cố định của bộ mô phỏng (bb-sim) — nó cần tái lập
    # được nên phải cố định. Nhưng dùng chính mốc đó để sinh tồn kho thì kho già
    # đi theo thời gian thực: RBC hạn 42 ngày, PLT hạn 5 ngày, nên seed mốc 2025
    # đem chạy năm 2026 cho ra 94% đơn vị ĐÃ HẾT HẠN mà vẫn mang trạng thái
    # AVAILABLE — bảng Tổng quan khoe mấy nghìn đơn vị "khả dụng" trong khi
    # Ghép nguồn không tìm ra nổi một đơn vị dùng được.
    #
    # Đặt ngày cuối của cửa sổ là hôm nay thì kho luôn có phổ hạn dùng thật:
    # phần lớn còn hạn, một ít sắp hết, một ít vừa quá hạn.
    start = date.today() - timedelta(days=settings.sim_days - 1)

    print(f"🌱 Seeding BLOODBLINK database (seed={settings.sim_seed}, start={start} → hôm nay, days={settings.sim_days})")

    facilities = seed_facilities()
    print(f"   ✓ {len(facilities)} facilities")

    units = generate_blood_units(facilities, start, settings.sim_days)
    print(f"   ✓ {len(units)} blood units")

    donors = generate_donors(500)
    print(f"   ✓ {len(donors)} donors")

    events = generate_inventory_events(units)
    print(f"   ✓ {len(events)} inventory events")

    users = seed_users()
    print(f"   ✓ {len(users)} tài khoản BB-Console")

    return {
        "facilities": facilities,
        "blood_units": units,
        "donors": donors,
        "inventory_events": events,
        "users": users,
    }
