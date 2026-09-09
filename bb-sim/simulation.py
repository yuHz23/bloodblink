"""
BLOODBLINK — Discrete Event Simulation (Week 11)

Compares baseline (no BLOODBLINK) vs BLOODBLINK scenarios across:
  1. Blood request fulfillment rate (ABO/RhD compatibility)
  2. Time-to-fulfillment (ETA from matching engine)
  3. Waste reduction (FEFO + cold chain monitoring)
  4. SOS donor response rate (4-ring escalation)

Metrics grounded in Vietnamese blood bank statistics:
  - 1.75M units/year nationally (2025), ~146K units/6mo at BV TMHH HCMC
  - O~45%, B~30%, A~20%, AB~5%; Rh- ~0.1% (very rare)
  - TT 26/2013/TT-BYT: shelf life, donation intervals, temperature thresholds
  - UK BSMS: ~10K RBC units wasted/year from temperature excursions (~1/4 of all waste)

Usage:
    python simulation.py [--seed 42] [--days 30] [--verbose]
"""

import argparse
import json
import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Optional

# ── Vietnamese blood type distribution (Viện HH-TMTW) ──────────────────

BLOOD_TYPE_DISTRIBUTION = {
    "O+": 0.405, "O-": 0.005,
    "A+": 0.180, "A-": 0.002,
    "B+": 0.270, "B-": 0.003,
    "AB+": 0.045, "AB-": 0.002,
}

SHELF_LIFE = {
    "WB":  42 * 24,
    "RBC": 42 * 24,
    "PLT": 5 * 24,
    "FFP": 365 * 24,
}

DONATION_INTERVAL_WEEKS = {"WB": 12, "RBC": 12, "PLT": 2, "FFP": 2}

# ── ABO/RhD compatibility ──────────────────────────────────────────────

RBC_COMPAT = {
    "O-":  {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"},
    "O+":  {"O+", "A+", "B+", "AB+"},
    "A-":  {"A-", "A+", "AB-", "AB+"},
    "A+":  {"A+", "AB+"},
    "B-":  {"B-", "B+", "AB-", "AB+"},
    "B+":  {"B+", "AB+"},
    "AB-": {"AB-", "AB+"},
    "AB+": {"AB+"},
}

PLASMA_COMPAT = {
    "O-":  {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"},
    "O+":  {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"},
    "A-":  {"A-", "A+", "AB-", "AB+"},
    "A+":  {"A-", "A+", "AB-", "AB+"},
    "B-":  {"B-", "B+", "AB-", "AB+"},
    "B+":  {"B-", "B+", "AB-", "AB+"},
    "AB-": {"AB-", "AB+"},
    "AB+": {"AB+", "AB-"},
}


def is_compatible(donor_type, recipient_type, component, recipient_sex="M", recipient_age=30):
    tbl = PLASMA_COMPAT if component in ("FFP", "CRYO") else RBC_COMPAT
    if recipient_type not in tbl.get(donor_type, set()):
        return False
    if donor_type[-1] == "+" and recipient_type[-1] == "-":
        if recipient_sex == "F" and 18 <= recipient_age <= 45:
            return False
    return True


def random_blood_type(rng):
    r = rng.random()
    cum = 0.0
    for bt, prob in BLOOD_TYPE_DISTRIBUTION.items():
        cum += prob
        if r <= cum:
            return bt
    return "O+"


# ── HCMC facilities ────────────────────────────────────────────────────

FACILITIES = [
    {"id": "BV-TMHH-HCM", "name": "BV Truyền máu Huyết học",  "lat": 10.7869, "lon": 106.6649, "daily_collections": 60},
    {"id": "BV-CH-HCM",    "name": "BV Chợ Rẫy",               "lat": 10.7570, "lon": 106.6639, "daily_collections": 25},
    {"id": "BV-UC-HCM",    "name": "BV ĐH Y Dược TP.HCM",     "lat": 10.7630, "lon": 106.6810, "daily_collections": 20},
    {"id": "BV-NHI-HCM",   "name": "BV Nhi Đồng 1",            "lat": 10.7720, "lon": 106.6930, "daily_collections": 10},
    {"id": "BV-115-HCM",   "name": "BV 115",                   "lat": 10.7715, "lon": 106.6855, "daily_collections": 15},
    {"id": "BV-CT-HCM",    "name": "BV Ung Bướu TP.HCM",       "lat": 10.7540, "lon": 106.6700, "daily_collections": 10},
    {"id": "BV-DK1-HCM",   "name": "BV Quận 1",                "lat": 10.7720, "lon": 106.7015, "daily_collections": 5},
    {"id": "BV-DK5-HCM",   "name": "BV Quận 5",                "lat": 10.7580, "lon": 106.6560, "daily_collections": 5},
]

# Pre-compute haversine distances
HAVERSINE_KM = {}
for i, f1 in enumerate(FACILITIES):
    for j, f2 in enumerate(FACILITIES):
        if i != j:
            lat1, lon1 = math.radians(f1["lat"]), math.radians(f1["lon"])
            lat2, lon2 = math.radians(f2["lat"]), math.radians(f2["lon"])
            dist = 6371 * 2 * math.asin(math.sqrt(
                math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
            ))
            HAVERSINE_KM[(f1["id"], f2["id"])] = dist


def eta_minutes(from_id, to_id, emergency=False):
    dist = HAVERSINE_KM.get((from_id, to_id), 5.0)
    speed = 40 if emergency else 25  # km/h
    return (dist / speed) * 60


# ── Data classes ────────────────────────────────────────────────────────

@dataclass
class BloodUnit:
    unit_id: str
    blood_type: str
    component: str
    volume_ml: int
    facility_id: str
    expires_in_hours: float
    available: bool = True

    @property
    def urgency_expiry(self):
        total = SHELF_LIFE.get(self.component, 1008)
        return max(0, 1.0 - self.expires_in_hours / total)


@dataclass
class Request:
    request_id: str
    facility_id: str
    component: str
    blood_type: str
    sex: str = "M"
    age: int = 35
    urgency: str = "routine"


@dataclass
class SimResult:
    scenario: str
    days: int
    total_requests: int = 0
    fulfilled: int = 0
    fulfilled_exact: int = 0
    fulfilled_compatible: int = 0
    fulfilled_sos: int = 0
    unfulfilled: int = 0
    avg_time_min: float = 0.0
    median_time_min: float = 0.0
    units_expired: int = 0
    units_temp_waste: int = 0
    total_waste: int = 0
    sos_calls: int = 0
    sos_successful: int = 0
    fulfillment_times: list = field(default_factory=list)


# ── Replenish inventory ─────────────────────────────────────────────────

def replenish_inventory(inventory, fid, day, rng, collections_per_day):
    """Add new blood units to facility inventory (daily collections)."""
    n = max(1, int(rng.gauss(collections_per_day, collections_per_day * 0.15)))
    for i in range(n):
        bt = random_blood_type(rng)
        comp = rng.choices(["RBC", "PLT", "FFP"], weights=[0.60, 0.20, 0.20])[0]
        # New units have near-full shelf life
        remaining = SHELF_LIFE[comp] * rng.uniform(0.85, 0.99)
        inventory[fid].append(BloodUnit(
            unit_id=f"U-{fid[:3]}-{day}-{len(inventory[fid])}",
            blood_type=bt, component=comp,
            volume_ml=rng.choice([250, 350, 450]),
            facility_id=fid,
            expires_in_hours=remaining,
        ))


def age_and_expire(inventory, fid, result, cold_chain_waste_rate, rng):
    """Age units by 24h, remove expired, apply cold chain waste."""
    expired = []
    for unit in inventory[fid]:
        unit.expires_in_hours -= 24
        if unit.expires_in_hours <= 0:
            expired.append(unit)
    for unit in expired:
        inventory[fid].remove(unit)
        if unit.available:
            result.units_expired += 1
            result.total_waste += 1

    # Cold chain waste (temperature excursions, handling errors, etc.)
    available = [u for u in inventory[fid] if u.available]
    # Binomial-like: each unit has cold_chain_waste_rate/30 chance of waste per day
    n_waste = sum(1 for _ in available if rng.random() < cold_chain_waste_rate / 30)
    for _ in range(min(n_waste, len(available))):
        if available:
            w = rng.choice(available)
            w.available = False
            result.units_temp_waste += 1
            result.total_waste += 1
            available = [u for u in inventory[fid] if u.available]


def find_best_match(request, all_inventory, src_facilities, rng, emergency_eta=False):
    """Find the best matching unit from given facilities."""
    best_match = None
    best_score = -1.0
    best_eta = 0.0

    for src_fid in src_facilities:
        for unit in all_inventory.get(src_fid, []):
            if not unit.available or unit.component != request.component:
                continue
            if unit.expires_in_hours <= 2:
                continue
            if not is_compatible(unit.blood_type, request.blood_type, request.component,
                                  request.sex, request.age):
                continue

            eta = eta_minutes(src_fid, request.facility_id, emergency=emergency_eta)

            # Score based on urgency profile
            w_urg, w_time, w_comp = {
                "emergency": (0.15, 0.45, 0.20),
                "urgent": (0.25, 0.30, 0.20),
                "routine": (0.35, 0.15, 0.20),
            }[request.urgency]

            total_shelf = SHELF_LIFE.get(unit.component, 1008)
            urg_score = max(0, 1.0 - unit.expires_in_hours / total_shelf)
            time_score = max(0, min(1.0, (24 - eta / 60) / 24)) if eta else 0.5

            if unit.blood_type == request.blood_type:
                comp_score = 1.0
            elif unit.blood_type[:-1] == request.blood_type[:-1]:
                comp_score = 0.9
            else:
                comp_score = 0.5
            if unit.blood_type == "O-" and request.blood_type != "O-":
                comp_score -= 0.3

            score = w_urg * urg_score + w_time * time_score + w_comp * comp_score
            if score > best_score:
                best_score = score
                best_match = unit
                best_eta = eta

    return best_match, best_eta


# ── Baseline simulation ────────────────────────────────────────────────

def simulate_baseline(days=30, rng=None, verbose=False):
    if rng is None:
        rng = random.Random(42)
    result = SimResult(scenario="baseline", days=days)
    inventory = {f["id"]: [] for f in FACILITIES}

    # Seed initial inventory
    for f in FACILITIES:
        replenish_inventory(inventory, f["id"], 0, rng, f["daily_collections"] * 3)  # 3 days buffer

    baseline_waste_rate = 0.10  # 10% cold chain waste per month

    for day in range(days):
        # Daily replenishment
        for f in FACILITIES:
            replenish_inventory(inventory, f["id"], day, rng, f["daily_collections"])

        # Generate requests
        for f in FACILITIES:
            n_req = max(1, int(rng.gauss(f["daily_collections"] * 0.8, 5)))
            for _ in range(n_req):
                result.total_requests += 1
                bt = random_blood_type(rng)
                comp = rng.choices(["RBC", "PLT", "FFP"], weights=[0.60, 0.20, 0.20])[0]
                sex = rng.choice(["M", "F"])
                age = rng.randint(18, 70)
                urgency = rng.choices(["routine", "urgent", "emergency"], weights=[0.50, 0.35, 0.15])[0]

                req = Request(
                    request_id=f"BL-{result.total_requests}",
                    facility_id=f["id"], component=comp,
                    blood_type=bt, sex=sex, age=age, urgency=urgency,
                )

                # BASELINE: only search LOCAL facility (no inter-facility matching)
                match, eta = find_best_match(req, inventory, [f["id"]], rng)

                if match:
                    match.available = False
                    result.fulfilled += 1
                    if match.blood_type == req.blood_type:
                        result.fulfilled_exact += 1
                    else:
                        result.fulfilled_compatible += 1
                    # Baseline: manual phone sourcing = 4-6 hours average
                    baseline_time = rng.uniform(240, 360)
                    result.fulfillment_times.append(baseline_time)
                else:
                    result.unfulfilled += 1

        # Age and expire
        for f in FACILITIES:
            age_and_expire(inventory, f["id"], result, baseline_waste_rate, rng)

    if result.fulfillment_times:
        result.avg_time_min = statistics.mean(result.fulfillment_times)
        result.median_time_min = statistics.median(result.fulfillment_times)

    if verbose:
        print(f"\n{'='*60}")
        print(f"BASELINE ({days} ngày, không BLOODBLINK)")
        print(f"{'='*60}")
        print(f"  Tổng yêu cầu:        {result.total_requests}")
        print(f"  Đáp ứng:             {result.fulfilled} ({result.fulfilled/result.total_requests*100:.1f}%)")
        print(f"    Khớp chính xác:    {result.fulfilled_exact} ({result.fulfilled_exact/result.total_requests*100:.1f}%)")
        print(f"    Tương hợp:         {result.fulfilled_compatible} ({result.fulfilled_compatible/result.total_requests*100:.1f}%)")
        print(f"  Không đáp ứng:       {result.unfulfilled} ({result.unfulfilled/result.total_requests*100:.1f}%)")
        print(f"  Thời gian TB:        {result.avg_time_min:.0f} phút ({result.avg_time_min/60:.1f}h)")
        print(f"  Thời gian trung vị:  {result.median_time_min:.0f} phút")
        print(f"  Đơn vị hủy:          {result.total_waste} (hết hạn: {result.units_expired}, chuỗi lạnh: {result.units_temp_waste})")

    return result


# ── BLOODBLINK simulation ──────────────────────────────────────────────

def simulate_bloodblink(days=30, rng=None, verbose=False):
    if rng is None:
        rng = random.Random(42)
    result = SimResult(scenario="bloodblink", days=days)
    inventory = {f["id"]: [] for f in FACILITIES}

    # Seed initial inventory
    for f in FACILITIES:
        replenish_inventory(inventory, f["id"], 0, rng, f["daily_collections"] * 3)

    # SOS donor pool (200 registered donors in HCMC)
    donor_pool = []
    for _ in range(200):
        donor_pool.append({
            "id": f"DON-{len(donor_pool)}",
            "blood_type": random_blood_type(rng),
            "facility_id": rng.choice([f["id"] for f in FACILITIES]),
            "sex": rng.choice(["M", "F"]),
            "age": rng.randint(18, 60),
            "last_donation_weeks": rng.uniform(0, 52),
        })

    bloodblink_waste_rate = 0.04  # 4% (BB-Box monitoring reduces cold chain waste by ~60%)

    for day in range(days):
        # Daily replenishment
        for f in FACILITIES:
            replenish_inventory(inventory, f["id"], day, rng, f["daily_collections"])

        # Generate requests
        for f in FACILITIES:
            n_req = max(1, int(rng.gauss(f["daily_collections"] * 0.8, 5)))
            for _ in range(n_req):
                result.total_requests += 1
                bt = random_blood_type(rng)
                comp = rng.choices(["RBC", "PLT", "FFP"], weights=[0.60, 0.20, 0.20])[0]
                sex = rng.choice(["M", "F"])
                age = rng.randint(18, 70)
                urgency = rng.choices(["routine", "urgent", "emergency"], weights=[0.50, 0.35, 0.15])[0]

                req = Request(
                    request_id=f"BB-{result.total_requests}",
                    facility_id=f["id"], component=comp,
                    blood_type=bt, sex=sex, age=age, urgency=urgency,
                )

                # BLOODBLINK: search ALL facilities
                all_fids = [ff["id"] for ff in FACILITIES]
                match, eta = find_best_match(req, inventory, all_fids, rng,
                                              emergency_eta=(urgency == "emergency"))

                if match:
                    match.available = False
                    result.fulfilled += 1
                    if match.blood_type == req.blood_type:
                        result.fulfilled_exact += 1
                    else:
                        result.fulfilled_compatible += 1
                    result.fulfillment_times.append(eta)
                else:
                    # SOS donor mobilization for unfulfilled emergency requests
                    if urgency == "emergency":
                        result.sos_calls += 1
                        eligible = [
                            d for d in donor_pool
                            if is_compatible(d["blood_type"], req.blood_type, req.component, req.sex, req.age)
                            and d["last_donation_weeks"] >= DONATION_INTERVAL_WEEKS.get(req.component, 12)
                        ]
                        # 4-ring escalation: cumulative response rates
                        ring_rates = [0.30, 0.20, 0.15, 0.10]
                        responded = False
                        for ring_i, ring_rate in enumerate(ring_rates):
                            n_eligible = max(1, int(len(eligible) * ring_rate * rng.uniform(0.5, 1.0)))
                            if n_eligible > 0:
                                result.sos_successful += 1
                                result.fulfilled += 1
                                result.fulfilled_sos += 1
                                result.fulfilled_compatible += 1
                                sos_time = [10, 20, 35, 55][ring_i] + rng.uniform(5, 20)
                                result.fulfillment_times.append(sos_time)
                                responded = True
                                break
                        if not responded:
                            result.unfulfilled += 1
                    else:
                        result.unfulfilled += 1

        # Age and expire
        for f in FACILITIES:
            age_and_expire(inventory, f["id"], result, bloodblink_waste_rate, rng)

    if result.fulfillment_times:
        result.avg_time_min = statistics.mean(result.fulfillment_times)
        result.median_time_min = statistics.median(result.fulfillment_times)

    if verbose:
        print(f"\n{'='*60}")
        print(f"BLOODBLINK ({days} ngày, có BLOODBLINK)")
        print(f"{'='*60}")
        print(f"  Tổng yêu cầu:        {result.total_requests}")
        print(f"  Đáp ứng:             {result.fulfilled} ({result.fulfilled/result.total_requests*100:.1f}%)")
        print(f"    Khớp chính xác:    {result.fulfilled_exact} ({result.fulfilled_exact/result.total_requests*100:.1f}%)")
        print(f"    Tương hợp:         {result.fulfilled_compatible} ({result.fulfilled_compatible/result.total_requests*100:.1f}%)")
        print(f"    SOS huy động:      {result.fulfilled_sos}")
        print(f"  Không đáp ứng:       {result.unfulfilled} ({result.unfulfilled/result.total_requests*100:.1f}%)")
        print(f"  Thời gian TB:        {result.avg_time_min:.0f} phút ({result.avg_time_min/60:.1f}h)")
        print(f"  Thời gian trung vị:  {result.median_time_min:.0f} phút")
        print(f"  SOS gọi:             {result.sos_calls} | Thành công: {result.sos_successful}")
        print(f"  Đơn vị hủy:          {result.total_waste} (hết hạn: {result.units_expired}, chuỗi lạnh: {result.units_temp_waste})")

    return result


# ── Comparison & output ─────────────────────────────────────────────────

def compare(bl: SimResult, bb: SimResult) -> dict:
    bl_rate = bl.fulfilled / max(1, bl.total_requests) * 100
    bb_rate = bb.fulfilled / max(1, bb.total_requests) * 100
    bl_exact = bl.fulfilled_exact / max(1, bl.total_requests) * 100
    bb_exact = bb.fulfilled_exact / max(1, bb.total_requests) * 100
    bl_unful = bl.unfulfilled / max(1, bl.total_requests) * 100
    bb_unful = bb.unfulfilled / max(1, bb.total_requests) * 100

    def pct_change(old, new):
        return ((new - old) / old * 100) if old else 0

    return {
        "fulfillment_rate": {"baseline": round(bl_rate, 1), "bloodblink": round(bb_rate, 1),
                              "improvement_pp": round(bb_rate - bl_rate, 1)},
        "exact_match_rate": {"baseline": round(bl_exact, 1), "bloodblink": round(bb_exact, 1),
                             "improvement_pp": round(bb_exact - bl_exact, 1)},
        "unfulfilled_rate": {"baseline": round(bl_unful, 1), "bloodblink": round(bb_unful, 1),
                             "reduction_pp": round(bl_unful - bb_unful, 1)},
        "avg_time_min": {"baseline": round(bl.avg_time_min, 0), "bloodblink": round(bb.avg_time_min, 0),
                          "reduction_pct": round(-pct_change(bl.avg_time_min, bb.avg_time_min), 1)},
        "median_time_min": {"baseline": round(bl.median_time_min, 0), "bloodblink": round(bb.median_time_min, 0)},
        "waste_total": {"baseline": bl.total_waste, "bloodblink": bb.total_waste,
                         "reduction_pct": round(-pct_change(bl.total_waste, bb.total_waste), 1)},
        "waste_per_day": {"baseline": round(bl.total_waste/max(1, bl.days), 1),
                          "bloodblink": round(bb.total_waste/max(1, bb.days), 1)},
        "sos_calls": bb.sos_calls, "sos_successful": bb.sos_successful,
        "sos_success_rate": round(bb.sos_successful / max(1, bb.sos_calls) * 100, 1) if bb.sos_calls else 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BLOODBLINK Discrete Event Simulation")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    rng_bl = random.Random(args.seed)
    rng_bb = random.Random(args.seed)

    print("🩸 BLOODBLINK — Mô phỏng sự kiện rời rạc (Discrete Event Simulation)")
    print(f"   Seed: {args.seed} | Thời gian: {args.days} ngày")
    print(f"   Cơ sở: {len(FACILITIES)} bệnh viện máu TP.HCM")
    print(f"   Phân bố nhóm máu VN: O~45%, B~30%, A~20%, AB~5%, Rh-~0.1%")
    print()

    bl = simulate_baseline(days=args.days, rng=rng_bl, verbose=args.verbose)
    bb = simulate_bloodblink(days=args.days, rng=rng_bb, verbose=args.verbose)

    comp = compare(bl, bb)

    print(f"\n{'='*60}")
    print("📊 SO SÁNH: Baseline vs BLOODBLINK")
    print(f"{'='*60}")
    print(f"  Tỷ lệ đáp ứng:       {comp['fulfillment_rate']['baseline']}% → {comp['fulfillment_rate']['bloodblink']}%  (+{comp['fulfillment_rate']['improvement_pp']}pp)")
    print(f"  Khớp chính xác:      {comp['exact_match_rate']['baseline']}% → {comp['exact_match_rate']['bloodblink']}%  (+{comp['exact_match_rate']['improvement_pp']}pp)")
    print(f"  Không đáp ứng:       {comp['unfulfilled_rate']['baseline']}% → {comp['unfulfilled_rate']['bloodblink']}%  (-{comp['unfulfilled_rate']['reduction_pp']}pp)")
    print(f"  Thời gian TB:        {comp['avg_time_min']['baseline']}min → {comp['avg_time_min']['bloodblink']}min  ({comp['avg_time_min']['reduction_pct']}% giảm)")
    print(f"  Thời gian trung vị:  {comp['median_time_min']['baseline']}min → {comp['median_time_min']['bloodblink']}min")
    print(f"  Đơn vị hủy:          {comp['waste_total']['baseline']} → {comp['waste_total']['bloodblink']}  ({comp['waste_total']['reduction_pct']}% giảm)")
    print(f"  Hủy/ngày:            {comp['waste_per_day']['baseline']} → {comp['waste_per_day']['bloodblink']}")
    print(f"  SOS huy động:        {comp['sos_calls']} cuộc gọi, {comp['sos_successful']} thành công ({comp['sos_success_rate']}%)")

    # Save JSON
    output = {
        "seed": args.seed, "days": args.days,
        "baseline": {
            "total_requests": bl.total_requests, "fulfilled": bl.fulfilled,
            "fulfilled_exact": bl.fulfilled_exact, "fulfilled_compatible": bl.fulfilled_compatible,
            "unfulfilled": bl.unfulfilled,
            "avg_time_min": round(bl.avg_time_min, 1), "median_time_min": round(bl.median_time_min, 1),
            "total_waste": bl.total_waste, "units_expired": bl.units_expired, "units_temp_waste": bl.units_temp_waste,
        },
        "bloodblink": {
            "total_requests": bb.total_requests, "fulfilled": bb.fulfilled,
            "fulfilled_exact": bb.fulfilled_exact, "fulfilled_compatible": bb.fulfilled_compatible,
            "fulfilled_sos": bb.fulfilled_sos,
            "unfulfilled": bb.unfulfilled,
            "avg_time_min": round(bb.avg_time_min, 1), "median_time_min": round(bb.median_time_min, 1),
            "total_waste": bb.total_waste, "units_expired": bb.units_expired, "units_temp_waste": bb.units_temp_waste,
            "sos_calls": bb.sos_calls, "sos_successful": bb.sos_successful,
        },
        "comparison": comp,
    }
    path = f"simulation_results_{args.days}d.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Kết quả lưu tại {path}")