"""Reconcile the donor SOS with a transfer request's remaining shortfall."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import case, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    SOSEvent,
    TransferOffer,
    TransferOrder,
    TransferRequest,
    TransferState,
)
from app.services import audit
from app.services.sos_dispatch import dispatch_initial_rings, facility_cell


async def start_sos_if_transfer_exhausted(
    db: AsyncSession,
    request_id: str,
    *,
    actor: str = "system",
) -> Optional[SOSEvent]:
    """Open or update one linked SOS as soon as pending hospitals cannot cover demand."""
    request = await db.scalar(
        select(TransferRequest)
        .where(TransferRequest.id == request_id)
        .with_for_update()
    )
    if request is None:
        return None

    offers = (await db.execute(
        select(TransferOffer).where(TransferOffer.request_id == request_id)
    )).scalars().all()

    allocated = int(await db.scalar(
        select(func.count(TransferOrder.id)).where(
            TransferOrder.request_id == request_id,
            TransferOrder.state != TransferState.CANCELLED,
        )
    ) or 0)
    if request.state == TransferState.PENDING and allocated >= request.qty:
        request.state = TransferState.APPROVED
        for offer in offers:
            if offer.status == "pending":
                offer.status = "cancelled"
                offer.responded_at = datetime.now(timezone.utc)
                offer.response_note = "Nơi nhận đã đủ số lượng"

    existing = await db.scalar(
        select(SOSEvent)
        .where(SOSEvent.request_id == request_id)
        .order_by(
            case((SOSEvent.status == "open", 0), else_=1),
            desc(SOSEvent.opened_at),
        )
        .limit(1)
        .with_for_update()
    )
    if existing is not None and existing.status in ("completed", "cancelled"):
        await db.commit()
        return existing

    if request.state == TransferState.CANCELLED:
        if existing is not None:
            existing.status = "cancelled"
            await db.commit()
        return existing

    if request.state != TransferState.PENDING:
        remaining = 0
    else:
        pending_capacity = sum(
            max(0, offer.offered_qty)
            for offer in offers
            if offer.status == "pending"
        )
        remaining = max(0, request.qty - allocated - pending_capacity)

    if not offers or (existing is None and remaining == 0):
        await db.commit()
        return None

    now = datetime.now(timezone.utc)
    if existing is None:
        childbearing_age = request.recipient_sex == "F" and (
            request.recipient_age is None or 18 <= request.recipient_age <= 45
        )
        event = SOSEvent(
            id=str(uuid.uuid4()),
            request_id=request.id,
            ring=0,
            opened_at=now,
            target_count=remaining,
            accept_count=0,
            facility_id=request.requester_facility_id,
            component_code=request.component_code.value,
            # Match the transfer engine's conservative defaults for unknown
            # recipient type, so the donor campaign uses the same RhD rules.
            abo=request.abo.value if request.abo else "O",
            rh=request.rh.value if request.rh else ("-" if childbearing_age else "+"),
            recipient_sex=request.recipient_sex,
            recipient_age=request.recipient_age,
            urgency=request.urgency.value if request.urgency else "urgent",
            h3_cell=await facility_cell(db, request.requester_facility_id),
            status="open",
        )
        db.add(event)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            return await db.scalar(
                select(SOSEvent).where(SOSEvent.request_id == request_id).limit(1)
            )
        await audit.record(db, actor, audit.SOS_OPEN, {
            "event_id": event.id,
            "request_id": request.id,
            "facility_id": request.requester_facility_id,
            "reason": "hospital_capacity_shortfall",
            "remaining_qty": remaining,
            "ring": 0,
        })
    else:
        event = existing
        previous_target = event.target_count
        shortfall_changed = remaining != previous_target
        event.target_count = remaining
        if remaining == 0 or event.accept_count >= remaining:
            event.status = "fulfilled"
            await db.commit()
            await db.refresh(event)
            return event

        reopened = event.status in ("fulfilled", "expired") and shortfall_changed
        if reopened:
            event.status = "open"
            event.ring = 0
            event.opened_at = now

        # A newly exposed shortfall can require more invitations while the
        # same SOS is already open. dispatch_ring excludes donors already
        # invited, so retrying is safe and does not send duplicate alerts.
        if event.status == "open" and shortfall_changed:
            result, auto_escalations = await dispatch_initial_rings(db, event)
            if result.notified == 0 and event.ring >= 3:
                event.status = "expired"
            if auto_escalations:
                await audit.record(db, actor, audit.SOS_ESCALATE, {
                    "event_id": event.id,
                    "ring": event.ring,
                    "donors_notified": result.notified,
                    "already_notified": result.already_notified,
                    "automatic_escalations": auto_escalations,
                    "reason": "transfer_shortfall_increased",
                })

        await db.commit()
        await db.refresh(event)
        return event

    result, auto_escalations = await dispatch_initial_rings(db, event)
    if result.notified == 0 and event.ring >= 3:
        event.status = "expired"
    if auto_escalations:
        await audit.record(db, actor, audit.SOS_ESCALATE, {
            "event_id": event.id,
            "ring": event.ring,
            "donors_notified": result.notified,
            "already_notified": result.already_notified,
            "automatic_escalations": auto_escalations,
            "reason": "no_donors_found_in_previous_ring",
        })
    await db.commit()
    await db.refresh(event)
    return event
