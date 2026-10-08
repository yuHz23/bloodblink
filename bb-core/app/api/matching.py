"""BB-Core — Matching API: find and rank compatible blood units."""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models.database import (
    BloodUnit, TransferRequest, TransferCandidate, TransferOffer, TransferOrder, Facility,
    FacilitySupportContribution, InventoryEvent,
    ComponentCode, ABO, RhD, UnitStatus, RequestUrgency, TransferState,
)
from app.services.sos_advice import advise
from app.services.matching import (
    find_matching_units, TransferRequest as MatchRequest,
    BloodUnitCandidate,
)
from app.api.schemas import (
    TransferRequestIn, TransferRequestOut, TransferOfferOut, TransferOfferResponseIn,
    TransferOrderOut, MatchResultOut, MatchResponse,
)
from app.api.deps import Principal, get_principal
from app.services.routing import HCMC_FACILITIES
from app.api.routing import routing_service

router = APIRouter()


async def _offer_payload(db: AsyncSession, offer: TransferOffer) -> dict:
    request = await db.get(TransferRequest, offer.request_id)
    source = await db.get(Facility, offer.source_facility_id)
    requester = await db.get(Facility, request.requester_facility_id) if request else None
    if not request or not requester:
        raise HTTPException(status_code=404, detail="Transfer offer context not found")
    return {
        "id": offer.id,
        "request_id": offer.request_id,
        "source_facility_id": offer.source_facility_id,
        "source_facility_name": source.name if source else "Không có nguồn phù hợp",
        "requester_facility_id": request.requester_facility_id,
        "requester_facility_name": requester.name,
        "component_code": request.component_code.value,
        "abo": request.abo.value if request.abo else None,
        "rh": request.rh.value if request.rh else None,
        "qty": request.qty,
        "urgency": request.urgency.value if request.urgency else "routine",
        "needed_by": request.needed_by,
        "priority_rank": offer.priority_rank,
        "available_qty": offer.available_qty,
        "offered_qty": offer.offered_qty,
        "accepted_qty": offer.accepted_qty,
        "status": offer.status,
        "created_at": offer.created_at,
        "expires_at": offer.expires_at,
        "responded_at": offer.responded_at,
        "response_note": offer.response_note,
    }


async def _expire_transfer_offers(db: AsyncSession, offers: list[TransferOffer]) -> None:
    now = datetime.now(timezone.utc)
    changed = False
    for offer in offers:
        expiry = offer.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if offer.status == "pending" and expiry <= now:
            offer.status = "expired"
            offer.responded_at = now
            offer.response_note = "Hết thời gian chờ màu vàng"
            changed = True
    if changed:
        await db.commit()


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
        recipient_sex=req.recipient_sex,
        recipient_age=req.recipient_age,
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
        recipient_sex=tr.recipient_sex,
        recipient_age=tr.recipient_age,
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
        .where(
            BloodUnit.status == UnitStatus.AVAILABLE,
            BloodUnit.expires_at > datetime.now(timezone.utc),
        )
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

    reciprocity_result = await db.execute(
        select(
            FacilitySupportContribution.beneficiary_facility_id,
            func.sum(FacilitySupportContribution.quantity).label("quantity"),
        )
        .where(FacilitySupportContribution.supporter_facility_id == tr.requester_facility_id)
        .group_by(FacilitySupportContribution.beneficiary_facility_id)
    )
    reciprocity_credits = {
        row.beneficiary_facility_id: int(row.quantity or 0)
        for row in reciprocity_result
    }

    # Build ETA lookup using real routing (with haversine fallback)
    async def eta_lookup(from_facility_id: str, to_facility_id: str) -> int:
        """Get ETA in seconds between two facilities using RoutingService."""
        from_fac = HCMC_FACILITIES.get(from_facility_id)
        to_fac = HCMC_FACILITIES.get(to_facility_id)
        if not from_fac or not to_fac:
            return 5400  # 90 min fallback for unknown facilities
        route = await routing_service.get_route(
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
        reciprocity_credits=reciprocity_credits,
        eta_lookup=sync_eta_lookup,
    )

    # Replace earlier results for this request so repeated searches cannot create
    # duplicate approval rows for the same blood unit.
    await db.execute(delete(TransferCandidate).where(TransferCandidate.request_id == tr.id))
    for r in results[:50]:
        tc = TransferCandidate(
            id=str(uuid.uuid4()),
            request_id=tr.id,
            unit_id=r.unit_id,
            rank=r.rank,
            score=r.score,
            score_breakdown=r.score_breakdown,
            reason_text=r.reason_text,
            eta_seconds=r.eta_seconds,
            compatible=r.compatible,
            blocked_reason=r.blocked_reason,
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


@router.post("/request/{request_id}/broadcast", response_model=list[TransferOfferOut])
async def broadcast_transfer_request(
    request_id: str,
    response_window_minutes: int = Query(default=10, ge=0, le=60),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Create one timed offer per viable source, ranked by safe compatible stock."""
    request = await db.get(TransferRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Transfer request not found")
    if principal.facility_id and principal.facility_id != request.requester_facility_id:
        raise HTTPException(status_code=403, detail="Only the requesting facility can broadcast this request")

    existing = (await db.execute(
        select(TransferOffer)
        .where(TransferOffer.request_id == request_id)
        .order_by(TransferOffer.priority_rank)
    )).scalars().all()
    if existing:
        await _expire_transfer_offers(db, existing)
        return [TransferOfferOut(**(await _offer_payload(db, offer))) for offer in existing]

    now = datetime.now(timezone.utc)
    candidate_rows = (await db.execute(
        select(TransferCandidate.unit_id, BloodUnit.held_by_facility_id)
        .join(BloodUnit, BloodUnit.id == TransferCandidate.unit_id)
        .join(Facility, Facility.id == BloodUnit.held_by_facility_id)
        .where(
            TransferCandidate.request_id == request_id,
            TransferCandidate.compatible.is_(True),
            BloodUnit.component_code == request.component_code,
            BloodUnit.status == UnitStatus.AVAILABLE,
            BloodUnit.expires_at > now,
            Facility.opt_in.is_(True),
        )
    )).all()
    compatible_units: dict[str, set[str]] = {}
    for unit_id, facility_id in candidate_rows:
        compatible_units.setdefault(facility_id, set()).add(unit_id)

    stock_rows = (await db.execute(
        select(BloodUnit.held_by_facility_id, func.count(BloodUnit.id))
        .where(
            BloodUnit.component_code == request.component_code,
            BloodUnit.status == UnitStatus.AVAILABLE,
            BloodUnit.expires_at > now,
        )
        .group_by(BloodUnit.held_by_facility_id)
    )).all()
    total_stock = {facility_id: int(count) for facility_id, count in stock_rows}
    source_facilities = (await db.execute(
        select(Facility).where(Facility.id.in_(compatible_units.keys()))
    )).scalars().all() if compatible_units else []
    facility_by_id = {facility.id: facility for facility in source_facilities}

    ranked_sources = []
    for facility_id, units in compatible_units.items():
        facility = facility_by_id.get(facility_id)
        if not facility:
            continue
        component = request.component_code.value
        safety_stock = int((facility.safety_threshold_json or {}).get(component, 0))
        shareable = min(len(units), max(0, total_stock.get(facility_id, 0) - safety_stock))
        if shareable:
            ranked_sources.append((facility_id, shareable))
    ranked_sources.sort(key=lambda item: (-item[1], facility_by_id[item[0]].name.casefold()))

    expiry = now + timedelta(minutes=response_window_minutes)
    if response_window_minutes == 0:
        ranked_sources = []
    for rank, (facility_id, shareable) in enumerate(ranked_sources, start=1):
        db.add(TransferOffer(
            id=str(uuid.uuid4()),
            request_id=request_id,
            source_facility_id=facility_id,
            priority_rank=rank,
            available_qty=shareable,
            offered_qty=min(request.qty, shareable),
            status="pending",
            created_at=now,
            expires_at=expiry,
        ))
    if not ranked_sources:
        # Persist the fact that dispatch was attempted with no viable wait window
        # or no stock. The server scheduler uses this to start SOS even if the
        # requesting browser closes immediately after the call.
        db.add(TransferOffer(
            id=str(uuid.uuid4()),
            request_id=request_id,
            source_facility_id=None,
            priority_rank=0,
            available_qty=0,
            offered_qty=0,
            accepted_qty=0,
            status="no_source",
            created_at=now,
            expires_at=now,
            responded_at=now,
            response_note="Không có nguồn phù hợp hoặc không còn thời gian chờ",
        ))
    await db.commit()

    offers = (await db.execute(
        select(TransferOffer)
        .where(TransferOffer.request_id == request_id)
        .order_by(TransferOffer.priority_rank)
    )).scalars().all()
    return [TransferOfferOut(**(await _offer_payload(db, offer))) for offer in offers]


@router.get("/request/{request_id}/offers", response_model=list[TransferOfferOut])
async def list_transfer_offers(
    request_id: str,
    db: AsyncSession = Depends(get_db),
):
    if not await db.get(TransferRequest, request_id):
        raise HTTPException(status_code=404, detail="Transfer request not found")
    offers = (await db.execute(
        select(TransferOffer)
        .where(TransferOffer.request_id == request_id)
        .order_by(TransferOffer.priority_rank)
    )).scalars().all()
    await _expire_transfer_offers(db, offers)
    return [TransferOfferOut(**(await _offer_payload(db, offer))) for offer in offers]


@router.get("/offers/incoming", response_model=list[TransferOfferOut])
async def list_incoming_transfer_offers(
    facility_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    if principal.facility_id:
        if facility_id and facility_id != principal.facility_id:
            raise HTTPException(status_code=403, detail="Cannot view another facility's incoming offers")
        facility_id = principal.facility_id
    elif principal.role != "admin" and not facility_id:
        raise HTTPException(status_code=403, detail="Facility context required")

    stmt = select(TransferOffer).where(TransferOffer.status == "pending")
    if facility_id:
        stmt = stmt.where(TransferOffer.source_facility_id == facility_id)
    offers = (await db.execute(stmt.order_by(TransferOffer.created_at.desc()))).scalars().all()
    await _expire_transfer_offers(db, offers)
    return [TransferOfferOut(**(await _offer_payload(db, offer)))
            for offer in offers if offer.status == "pending"]


@router.post("/offers/{offer_id}/respond", response_model=TransferOfferOut)
async def respond_to_transfer_offer(
    offer_id: str,
    req: TransferOfferResponseIn,
    facility_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    offer_ref = await db.get(TransferOffer, offer_id)
    if not offer_ref:
        raise HTTPException(status_code=404, detail="Transfer offer not found")
    # Lock the request before the offer so two source hospitals cannot deadlock
    # while the winner cancels the remaining offers.
    request = await db.scalar(
        select(TransferRequest).where(TransferRequest.id == offer_ref.request_id).with_for_update()
    )
    offer = await db.scalar(
        select(TransferOffer).where(TransferOffer.id == offer_id).with_for_update()
    )
    if not offer or not request:
        raise HTTPException(status_code=404, detail="Transfer offer context not found")
    acting_facility = principal.facility_id or (facility_id if principal.role == "admin" else None)
    if acting_facility != offer.source_facility_id:
        raise HTTPException(status_code=403, detail="Only the offered facility can respond")
    if offer.status != "pending":
        raise HTTPException(status_code=409, detail=f"Offer is already {offer.status}")

    now = datetime.now(timezone.utc)
    expires = offer.expires_at if offer.expires_at.tzinfo else offer.expires_at.replace(tzinfo=timezone.utc)
    if expires <= now:
        offer.status = "expired"
        offer.responded_at = now
        offer.response_note = "Hết thời gian chờ màu vàng"
        await db.commit()
        raise HTTPException(status_code=409, detail="Offer response window has expired")

    if not req.accept:
        offer.status = "declined"
        offer.responded_at = now
        offer.response_note = req.note or "Cơ sở từ chối hỗ trợ"
        await db.commit()
        await db.refresh(offer)
        return TransferOfferOut(**(await _offer_payload(db, offer)))

    allocated = int(await db.scalar(
        select(func.count(TransferOrder.id)).where(
            TransferOrder.request_id == request.id,
            TransferOrder.state != TransferState.CANCELLED,
        )
    ) or 0)
    remaining = max(0, request.qty - allocated)
    if remaining == 0:
        offer.status = "cancelled"
        offer.responded_at = now
        offer.response_note = "Nơi nhận đã đủ số lượng"
        await db.commit()
        raise HTTPException(status_code=409, detail="Transfer request has already been fulfilled")

    source = await db.get(Facility, offer.source_facility_id)
    source_stock = int(await db.scalar(
        select(func.count(BloodUnit.id)).where(
            BloodUnit.held_by_facility_id == offer.source_facility_id,
            BloodUnit.component_code == request.component_code,
            BloodUnit.status == UnitStatus.AVAILABLE,
            BloodUnit.expires_at > now,
        )
    ) or 0)
    safety = int(((source.safety_threshold_json if source else None) or {}).get(
        request.component_code.value, 0
    ))
    reserve_qty = min(offer.offered_qty, remaining, max(0, source_stock - safety))
    candidates = (await db.execute(
        select(TransferCandidate, BloodUnit)
        .join(BloodUnit, BloodUnit.id == TransferCandidate.unit_id)
        .where(
            TransferCandidate.request_id == request.id,
            TransferCandidate.compatible.is_(True),
            BloodUnit.held_by_facility_id == offer.source_facility_id,
            BloodUnit.component_code == request.component_code,
            BloodUnit.status == UnitStatus.AVAILABLE,
            BloodUnit.expires_at > now,
        )
        .order_by(TransferCandidate.rank)
        .with_for_update()
    )).all()
    newly_reserved = 0
    for candidate, unit in candidates:
        if newly_reserved >= reserve_qty:
            break
        unit.status = UnitStatus.RESERVED
        db.add(TransferOrder(
            id=str(uuid.uuid4()),
            request_id=request.id,
            source_facility_id=offer.source_facility_id,
            unit_id=unit.id,
            state=TransferState.APPROVED,
            approved_by=principal.subject,
            at=now,
        ))
        newly_reserved += 1

    offer.responded_at = now
    offer.accepted_qty = newly_reserved
    offer.status = "accepted" if newly_reserved else "declined"
    offer.response_note = req.note or ("Đã nhận yêu cầu và giữ máu" if newly_reserved else "Kho khả dụng đã thay đổi")
    if allocated + newly_reserved >= request.qty:
        request.state = TransferState.APPROVED
        pending = (await db.execute(
            select(TransferOffer).where(
                TransferOffer.request_id == request.id,
                TransferOffer.status == "pending",
                TransferOffer.id != offer.id,
            )
        )).scalars().all()
        for other in pending:
            other.status = "cancelled"
            other.responded_at = now
            other.response_note = "Nơi nhận đã đủ số lượng"

    await db.commit()
    await db.refresh(offer)
    return TransferOfferOut(**(await _offer_payload(db, offer)))


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
    """Reserve the highest-ranked compatible units for coordinator review."""
    tr = await db.get(TransferRequest, request_id)
    if not tr:
        raise HTTPException(status_code=404, detail="Transfer request not found")

    if tr.state != TransferState.PENDING:
        raise HTTPException(status_code=400, detail=f"Request is in state {tr.state.value}, not PENDING")

    now = datetime.now(timezone.utc)
    stmt = (
        select(TransferCandidate, BloodUnit, Facility)
        .join(BloodUnit, TransferCandidate.unit_id == BloodUnit.id)
        .join(Facility, BloodUnit.held_by_facility_id == Facility.id)
        .where(TransferCandidate.request_id == request_id)
        .where(TransferCandidate.compatible.is_(True))
        .where(BloodUnit.status == UnitStatus.AVAILABLE)
        .where(BloodUnit.expires_at > now)
        .order_by(TransferCandidate.rank)
    )
    candidates = (await db.execute(stmt)).all()
    if not candidates:
        raise HTTPException(status_code=404, detail="No compatible candidates found")

    stock_rows = await db.execute(
        select(BloodUnit.held_by_facility_id, func.count(BloodUnit.id))
        .where(
            BloodUnit.component_code == tr.component_code,
            BloodUnit.status == UnitStatus.AVAILABLE,
            BloodUnit.expires_at > now,
        )
        .group_by(BloodUnit.held_by_facility_id)
    )
    available_by_facility = {row[0]: int(row[1]) for row in stock_rows}

    allocated_orders = await db.scalar(
        select(func.count(TransferOrder.id)).where(
            TransferOrder.request_id == request_id,
            TransferOrder.state != TransferState.CANCELLED,
        )
    ) or 0
    if allocated_orders >= tr.qty:
        raise HTTPException(status_code=409, detail="All requested units already have transfer orders")

    allocated_orders = int(allocated_orders)
    newly_allocated = 0
    seen_units: set[str] = set()
    for candidate, unit, source in candidates:
        if allocated_orders >= tr.qty:
            break
        if unit.id in seen_units or not source.opt_in:
            continue
        seen_units.add(unit.id)

        available = available_by_facility.get(source.id, 0)
        minimum = (source.safety_threshold_json or {}).get(tr.component_code.value, 0)
        if available <= 0 or available - 1 < minimum:
            continue

        unit.status = UnitStatus.RESERVED
        available_by_facility[source.id] = available - 1
        db.add(TransferOrder(
            id=str(uuid.uuid4()),
            request_id=request_id,
            source_facility_id=source.id,
            unit_id=unit.id,
            state=TransferState.APPROVED,
            approved_by=approved_by,
            at=now,
        ))
        allocated_orders += 1
        newly_allocated += 1

    if newly_allocated == 0:
        raise HTTPException(status_code=409, detail="No source can share without crossing its safety stock")

    # Keep a partially allocated request open so the coordinator can search
    # again and reserve the remaining units when another source is available.
    if allocated_orders >= tr.qty:
        tr.state = TransferState.APPROVED

    await db.commit()
    await db.refresh(tr)

    return TransferRequestOut.model_validate(tr)


@router.get("/request/{request_id}/orders", response_model=list[TransferOrderOut])
async def list_transfer_orders(
    request_id: str,
    db: AsyncSession = Depends(get_db),
):
    tr = await db.get(TransferRequest, request_id)
    if not tr:
        raise HTTPException(status_code=404, detail="Transfer request not found")
    result = await db.execute(
        select(TransferOrder)
        .where(TransferOrder.request_id == request_id)
        .order_by(TransferOrder.at, TransferOrder.id)
    )
    return result.scalars().all()


@router.post("/order/{order_id}/complete", response_model=TransferOrderOut)
async def complete_transfer_order(
    order_id: str,
    received_by: str = Query(default="console-user", min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    """Confirm physical delivery, move the unit, and record the support credit."""
    order = await db.get(TransferOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Transfer order not found")
    if order.state == TransferState.DELIVERED:
        raise HTTPException(status_code=409, detail="Transfer order is already delivered")
    if order.state not in (TransferState.APPROVED, TransferState.IN_TRANSIT):
        raise HTTPException(status_code=409, detail=f"Transfer order cannot be completed from {order.state.value}")

    request = await db.get(TransferRequest, order.request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Transfer request not found")

    unit = await db.get(BloodUnit, order.unit_id) if order.unit_id else None
    if unit is None:
        # Backfill an older approved order from its still-reserved candidate.
        legacy_result = await db.execute(
            select(BloodUnit)
            .join(TransferCandidate, TransferCandidate.unit_id == BloodUnit.id)
            .where(
                TransferCandidate.request_id == order.request_id,
                BloodUnit.held_by_facility_id == order.source_facility_id,
                BloodUnit.status == UnitStatus.RESERVED,
            )
            .order_by(TransferCandidate.rank)
            .limit(1)
        )
        unit = legacy_result.scalar_one_or_none()
        if unit is None:
            raise HTTPException(status_code=409, detail="Reserved blood unit for this order was not found")
        order.unit_id = unit.id

    now = datetime.now(timezone.utc)
    if unit.status != UnitStatus.RESERVED:
        raise HTTPException(status_code=409, detail="Blood unit is no longer reserved for this transfer")
    if unit.expires_at <= now:
        unit.status = UnitStatus.EXPIRED
        await db.commit()
        raise HTTPException(status_code=409, detail="Blood unit expired before delivery and was removed from available stock")

    source_id = order.source_facility_id
    destination_id = request.requester_facility_id
    unit.held_by_facility_id = destination_id
    unit.status = UnitStatus.AVAILABLE
    order.state = TransferState.DELIVERED
    order.completed_at = now
    db.add_all([
        InventoryEvent(
            id=str(uuid.uuid4()), unit_id=unit.id, event_type="transferred_out",
            at=now, actor_id=received_by,
            note=f"Giao cho cơ sở {destination_id} theo lệnh {order.id}",
        ),
        InventoryEvent(
            id=str(uuid.uuid4()), unit_id=unit.id, event_type="transferred_in",
            at=now, actor_id=received_by,
            note=f"Nhận từ cơ sở {source_id} theo lệnh {order.id}",
        ),
        FacilitySupportContribution(
            id=str(uuid.uuid4()),
            transfer_order_id=order.id,
            request_id=request.id,
            unit_id=unit.id,
            supporter_facility_id=source_id,
            beneficiary_facility_id=destination_id,
            component_code=unit.component_code,
            quantity=1,
            at=now,
        ),
    ])

    await db.flush()
    delivered_count = await db.scalar(
        select(func.count(TransferOrder.id)).where(
            TransferOrder.request_id == request.id,
            TransferOrder.state == TransferState.DELIVERED,
        )
    )
    if (delivered_count or 0) >= request.qty:
        request.state = TransferState.DELIVERED

    await db.commit()
    await db.refresh(order)
    return TransferOrderOut.model_validate(order)
