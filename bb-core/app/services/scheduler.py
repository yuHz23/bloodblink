"""
BB-Core — Bộ lập lịch tự nâng vòng SOS.

Trước P2, bốn mốc T+0/10/25/45 phút chỉ là một dòng chú thích trong `api/sos.py`:
muốn leo thang phải có người bấm tay. Ở đây nó thành việc thật.

Cách chạy: một tác vụ APScheduler quét mỗi `sos_scheduler_interval_seconds`, tìm
các sự kiện còn mở, tính vòng ĐÁNG LẼ phải tới theo thời gian đã trôi, rồi nâng
dần cho tới vòng đó.

Vì sao quét theo chu kỳ thay vì hẹn giờ từng sự kiện: máy chủ khởi động lại là
mọi hẹn giờ trong bộ nhớ bay hết, còn quét theo chu kỳ thì tự bắt kịp các sự kiện
lẽ ra đã phải leo thang lúc máy chủ đang tắt.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.database import (
    SOSEvent, TransferOffer, TransferOrder, TransferRequest, TransferState,
)
from app.services.sos_dispatch import escalate_event
from app.services.sos_dispatch import dispatch_ring, facility_cell
from app.services import audit

log = logging.getLogger("bb-core.scheduler")

_scheduler: Optional[AsyncIOScheduler] = None


def due_ring(opened_at: datetime, now: Optional[datetime] = None) -> int:
    """
    Vòng mà một sự kiện mở lúc `opened_at` lẽ ra đang ở, theo `settings.sos_rings`.

    Mốc mặc định [0, 10, 25, 45] phút → sau 30 phút là vòng 2.
    """
    now = now or datetime.now(timezone.utc)
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=timezone.utc)

    elapsed_min = (now - opened_at).total_seconds() / 60
    ring = 0
    for index, minutes in enumerate(settings.sos_rings):
        if elapsed_min >= minutes:
            ring = index
    return min(ring, 3)


async def escalate_due_events(session: Optional[AsyncSession] = None) -> int:
    """
    Nâng vòng mọi sự kiện đang trễ. Trả về số lần leo thang đã thực hiện.

    Nhận sẵn `session` để test gọi được mà không cần đụng tới engine toàn cục.
    """
    own_session = session is None
    db = session or async_session()
    escalations = 0

    try:
        now = datetime.now(timezone.utc)
        ttl_cutoff = now - timedelta(minutes=settings.sos_event_ttl_minutes)

        events = (await db.execute(
            select(SOSEvent).where(SOSEvent.status == "open")
        )).scalars().all()

        for event in events:
            opened = event.opened_at
            if opened is not None and opened.tzinfo is None:
                opened = opened.replace(tzinfo=timezone.utc)

            # Quá hạn mà vẫn chưa đủ người: đóng lại, thôi réo người hiến.
            if opened is not None and opened < ttl_cutoff:
                event.status = "expired"
                await db.commit()
                log.info("SOS %s quá hạn %d phút — đã đóng",
                         event.id, settings.sos_event_ttl_minutes)
                continue

            if opened is None:
                continue

            target = due_ring(opened, now)
            while event.ring < target:
                result = await escalate_event(db, event)
                escalations += 1
                log.info("SOS %s tự lên vòng %d: gọi thêm %d người (%d người đã gọi trước đó)",
                         event.id, result.ring, result.notified, result.already_notified)
    finally:
        if own_session:
            await db.close()

    return escalations


async def dispatch_unanswered_transfer_requests(session: Optional[AsyncSession] = None) -> int:
    """Start donor SOS when every ranked hospital offer declined or timed out."""
    own_session = session is None
    db = session or async_session()
    started = 0
    try:
        now = datetime.now(timezone.utc)
        requests = (await db.execute(
            select(TransferRequest)
            .where(TransferRequest.state == TransferState.PENDING)
            .with_for_update(skip_locked=True)
        )).scalars().all()

        for request in requests:
            offers = (await db.execute(
                select(TransferOffer).where(TransferOffer.request_id == request.id)
            )).scalars().all()
            if not offers:
                continue

            expired_any = False
            for offer in offers:
                expires = offer.expires_at
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if offer.status == "pending" and expires <= now:
                    offer.status = "expired"
                    offer.responded_at = now
                    offer.response_note = "Hết thời gian chờ màu vàng"
                    expired_any = True
            if expired_any:
                await db.flush()

            allocated = int(await db.scalar(
                select(func.count(TransferOrder.id)).where(
                    TransferOrder.request_id == request.id,
                    TransferOrder.state != TransferState.CANCELLED,
                )
            ) or 0)
            if allocated >= request.qty:
                request.state = TransferState.APPROVED
                for offer in offers:
                    if offer.status == "pending":
                        offer.status = "cancelled"
                        offer.responded_at = now
                        offer.response_note = "Nơi nhận đã đủ số lượng"
                await db.commit()
                continue

            if any(offer.status == "pending" for offer in offers):
                if expired_any:
                    await db.commit()
                continue

            # Prevent duplicate SOS if a coordinator already started one.
            existing_event = await db.scalar(
                select(SOSEvent.id).where(SOSEvent.request_id == request.id).limit(1)
            )
            if existing_event:
                continue

            remaining = max(1, request.qty - allocated)
            cell = await facility_cell(db, request.requester_facility_id)
            event = SOSEvent(
                id=str(uuid.uuid4()),
                request_id=request.id,
                ring=0,
                opened_at=now,
                target_count=remaining,
                accept_count=0,
                facility_id=request.requester_facility_id,
                component_code=request.component_code.value,
                abo=request.abo.value if request.abo else None,
                rh=request.rh.value if request.rh else None,
                urgency=request.urgency.value if request.urgency else "urgent",
                h3_cell=cell,
                status="open",
            )
            db.add(event)
            await db.flush()
            await audit.record(db, "system", audit.SOS_OPEN, {
                "event_id": event.id,
                "request_id": request.id,
                "facility_id": request.requester_facility_id,
                "reason": "transfer_offers_declined_or_expired",
                "remaining_qty": remaining,
                "ring": 0,
            })
            await db.commit()
            await dispatch_ring(db, event)
            started += 1
            log.info("Transfer request %s: offers ended; donor SOS started for %d units",
                     request.id, remaining)
    finally:
        if own_session:
            await db.close()
    return started


def start_scheduler() -> Optional[AsyncIOScheduler]:
    """Khởi động bộ quét. Gọi trong vòng đời FastAPI."""
    global _scheduler
    if not settings.sos_auto_escalate:
        log.info("Bỏ qua bộ lập lịch SOS (sos_auto_escalate=False)")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        escalate_due_events,
        trigger="interval",
        seconds=settings.sos_scheduler_interval_seconds,
        id="sos-escalation",
        # Máy bận thì bỏ lượt quá hạn thay vì dồn đống chạy bù.
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    _scheduler.add_job(
        dispatch_unanswered_transfer_requests,
        trigger="interval",
        seconds=settings.sos_scheduler_interval_seconds,
        id="transfer-to-sos-fallback",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    _scheduler.start()
    log.info("Bộ lập lịch SOS chạy mỗi %ds, mốc leo thang %s phút",
             settings.sos_scheduler_interval_seconds, settings.sos_rings)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
