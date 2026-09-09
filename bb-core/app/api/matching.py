"""BB-Core — Matching API: find and rank compatible blood units."""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models.database import (
    BloodUnit, TransferRequest, TransferCandidate, Facility,
    ComponentCode, ABO, RhD, UnitStatus, RequestUrgency, TransferState,
)
from app.services.sos_advice import advise
from app.services.matching import (
    find_matching_units, TransferRequest as MatchRequest,
    BloodUnitCandidate,
)
from app.api.schemas import (
    TransferRequestIn, TransferRequestOut, MatchResultOut, MatchResponse,
)
from app.services.routing import RoutingService, HCMC_FACILITIES

router = APIRouter()
_routing = RoutingService()


@router.post("/request", response_model=TransferRequestOut)
async def create_transfer_request(
    req: TransferRequestIn,
    db: AsyncSession = Depends(get_db),
):
    """Create a new transfer request for blood components."""
    import uuid

    # Verify requesting facility exists
    fac = await db.get(Facility, req.requester_facility_id)
    if not fac:
        raise HTTPException(status_code=404, detail=f"Facility {req.requester_facility_id} not found")

    # Create the request
    tr = TransferRequest(
        id=str(uuid.uuid4()),
        requester_facility_id=req.requester_facility_id,
        component_code=ComponentCode(req.component_code),
        abo=ABO(req.abo) if req.abo else None,
        rh=RhD(req.rh) if req.rh else None,
        qty=req.qty,
        urgency=RequestUrgency(req.urgency),
        needed_by=req.needed_by,
        created_at=datetime.now(timezone.utc),
        state=TransferState.PENDING,
    )
    db.add(tr)
    await db.commit()
    await db.refresh(tr)

    return TransferRequestOut.model_validate(tr)


@router.post("/find", response_model=MatchResponse)
async def find_matches(
    request_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Find compatible blood units for a transfer request.

    Returns a ranked list with scores and human-readable explanations.
    This is the core value proposition of BLOODBLINK.
    """
    # Load the transfer request
    tr = await db.get(TransferRequest, request_id)
    if not tr:
        raise HTTPException(status_code=404, detail=f"Transfer request {request_id} not found")

    # Build the matching request
    match_req = MatchRequest(
        request_id=tr.id,
        requester_facility_id=tr.requester_facility_id,
        component_code=tr.component_code.value,
        abo=tr.abo.value if tr.abo else None,
        rh=tr.rh.value if tr.rh else None,
        urgency=tr.urgency.value,
        needed_by=tr.needed_by,
    )

    # Query available units of the requested component type
    stmt = (
        select(BloodUnit, Facility)
        .join(Facility, BloodUnit.held_by_facility_id == Facility.id)
        .where(
            and_(
                BloodUnit.component_code == tr.component_code,
                BloodUnit.status == UnitStatus.AVAILABLE,
                BloodUnit.held_by_facility_id != tr.requester_facility_id,  # exclude own facility
            )
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Build candidate list
    candidates = []
    for unit, facility in rows:
        candidates.append(BloodUnitCandidate(
            unit_id=unit.id,
            isbt_din=unit.isbt_din,
            component_code=unit.component_code.value,
            abo=unit.abo.value,
            rh=unit.rh.value,
            volume_ml=unit.volume_ml,
            collected_at=unit.collected_at,
            expires_at=unit.expires_at,
            held_by_facility_id=unit.held_by_facility_id,
            facility_name=facility.name,
            facility_opt_in=facility.opt_in,
            irradiated=unit.irradiated,
            leukoreduced=unit.leukoreduced,
        ))

    # Đếm tồn kho từng cơ sở, để không rút cạn nguồn của chính nơi cho.
    #
    # Trước đây chỗ này có HAI truy vấn giống hệt nhau: một cái dựng vào biến
    # `stock_stmt` rồi không ai chạy, và nó gọi `func.count(...)` trong khi
    # `func` chưa hề được import ở đầu tệp — nên endpoint nổ `NameError` ngay
    # dòng đó, trước cả khi tới truy vấn thật ở dưới. Cả trang Ghép nguồn trả
    # 500 và console render trắng.
    stock_result = await db.execute(
        select(
            BloodUnit.held_by_facility_id,
            BloodUnit.component_code,
            func.count(BloodUnit.id).label("count"),
        )
        .where(BloodUnit.status == UnitStatus.AVAILABLE)
        .group_by(BloodUnit.held_by_facility_id, BloodUnit.component_code)
    )
    facility_stock = {}
    for row in stock_result:
        fid = row.held_by_facility_id
        if fid not in facility_stock:
            facility_stock[fid] = {}
        facility_stock[fid][row.component_code.value] = row.count

    # Get safety thresholds
    safety_thresholds = {}
    facilities_stmt = select(Facility)
    fac_result = await db.execute(facilities_stmt)
    for fac in fac_result.scalars().all():
        safety_thresholds[fac.id] = fac.safety_threshold_json

    # Build ETA lookup using real routing (with haversine fallback)
    async def eta_lookup(from_facility_id: str, to_facility_id: str) -> int:
        """Get ETA in seconds between two facilities using RoutingService."""
        from_fac = HCMC_FACILITIES.get(from_facility_id)
        to_fac = HCMC_FACILITIES.get(to_facility_id)
        if not from_fac or not to_fac:
            return 5400  # 90 min fallback for unknown facilities
        route = await _routing.get_route(
            from_fac["lat"], from_fac["lon"],
            to_fac["lat"], to_fac["lon"],
            mode="emergency" if match_req.urgency == "emergency" else "car",
        )
        return int(route.duration_s)

    # Pre-compute ETAs for all source facilities → requesting facility
    eta_cache: dict[str, int] = {}
    for candidate in candidates:
        fid = candidate.held_by_facility_id
        if fid not in eta_cache:
            try:
                eta_cache[fid] = await eta_lookup(fid, tr.requester_facility_id)
            except Exception:
                eta_cache[fid] = 5400  # 90 min fallback

    def sync_eta_lookup(from_facility_id: str, to_facility_id: str) -> int:
        """Synchronous ETA lookup using pre-computed cache."""
        return eta_cache.get(from_facility_id, 5400)

    # Find matches
    results = find_matching_units(
        request=match_req,
        candidates=candidates,
        now=datetime.now(timezone.utc),
        safety_margin_hours=settings.safety_margin_hours,
        facility_stock_counts=facility_stock,
        facility_safety_thresholds=safety_thresholds,
        eta_lookup=sync_eta_lookup,
    )

    # Store top candidates in database
    for r in results[:10]:  # Store top 10
        tc = TransferCandidate(
            id=str(uuid.uuid4()) if not hasattr(r, '_saved') else r.unit_id,
            request_id=tr.id,
            unit_id=r.unit_id,
            rank=r.rank,
            score=r.score,
            score_breakdown=r.score_breakdown,
            reason_text=r.reason_text,
            eta_seconds=r.eta_seconds,
        )
        db.add(tc)
    await db.commit()

    # Separate compatible and blocked
    compatible = [r for r in results if r.compatible]
    blocked = [r for r in results if not r.compatible]

    # ── Có nên mở SOS sau khi đã tìm kho? ─────────────────────────
    #
    # Tìm nguồn xong mà không nói gì thêm thì nhân viên phải TỰ NHỚ sang mục SOS
    # và tự điền lại nhóm máu, chế phẩm, cơ sở — bước dễ rơi nhất đúng lúc đang
    # cuống. Xem `services/sos_advice.py` về thứ tự kho-trước-người-sau.
    unit_by_id = {c.unit_id: c for c in candidates}
    taken: dict[str, int] = {}
    for r in compatible[: tr.qty]:
        unit = unit_by_id.get(r.unit_id)
        if unit:
            taken[unit.held_by_facility_id] = taken.get(unit.held_by_facility_id, 0) + 1

    component = tr.component_code.value
    advice = advise(
        qty_needed=tr.qty,
        compatible_count=len(compatible),
        urgency=tr.urgency.value,
        rh=tr.rh.value if tr.rh else None,
        taken_by_facility=taken,
        stock_by_facility={
            fid: comps.get(component, 0) for fid, comps in facility_stock.items()
        },
        thresholds_by_facility={
            fid: (thr or {}).get(component, 0) for fid, thr in safety_thresholds.items()
        },
    )

    return MatchResponse(
        request_id=request_id,
        total_candidates=len(results),
        compatible_count=len(compatible),
        sos_action=advice.action,
        sos_reason=advice.reason,
        sos_urgency=advice.urgency,
        sos_target_count=advice.target_count,
        sos_start_ring=advice.start_ring,
        sos_depleted_facilities=advice.depleted_facilities,
        results=[
            MatchResultOut(
                unit_id=r.unit_id,
                rank=r.rank,
                score=r.score,
                score_breakdown=r.score_breakdown,
                reason_text=r.reason_text,
                eta_seconds=r.eta_seconds,
                compatible=r.compatible,
                blocked_reason=r.blocked_reason,
            )
            for r in results[:50]  # Return top 50
        ],
    )


@router.get("/request/{request_id}", response_model=TransferRequestOut)
async def get_transfer_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get details of a transfer request."""
    tr = await db.get(TransferRequest, request_id)
    if not tr:
        raise HTTPException(status_code=404, detail="Transfer request not found")
    return TransferRequestOut.model_validate(tr)


@router.post("/request/{request_id}/approve", response_model=TransferRequestOut)
async def approve_transfer_request(
    request_id: str,
    approved_by: str,
    db: AsyncSession = Depends(get_db),
):
    """Approve a transfer request — button must say 'Đề xuất', not 'Điều chuyển'."""
    import uuid

    tr = await db.get(TransferRequest, request_id)
    if not tr:
        raise HTTPException(status_code=404, detail="Transfer request not found")

    if tr.state != TransferState.PENDING:
        raise HTTPException(status_code=400, detail=f"Request is in state {tr.state.value}, not PENDING")

    # Get the top candidate
    stmt = (
        select(TransferCandidate)
        .where(TransferCandidate.request_id == request_id)
        .where(TransferCandidate.compatible == True)
        .order_by(TransferCandidate.rank)
        .limit(1)
    )
    result = await db.execute(stmt)
    top_candidate = result.scalar_one_or_none()

    if not top_candidate:
        raise HTTPException(status_code=404, detail="No compatible candidates found")

    # Create transfer order
    from app.models.database import TransferOrder
    unit = await db.get(BloodUnit, top_candidate.unit_id)

    order = TransferOrder(
        id=str(uuid.uuid4()),
        request_id=request_id,
        source_facility_id=unit.held_by_facility_id,
        state=TransferState.APPROVED,
        approved_by=approved_by,
        at=datetime.now(timezone.utc),
    )
    db.add(order)

    # Update request state
    tr.state = TransferState.APPROVED

    # Mark unit as reserved
    unit.status = UnitStatus.RESERVED

    await db.commit()
    await db.refresh(tr)

    return TransferRequestOut.model_validate(tr)