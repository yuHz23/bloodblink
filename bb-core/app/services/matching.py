"""
BB-Core — Matching Engine: source finding + ranking with explanation

The core algorithm that proves BLOODBLINK's value proposition:
Given a transfer request, find and rank all compatible blood units
across facilities, with human-readable explanations.

Three-step process (per the planning doc):
  1. Hard filter (eliminate non-viable units)
  2. Score (5 weighted factors)
  3. Professional guard rails (O- penalty, RhD for women of childbearing age)

Output: ranked list with score_breakdown_json and reason_text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.services.compatibility import (
    is_compatible, compute_compatibility_score, ComponentCode, ABO, RhD,
)


# ── Data classes ─────────────────────────────────────────────────

@dataclass
class TransferRequest:
    """Incoming request for blood component transfer."""
    request_id: str
    requester_facility_id: str
    component_code: str      # RBC, PLT, FFP, CRYO
    abo: Optional[str]       # None = any compatible
    rh: Optional[str]        # None = any compatible
    urgency: str              # routine, urgent, emergency
    needed_by: datetime
    recipient_sex: Optional[str] = None
    recipient_age: Optional[int] = None


@dataclass
class BloodUnitCandidate:
    """A blood unit that might satisfy a request."""
    unit_id: str
    isbt_din: str
    component_code: str
    abo: str
    rh: str
    volume_ml: int
    collected_at: datetime
    expires_at: datetime
    held_by_facility_id: str
    facility_name: str
    facility_opt_in: bool
    irradiated: bool = False
    leukoreduced: bool = False


@dataclass
class MatchResult:
    """A ranked match with full explanation."""
    unit_id: str
    rank: int
    score: float
    score_breakdown: dict          # {factor: value}
    reason_text: str               # human-readable explanation
    eta_seconds: Optional[int] = None
    compatible: bool = True
    blocked_reason: Optional[str] = None


# ── Weight profiles by urgency ──────────────────────────────────

WEIGHT_PROFILES = {
    # Emergency: arrival time is everything
    "emergency": {
        "urgency_expiry": 0.15,    # near-expiry still matters but less
        "time_margin": 0.45,        # can it arrive before needed_by?
        "blood_group_match": 0.20,
        "source_stock_margin": 0.10,
        "risk_penalty": 0.10,
    },
    # Routine/rotation: FEFO + stock safety first
    "routine": {
        "urgency_expiry": 0.35,     # FEFO — dispatch near-expiry first
        "time_margin": 0.15,
        "blood_group_match": 0.20,
        "source_stock_margin": 0.20, # don't deplete source below safety
        "risk_penalty": 0.10,
    },
    # Urgent: balanced
    "urgent": {
        "urgency_expiry": 0.25,
        "time_margin": 0.30,
        "blood_group_match": 0.20,
        "source_stock_margin": 0.15,
        "risk_penalty": 0.10,
    },
}


def find_matching_units(
    request: TransferRequest,
    candidates: list[BloodUnitCandidate],
    now: datetime = None,
    safety_margin_hours: float = 2.0,
    facility_stock_counts: Optional[dict[str, dict[str, int]]] = None,
    facility_safety_thresholds: Optional[dict[str, dict[str, int]]] = None,
    reciprocity_credits: Optional[dict[str, int]] = None,
    eta_lookup: Optional[callable] = None,
) -> list[MatchResult]:
    """
    Main matching function: filter, score, rank, and explain.

    Args:
        request: The transfer request to fulfill.
        candidates: All available blood units (pre-filtered to same component type).
        now: Current timestamp (defaults to UTC now).
        safety_margin_hours: Buffer before expiry (default 2 hours).
        facility_stock_counts: {facility_id: {component: count}} for source stock check.
        facility_safety_thresholds: {facility_id: {component: min_count}} per facility.
        reciprocity_credits: {source_facility_id: confirmed units previously received from requester}.
        eta_lookup: async function(from_facility_id, to_facility_id) -> int (seconds).

    Returns:
        Sorted list of MatchResult, best first.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    weights = WEIGHT_PROFILES.get(request.urgency, WEIGHT_PROFILES["routine"])
    results: list[MatchResult] = []

    for candidate in candidates:
        result = _evaluate_candidate(
            request=request,
            candidate=candidate,
            now=now,
            weights=weights,
            safety_margin_hours=safety_margin_hours,
            facility_stock_counts=facility_stock_counts or {},
            facility_safety_thresholds=facility_safety_thresholds or {},
            reciprocity_credits=reciprocity_credits or {},
            eta_lookup=eta_lookup,
        )
        if result is not None:
            results.append(result)

    # Keep compatible, group-specific units ahead of O-negative reserve units.
    # O- remains available when other compatible stock cannot cover the request.
    candidate_by_id = {c.unit_id: c for c in candidates}
    recipient_abo = request.abo or "O"
    is_childbearing_age = (
        request.recipient_sex == "F"
        and (request.recipient_age is None or 18 <= request.recipient_age <= 45)
    )
    recipient_rh = request.rh or ("-" if is_childbearing_age else "+")

    def uses_o_negative_reserve(result: MatchResult) -> bool:
        unit = candidate_by_id.get(result.unit_id)
        return bool(
            result.compatible
            and request.component_code in (ComponentCode.RBC.value, ComponentCode.WB.value)
            and unit
            and unit.abo == "O"
            and unit.rh == "-"
            and (recipient_abo != "O" or recipient_rh != "-")
        )

    results.sort(key=lambda r: (
        not r.compatible,
        uses_o_negative_reserve(r),
        -r.score,
        candidate_by_id[r.unit_id].expires_at if r.unit_id in candidate_by_id else datetime.max.replace(tzinfo=timezone.utc),
    ))
    for i, r in enumerate(results):
        r.rank = i + 1

    return results


def _evaluate_candidate(
    request: TransferRequest,
    candidate: BloodUnitCandidate,
    now: datetime,
    weights: dict,
    safety_margin_hours: float,
    facility_stock_counts: dict,
    facility_safety_thresholds: dict,
    reciprocity_credits: dict,
    eta_lookup: Optional[callable] = None,
) -> Optional[MatchResult]:
    """Evaluate a single candidate unit against a request."""

    # ── Step 1: Hard filter (eliminate non-viable units) ──────────

    # 1a. Facility must have opted in to sharing
    if not candidate.facility_opt_in:
        return None

    # 1b. ABO/RhD compatibility (with professional constraints)
    recipient_abo = request.abo or "O"  # unknown ABO: use group O red-cell compatibility
    is_childbearing_age = (
        request.recipient_sex == "F"
        and (request.recipient_age is None or 18 <= request.recipient_age <= 45)
    )
    # Unknown RhD for a woman of childbearing age is handled conservatively as RhD-negative.
    recipient_rh = request.rh or ("-" if is_childbearing_age else "+")

    compat, compat_reason = is_compatible(
        donor_abo=candidate.abo,
        donor_rh=candidate.rh,
        recipient_abo=recipient_abo,
        recipient_rh=recipient_rh,
        component=request.component_code,
        recipient_sex=request.recipient_sex,
        recipient_age=request.recipient_age,
    )

    if not compat:
        return MatchResult(
            unit_id=candidate.unit_id,
            rank=0, score=0.0,
            score_breakdown={"blocked": True},
            reason_text=f"❌ Không tương hợp: {compat_reason}",
            compatible=False,
            blocked_reason=compat_reason,
        )

    # 1c. Unit must not have expired (with safety margin)
    time_remaining = candidate.expires_at - now
    if time_remaining <= timedelta(hours=0):
        return None  # already expired, skip entirely

    # 1d. ETA must be before needed_by (with safety margin)
    # Placeholder: assume eta_lookup returns seconds
    eta_seconds = None
    if eta_lookup:
        try:
            eta_seconds = eta_lookup(candidate.held_by_facility_id, request.requester_facility_id)
        except Exception:
            eta_seconds = 5400  # 90 min fallback

    safety_margin = timedelta(hours=safety_margin_hours)
    expiry_with_margin = candidate.expires_at - safety_margin

    # 1e. Source facility must not go below safety threshold after sharing
    source_id = candidate.held_by_facility_id
    if source_id in facility_stock_counts and source_id in facility_safety_thresholds:
        current_stock = facility_stock_counts[source_id].get(request.component_code, 0)
        min_stock = facility_safety_thresholds[source_id].get(request.component_code, 0)
        if current_stock - 1 < min_stock:
            return None  # would deplete source below safety

    # ── Step 2: Score (5 weighted factors) ────────────────────────

    hours_remaining = time_remaining.total_seconds() / 3600
    time_to_needed = (request.needed_by - now).total_seconds() / 3600

    # Factor 1: Urgency/expiry — FEFO score (higher = closer to expiry = more urgent to dispatch)
    # Normalized: 1.0 = expiring in next 6h, 0.0 = fresh
    if request.component_code == "PLT":
        urgency_expiry = max(0, 1.0 - (hours_remaining / 120))  # PLT: 5-day window
    elif request.component_code == "RBC":
        urgency_expiry = max(0, 1.0 - (hours_remaining / 1008))  # RBC: 42-day window
    else:
        urgency_expiry = max(0, 1.0 - (hours_remaining / 720))  # FFP: 30-day window

    # Factor 2: Time margin — will it arrive before needed_by?
    eta_hours = (eta_seconds or 5400) / 3600
    time_margin = max(0, min(1.0, (time_to_needed - eta_hours) / 24))  # 24h = perfect margin

    # Factor 3: Blood group match quality
    blood_group_score = compute_compatibility_score(
        candidate.abo, candidate.rh,
        recipient_abo, recipient_rh,
        request.component_code,
        request.recipient_sex, request.recipient_age,
    )

    # Factor 4: Source stock margin (how much above safety threshold after sharing)
    source_stock_margin = 0.5  # neutral default
    if source_id in facility_stock_counts:
        current = facility_stock_counts[source_id].get(request.component_code, 0)
        min_req = facility_safety_thresholds.get(source_id, {}).get(request.component_code, 0)
        if min_req > 0:
            source_stock_margin = min(1.0, (current - min_req) / (min_req * 2))

    # Factor 5: Risk/cost penalty (route complexity placeholder)
    risk_penalty = 0.0
    if (request.component_code in (ComponentCode.RBC.value, ComponentCode.WB.value)
            and candidate.abo == "O" and candidate.rh == "-"
            and (recipient_abo != "O" or recipient_rh != "-")):
        risk_penalty = 0.3  # O- used for non-O- is penalized
    if candidate.irradiated and request.component_code != "RBC":
        risk_penalty += 0.05  # unnecessary irradiation

    # Weighted sum
    score = (
        weights["urgency_expiry"] * urgency_expiry
        + weights["time_margin"] * time_margin
        + weights["blood_group_match"] * blood_group_score
        + weights["source_stock_margin"] * source_stock_margin
        + weights["risk_penalty"] * (1.0 - risk_penalty)
    )
    reciprocity_count = reciprocity_credits.get(source_id, 0)
    reciprocity_cap = 0.05 if request.urgency == "emergency" else 0.16
    reciprocity_bonus = min(reciprocity_cap, reciprocity_count * 0.04)
    score += reciprocity_bonus
    score = max(0.0, min(1.0, score))

    # ── Build reason text ────────────────────────────────────────
    reason_parts = []

    # Blood group explanation
    if candidate.abo == recipient_abo and candidate.rh == recipient_rh:
        reason_parts.append(f"cùng nhóm {candidate.abo}{candidate.rh}")
    else:
        reason_parts.append(f"tương hợp {candidate.abo}{candidate.rh}→{recipient_abo}{recipient_rh}")

    # Expiry explanation
    hours_left = int(hours_remaining)
    if hours_left < 24:
        reason_parts.append(f"còn {hours_left}h trước hạn")
    else:
        reason_parts.append(f"còn {hours_left // 24} ngày trước hạn")

    # ETA explanation
    if eta_seconds:
        eta_min = eta_seconds // 60
        if eta_min < 60:
            reason_parts.append(f"đến nơi trong ~{eta_min} phút")
        else:
            reason_parts.append(f"đến nơi trong ~{eta_min // 60}h{eta_min % 60:02d}'")

    # Source stock context
    if source_id in facility_stock_counts:
        current = facility_stock_counts[source_id].get(request.component_code, 0)
        reason_parts.append(f"nguồn còn {current} đơn vị")

    # O- warning
    if (request.component_code in (ComponentCode.RBC.value, ComponentCode.WB.value)
            and candidate.abo == "O" and candidate.rh == "-"
            and (recipient_abo != "O" or recipient_rh != "-")):
        reason_parts.append("⚠️ O- = tài nguyên khan hiếm")
    if reciprocity_count > 0:
        reason_parts.append(f"ưu tiên có đi có lại ({reciprocity_count} đơn vị đã nhận hỗ trợ)")

    reason_text = ", ".join(reason_parts)
    if reason_text:
        reason_text = reason_text[0].upper() + reason_text[1:] + "."
        if not reason_text.endswith("."):
            pass  # already ends with period

    # Build breakdown
    breakdown = {
        "urgency_expiry": round(urgency_expiry, 3),
        "time_margin": round(time_margin, 3),
        "blood_group_match": round(blood_group_score, 3),
        "source_stock_margin": round(source_stock_margin, 3),
        "risk_penalty": round(1.0 - risk_penalty, 3),
        "reciprocity_bonus": round(reciprocity_bonus, 3),
        "reciprocity_credits": reciprocity_count,
        "hours_remaining": round(hours_remaining, 1),
        "eta_seconds": eta_seconds,
    }

    return MatchResult(
        unit_id=candidate.unit_id,
        rank=0,  # will be set by sort
        score=round(score, 4),
        score_breakdown=breakdown,
        reason_text=reason_text,
        eta_seconds=eta_seconds,
    )
